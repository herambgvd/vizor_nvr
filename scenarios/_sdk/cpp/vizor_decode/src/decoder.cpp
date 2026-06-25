// vizor_decode/decoder.cpp
//
// Implementation of Decoder. FFmpeg API is C; we wrap each handle in
// a unique_ptr with a custom deleter so an exception mid-construction
// can't leak.
//
// NVDEC path overview:
//   1. Open RTSP via avformat_open_input (low-latency options).
//   2. Find video stream + matching AVCodec (h264_cuvid if NVDEC ok).
//   3. Allocate AVHWDeviceContext(CUDA) and attach to codec ctx.
//      Tells the decoder "output frames live in VRAM, NV12 layout."
//   4. avcodec_open2() — opens the decoder.
//   5. Read loop: av_read_frame -> avcodec_send_packet -> receive_frame.
//   6. Each AVFrame is on GPU (format = AV_PIX_FMT_CUDA). Transfer
//      to host via av_hwframe_transfer_data, then NV12 -> BGR via
//      sws_scale. Day 2 swap this for a CUDA kernel (zero copy).

#include "vizor_decode/decoder.hpp"
#include "vizor_decode/errors.hpp"

#include <atomic>
#include <cstring>
#include <iostream>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/imgutils.h>
#include <libavutil/opt.h>
#include <libavutil/pixdesc.h>
#include <libswscale/swscale.h>
}

namespace vizor::decode {

namespace {

// Custom deleters for RAII wrappers around C handles.
struct AVFormatCtxDeleter {
    void operator()(AVFormatContext* p) const noexcept {
        if (p) avformat_close_input(&p);
    }
};
struct AVCodecCtxDeleter {
    void operator()(AVCodecContext* p) const noexcept {
        if (p) avcodec_free_context(&p);
    }
};
struct AVBufferRefDeleter {
    void operator()(AVBufferRef* p) const noexcept {
        if (p) av_buffer_unref(&p);
    }
};
struct AVPacketDeleter {
    void operator()(AVPacket* p) const noexcept {
        if (p) av_packet_free(&p);
    }
};
struct AVFrameDeleter {
    void operator()(AVFrame* p) const noexcept {
        if (p) av_frame_free(&p);
    }
};
struct SwsCtxDeleter {
    void operator()(SwsContext* p) const noexcept {
        if (p) sws_freeContext(p);
    }
};

using FormatCtxPtr = std::unique_ptr<AVFormatContext, AVFormatCtxDeleter>;
using CodecCtxPtr  = std::unique_ptr<AVCodecContext,  AVCodecCtxDeleter>;
using HwCtxPtr     = std::unique_ptr<AVBufferRef,     AVBufferRefDeleter>;
using PacketPtr    = std::unique_ptr<AVPacket,        AVPacketDeleter>;
using FramePtr     = std::unique_ptr<AVFrame,         AVFrameDeleter>;
using SwsCtxPtr    = std::unique_ptr<SwsContext,      SwsCtxDeleter>;

// FFmpeg uses a global callback to ask "which pixel format do you
// support?" during stream setup. For NVDEC we MUST return
// AV_PIX_FMT_CUDA — otherwise libavcodec assumes software output.
AVPixelFormat get_hw_pix_format(AVCodecContext*,
                                const AVPixelFormat* pix_fmts) {
    for (const AVPixelFormat* p = pix_fmts; *p != AV_PIX_FMT_NONE; ++p) {
        if (*p == AV_PIX_FMT_CUDA) return *p;
    }
    return AV_PIX_FMT_NONE;
}

}  // namespace

struct Decoder::Impl {
    DecoderConfig cfg;
    FormatCtxPtr fmt;
    CodecCtxPtr  codec;
    HwCtxPtr     hw_device;
    SwsCtxPtr    sws;          // GPU->CPU conversion to BGR
    int video_stream_index = -1;
    bool hw_active = false;
    std::atomic<bool> stop_flag{false};
    std::atomic<uint64_t> n_packets{0};
    std::atomic<uint64_t> n_frames{0};

    // Reusable buffers — avoid alloc per frame.
    PacketPtr pkt;
    FramePtr  hw_frame;   // GPU surface (AV_PIX_FMT_CUDA)
    FramePtr  sw_frame;   // Host NV12 after transfer
    FramePtr  bgr_frame;  // Host BGR after sws_scale
    int sws_w = 0, sws_h = 0;  // detect resolution change

