// vizor_decode/preprocess.hpp
//
// GPU preprocessing kernels. Take an NVDEC NV12 surface (AVFrame
// pix_fmt = AV_PIX_FMT_CUDA, underlying frame is NV12), turn it into
// an inference-ready CHW float tensor in VRAM. Zero PCIe transfers
// on the hot path.
//
// Public surface is deliberately thin — the kernels are CUDA C++ and
// live in preprocess.cu; this header lets pure-C++ TUs include it
// without dragging in nppi.h / cuda_runtime.h.

#pragma once

#include <cstddef>
#include <cstdint>

namespace vizor::decode {

// Output layout. Triton's most common YOLOv8/v12 export wants
// NCHW float32 RGB normalised to [0,1].
struct PreprocessOutput {
    void*    device_ptr = nullptr;   // CUDA device pointer (float*)
    size_t   bytes      = 0;         // total bytes in the buffer
    int      n          = 1;
    int      c          = 3;
    int      h          = 0;
    int      w          = 0;
};

// Convert NV12 (Y plane + interleaved UV) → resized RGB float CHW
// on GPU. Letterboxing preserves aspect ratio; padding is mid-grey
// (114/255) which matches Ultralytics defaults.
//
// All allocations live as long as the Preprocessor instance — the
// caller can call run() back-to-back without re-allocating.
class Preprocessor {
public:
    Preprocessor(int dst_w, int dst_h);
    ~Preprocessor();

    // Configure normalisation so one kernel serves different models:
    //   out = pixel * norm_scale - norm_mean ; swap_rb=true → RGB out (YOLO),
    //   false → BGR out (SCRFD); pad_val = raw pad pixel (114 YOLO, 0 SCRFD);
    //   center_pad=true → centred letterbox (YOLO), false → top-left (SCRFD).
    // Defaults match YOLO so existing callers are unaffected.
    // SCRFD: set_norm(1.0f/128, 127.5f, false, 0.0f, false).
    void set_norm(float norm_scale, float norm_mean, bool swap_rb,
                  float pad_val, bool center_pad);

    int dst_w() const;
    int dst_h() const;

    // Like run_bgr but also copies the GPU result into the caller-provided host
    // buffer `out` (NCHW float32, 1*3*dst_h*dst_w). The cudaMemcpy lives here (nvcc
    // unit) so the pybind .cpp doesn't need the CUDA toolchain.
    void run_bgr_host(const uint8_t* host_bgr, int src_w, int src_h, float* out);

    Preprocessor(const Preprocessor&) = delete;
    Preprocessor& operator=(const Preprocessor&) = delete;

    // src_y, src_uv: CUDA device pointers from AVFrame.data[0],[1]
    // src_y_pitch, src_uv_pitch: AVFrame.linesize[0],[1] (bytes)
    // src_w, src_h: source dimensions
    //
    // Returns a PreprocessOutput pointing at the internal device buffer.
    // The buffer is reused on the next call — copy out if you need to
    // keep it.
    PreprocessOutput run(
        const uint8_t* src_y,  size_t src_y_pitch,
        const uint8_t* src_uv, size_t src_uv_pitch,
        int src_w, int src_h);

    // Host-side BGR variant. Uploads the host buffer to an internal
    // staging GPU buffer, then runs the letterbox+normalise kernel
    // straight from BGR (skipping the NV12->RGB step). Useful while
    // the worker still consumes decoded BGR ndarrays — the win is
    // the resize+normalise+CHW transpose moving to GPU, plus the
    // Triton input bytes never leaving VRAM.
    PreprocessOutput run_bgr(
        const uint8_t* host_bgr,  // tightly packed HxWx3 uint8
        int src_w, int src_h);

    // Diagnostic — verify CUDA is actually available before
    // committing to a decoder pipeline.
    static bool cuda_available();

private:
    struct Impl;
    Impl* impl_;
};

}  // namespace vizor::decode
