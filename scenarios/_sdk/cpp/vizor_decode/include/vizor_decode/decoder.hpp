// vizor_decode/decoder.hpp
//
// RTSP → NVDEC → BGR pipeline.
//
// Usage:
//   Decoder dec("rtsp://cam/stream", DecoderConfig{});
//   while (auto frame = dec.next_frame()) {
//       // process frame->bgr (width*height*3 bytes)
//   }
//
// Lifecycle:
//   - Constructor opens the URL, negotiates h264_cuvid hwaccel, and
//     starts the decoder. Throws DecodeError on failure.
//   - next_frame() blocks until a decoded frame is ready or the
//     stream ends. Returns std::nullopt on EOF.
//   - Destructor frees FFmpeg + CUDA resources.
//
// Day 1 limitation: synchronous, one camera per Decoder instance,
// host-side BGR output. Async ringbuffer + zero-copy land on Day 3.

#pragma once

#include "frame.hpp"

#include <memory>
#include <optional>
#include <string>

namespace vizor::decode {

struct DecoderConfig {
    // RTSP transport. "tcp" is reliable but adds latency; "udp" is
    // faster but drops on congestion. Match the camera's vendor
    // recommendation.
    std::string rtsp_transport = "tcp";

    // Socket read timeout, microseconds. FFmpeg calls it "stimeout".
    int64_t socket_timeout_us = 5'000'000;  // 5 s

    // Try NVDEC first; fall back to software libavcodec h264 decoder
    // on failure. Set false to force CPU decode (useful for
    // A/B benchmarks).
    bool prefer_hwaccel = true;

    // CUDA device index. -1 = first visible GPU.
    int gpu_index = 0;
};

class Decoder {
public:
    Decoder(const std::string& url, const DecoderConfig& cfg);
    ~Decoder();

    // Move-only — RAII handles aren't safe to copy.
    Decoder(const Decoder&) = delete;
    Decoder& operator=(const Decoder&) = delete;
    Decoder(Decoder&&) noexcept;
    Decoder& operator=(Decoder&&) noexcept;

    // Block for the next decoded frame.
    // Returns nullopt on end-of-stream OR after .stop() was called.
    std::optional<Frame> next_frame();

    // Signal next_frame() to wake up + return nullopt. Safe from
    // another thread. Day 3+ uses this; Day 1 ignore.
    void stop();

    // Whether the active codec is NVDEC (h264_cuvid) or software.
    bool is_hw_decoder() const noexcept;

    // Diagnostics — frames decoded + packets read so far.
    uint64_t frames_decoded() const noexcept;
    uint64_t packets_read() const noexcept;

private:
    // Pimpl idiom: hide FFmpeg headers from public API consumers.
    // Anyone including decoder.hpp shouldn't need libavcodec on their
    // include path. Forward-declare + heap-allocate.
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace vizor::decode