    void open(const std::string& url) {
        // 1. Allocate format context + set input options BEFORE open.
        AVDictionary* opts = nullptr;
        av_dict_set(&opts, "rtsp_transport", cfg.rtsp_transport.c_str(), 0);
        av_dict_set(&opts, "stimeout",
                    std::to_string(cfg.socket_timeout_us).c_str(), 0);
        av_dict_set(&opts, "max_delay", "100000", 0);
        av_dict_set(&opts, "fflags", "nobuffer+discardcorrupt", 0);
        av_dict_set(&opts, "flags", "low_delay", 0);
        av_dict_set(&opts, "probesize", "32", 0);
        av_dict_set(&opts, "analyzeduration", "0", 0);

        AVFormatContext* raw_fmt = nullptr;
        int err = avformat_open_input(&raw_fmt, url.c_str(), nullptr, &opts);
        av_dict_free(&opts);
        if (err < 0) throw DecodeError("avformat_open_input", err);
        fmt.reset(raw_fmt);

        // 2. Probe stream info — needed to find the video stream.
        err = avformat_find_stream_info(fmt.get(), nullptr);
        if (err < 0) throw DecodeError("avformat_find_stream_info", err);

        // 3. Pick the first video stream.
        for (unsigned i = 0; i < fmt->nb_streams; ++i) {
            if (fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                video_stream_index = static_cast<int>(i);
                break;
            }
        }
        if (video_stream_index < 0)
            throw DecodeError("no video stream found");

        AVStream* st = fmt->streams[video_stream_index];

        // 4. Choose decoder — try cuvid first if hwaccel requested.
        const AVCodec* dec = nullptr;
        if (cfg.prefer_hwaccel && st->codecpar->codec_id == AV_CODEC_ID_H264) {
            dec = avcodec_find_decoder_by_name("h264_cuvid");
        } else if (cfg.prefer_hwaccel &&
                   st->codecpar->codec_id == AV_CODEC_ID_HEVC) {
            dec = avcodec_find_decoder_by_name("hevc_cuvid");
        }
        if (!dec) {
            // Fall back to software.
            dec = avcodec_find_decoder(st->codecpar->codec_id);
            if (!dec) throw DecodeError("no decoder for codec id");
        }
        bool tried_hw = (std::string(dec->name).find("_cuvid") != std::string::npos);

        // 5. Allocate codec context + copy params from stream.
        AVCodecContext* raw_codec = avcodec_alloc_context3(dec);
        if (!raw_codec) throw DecodeError("avcodec_alloc_context3");
        codec.reset(raw_codec);

        err = avcodec_parameters_to_context(codec.get(), st->codecpar);
        if (err < 0) throw DecodeError("avcodec_parameters_to_context", err);

        // 6. If using NVDEC, create CUDA hwdevice + attach. On
        //    failure (e.g. CUDA_ERROR_OUT_OF_MEMORY, no nvidia
        //    runtime) tear the cuvid codec down completely and rebuild
        //    the codec context with the software decoder — leaving the
        //    cuvid decoder around with no hw_device_ctx makes
        //    avcodec_open2 fail with -542398533.
        if (tried_hw) {
            AVBufferRef* raw_hw = nullptr;
            err = av_hwdevice_ctx_create(
                &raw_hw, AV_HWDEVICE_TYPE_CUDA,
                std::to_string(cfg.gpu_index).c_str(), nullptr, 0);
            if (err < 0) {
                std::cerr << "[vizor_decode] CUDA hwdevice init failed; "
                          << "falling back to software decode\n";
                tried_hw = false;
                // Drop the cuvid codec context — software path needs
                // a fresh AVCodecContext built for the sw decoder.
                codec.reset();
                const AVCodec* sw_dec = avcodec_find_decoder(
                    st->codecpar->codec_id);
                if (!sw_dec) throw DecodeError("software decoder not found");
                dec = sw_dec;
                AVCodecContext* raw_sw = avcodec_alloc_context3(dec);
                if (!raw_sw) throw DecodeError("avcodec_alloc_context3 sw");
                codec.reset(raw_sw);
                int e2 = avcodec_parameters_to_context(codec.get(),
                                                       st->codecpar);
                if (e2 < 0)
                    throw DecodeError("avcodec_parameters_to_context sw", e2);
            } else {
                hw_device.reset(raw_hw);
                codec->hw_device_ctx = av_buffer_ref(hw_device.get());
                codec->get_format = get_hw_pix_format;
                hw_active = true;
            }
        }

        // 7. Open the decoder.
        err = avcodec_open2(codec.get(), dec, nullptr);
        if (err < 0) throw DecodeError("avcodec_open2", err);

        // 8. Preallocate reusable AVPacket + AVFrames.
        pkt.reset(av_packet_alloc());
        hw_frame.reset(av_frame_alloc());
        sw_frame.reset(av_frame_alloc());
        bgr_frame.reset(av_frame_alloc());
        if (!pkt || !hw_frame || !sw_frame || !bgr_frame)
            throw DecodeError("av_*_alloc returned null");
    }

    // Convert NV12 host frame -> BGR24 host frame using sws_scale.
    // Lazily build sws context — recreate if input resolution changes.
    void nv12_to_bgr(const AVFrame* src) {
        if (sws_w != src->width || sws_h != src->height || !sws) {
            sws.reset(sws_getContext(
                src->width, src->height,
                static_cast<AVPixelFormat>(src->format),
                src->width, src->height, AV_PIX_FMT_BGR24,
                SWS_BILINEAR, nullptr, nullptr, nullptr));
            if (!sws) throw DecodeError("sws_getContext");
            sws_w = src->width;
            sws_h = src->height;

            // Allocate dst BGR frame buffer.
            av_frame_unref(bgr_frame.get());
            bgr_frame->format = AV_PIX_FMT_BGR24;
            bgr_frame->width  = src->width;
            bgr_frame->height = src->height;
            int err = av_frame_get_buffer(bgr_frame.get(), 32);
            if (err < 0) throw DecodeError("av_frame_get_buffer bgr", err);
        }
        sws_scale(sws.get(), src->data, src->linesize, 0,
                  src->height, bgr_frame->data, bgr_frame->linesize);
    }

    std::optional<Frame> next_frame() {
        while (!stop_flag.load(std::memory_order_relaxed)) {
            // Drain decoder first — may have buffered frames from last
            // packet send.
            int err = avcodec_receive_frame(codec.get(), hw_frame.get());
            if (err == 0) {
                ++n_frames;
                AVFrame* src = hw_frame.get();
                FramePtr transferred;

                // If frame is on GPU, copy to host first.
                if (hw_active && src->format == AV_PIX_FMT_CUDA) {
                    transferred.reset(av_frame_alloc());
                    int terr = av_hwframe_transfer_data(
                        transferred.get(), src, 0);
                    if (terr < 0) {
                        av_frame_unref(hw_frame.get());
                        throw DecodeError("av_hwframe_transfer_data", terr);
                    }
                    src = transferred.get();
                }

                nv12_to_bgr(src);

                Frame out;
                out.width  = bgr_frame->width;
                out.height = bgr_frame->height;
                out.hw_decoded = hw_active;
                out.pts_us = src->pts == AV_NOPTS_VALUE ? -1 : src->pts;
                // Copy BGR bytes into a tight buffer (no row padding).
                const size_t row_bytes = static_cast<size_t>(out.width) * 3;
                out.bgr.resize(row_bytes * out.height);
                for (int y = 0; y < out.height; ++y) {
                    std::memcpy(
                        out.bgr.data() + static_cast<size_t>(y) * row_bytes,
                        bgr_frame->data[0] +
                            static_cast<size_t>(y) * bgr_frame->linesize[0],
                        row_bytes);
                }

                av_frame_unref(hw_frame.get());
                return out;
            }
            if (err != AVERROR(EAGAIN) && err != AVERROR_EOF) {
                throw DecodeError("avcodec_receive_frame", err);
            }
            if (err == AVERROR_EOF) return std::nullopt;

            // Need more packets — read next one.
            err = av_read_frame(fmt.get(), pkt.get());
            if (err == AVERROR_EOF) {
                // Flush decoder.
                avcodec_send_packet(codec.get(), nullptr);
                continue;
            }
            if (err < 0) throw DecodeError("av_read_frame", err);

            ++n_packets;
            if (pkt->stream_index == video_stream_index) {
                err = avcodec_send_packet(codec.get(), pkt.get());
                if (err < 0 && err != AVERROR(EAGAIN)) {
                    av_packet_unref(pkt.get());
                    throw DecodeError("avcodec_send_packet", err);
                }
            }
            av_packet_unref(pkt.get());
        }
        return std::nullopt;  // stopped
    }
};

Decoder::Decoder(const std::string& url, const DecoderConfig& cfg)
    : impl_(std::make_unique<Impl>()) {
    impl_->cfg = cfg;
    impl_->open(url);
}

Decoder::~Decoder() = default;
Decoder::Decoder(Decoder&&) noexcept = default;
Decoder& Decoder::operator=(Decoder&&) noexcept = default;

std::optional<Frame> Decoder::next_frame() { return impl_->next_frame(); }
void Decoder::stop() { impl_->stop_flag.store(true); }

bool Decoder::is_hw_decoder() const noexcept { return impl_->hw_active; }
uint64_t Decoder::frames_decoded() const noexcept {
    return impl_->n_frames.load();
}
uint64_t Decoder::packets_read() const noexcept {
    return impl_->n_packets.load();
}

}  // namespace vizor::decode
