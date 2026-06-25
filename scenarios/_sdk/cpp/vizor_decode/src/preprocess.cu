// vizor_decode/preprocess.cu
//
// CUDA kernels for the NVDEC -> Triton-ready tensor pipeline.
//
// Pipeline per frame:
//   NV12 source on GPU  (Y plane + interleaved UV plane)
//       │
//       │  nv12_to_rgb_letterbox_kernel
//       │  (single kernel: YUV→RGB, bilinear resize, letterbox pad,
//       │   normalise to float [0,1], NCHW layout)
//       ▼
//   float NCHW RGB tensor on GPU  (ready for Triton)
//
// One kernel does it all so we read each source pixel exactly once
// and write each destination pixel exactly once. Intermediate
// allocations would double memory bandwidth.

#include "vizor_decode/preprocess.hpp"

#include <cstdio>
#include <cuda_runtime.h>
#include <stdexcept>

namespace vizor::decode {

namespace {

// BT.601 limited-range YUV → RGB. Camera streams are almost always
// limited-range. Switch to full-range coefficients if your source
// reports JFIF / pc range.
__device__ __forceinline__ void yuv2rgb(
    float y, float u, float v,
    float& r, float& g, float& b) {
    y = y - 16.0f;
    u = u - 128.0f;
    v = v - 128.0f;
    r = 1.164f * y                 + 1.596f * v;
    g = 1.164f * y - 0.392f * u    - 0.813f * v;
    b = 1.164f * y + 2.017f * u;
    r = fminf(fmaxf(r, 0.0f), 255.0f);
    g = fminf(fmaxf(g, 0.0f), 255.0f);
    b = fminf(fmaxf(b, 0.0f), 255.0f);
}

// Single kernel that does the entire preprocess.
//
// Each thread writes one (dst_x, dst_y) pixel into the CHW float
// tensor.
__global__ void nv12_to_rgb_letterbox_kernel(
    const uint8_t* __restrict__ y_plane,  size_t y_pitch,
    const uint8_t* __restrict__ uv_plane, size_t uv_pitch,
    int src_w, int src_h,
    float* __restrict__ dst,  // CHW, contiguous
    int dst_w, int dst_h,
    // Letterbox scale + offsets — precomputed on host:
    float scale, int pad_x, int pad_y, int scaled_w, int scaled_h) {
    const int x = blockIdx.x * blockDim.x + threadIdx.x;
    const int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= dst_w || y >= dst_h) return;

    const int dst_plane = dst_w * dst_h;
    float* dst_r = dst;
    float* dst_g = dst + dst_plane;
    float* dst_b = dst + dst_plane * 2;
    const int dst_idx = y * dst_w + x;

    // Letterbox: if outside the scaled image region, emit pad colour
    // (Ultralytics uses 114/255).
    if (x < pad_x || y < pad_y ||
        x >= pad_x + scaled_w || y >= pad_y + scaled_h) {
        const float pad = 114.0f / 255.0f;
        dst_r[dst_idx] = pad;
        dst_g[dst_idx] = pad;
        dst_b[dst_idx] = pad;
        return;
    }

    // Map (dst_x, dst_y) back into source space (bilinear sample).
    const float sx = (x - pad_x + 0.5f) / scale - 0.5f;
    const float sy = (y - pad_y + 0.5f) / scale - 0.5f;
    int   sx0 = static_cast<int>(floorf(sx));
    int   sy0 = static_cast<int>(floorf(sy));
    const float fx = sx - sx0;
    const float fy = sy - sy0;
    int sx1 = sx0 + 1;
    int sy1 = sy0 + 1;
    if (sx0 < 0) sx0 = 0;
    if (sy0 < 0) sy0 = 0;
    if (sx1 >= src_w) sx1 = src_w - 1;
    if (sy1 >= src_h) sy1 = src_h - 1;

    // Sample Y at four neighbour pixels.
    const float y00 = y_plane[sy0 * y_pitch + sx0];
    const float y01 = y_plane[sy0 * y_pitch + sx1];
    const float y10 = y_plane[sy1 * y_pitch + sx0];
    const float y11 = y_plane[sy1 * y_pitch + sx1];
    const float yv =
        (1 - fx) * (1 - fy) * y00 + fx * (1 - fy) * y01 +
        (1 - fx) *      fy  * y10 + fx *      fy  * y11;

    // UV plane is half-res, interleaved. Use nearest-neighbour for
    // chroma — bilinear there has ~0 quality impact for YOLO input.
    const int uv_x = sx0 / 2;
    const int uv_y = sy0 / 2;
    const float u = uv_plane[uv_y * uv_pitch + uv_x * 2 + 0];
    const float v = uv_plane[uv_y * uv_pitch + uv_x * 2 + 1];

    float r, g, b;
    yuv2rgb(yv, u, v, r, g, b);

    dst_r[dst_idx] = r * (1.0f / 255.0f);
    dst_g[dst_idx] = g * (1.0f / 255.0f);
    dst_b[dst_idx] = b * (1.0f / 255.0f);
}

// BGR → letterboxed CHW float RGB kernel. Mirrors the NV12 path but
// skips the YUV→RGB conversion (input is already BGR).
__global__ void bgr_letterbox_kernel(
    const uint8_t* __restrict__ src_bgr, size_t src_pitch,
    int src_w, int src_h,
    float* __restrict__ dst,
    int dst_w, int dst_h,
    float scale, int pad_x, int pad_y, int scaled_w, int scaled_h) {
    const int x = blockIdx.x * blockDim.x + threadIdx.x;
    const int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= dst_w || y >= dst_h) return;

    const int dst_plane = dst_w * dst_h;
    float* dst_r = dst;
    float* dst_g = dst + dst_plane;
    float* dst_b = dst + dst_plane * 2;
    const int dst_idx = y * dst_w + x;

    if (x < pad_x || y < pad_y ||
        x >= pad_x + scaled_w || y >= pad_y + scaled_h) {
        const float pad = 114.0f / 255.0f;
        dst_r[dst_idx] = pad;
        dst_g[dst_idx] = pad;
        dst_b[dst_idx] = pad;
        return;
    }

    const float sx = (x - pad_x + 0.5f) / scale - 0.5f;
    const float sy = (y - pad_y + 0.5f) / scale - 0.5f;
    int   sx0 = static_cast<int>(floorf(sx));
    int   sy0 = static_cast<int>(floorf(sy));
    const float fx = sx - sx0;
    const float fy = sy - sy0;
    int sx1 = sx0 + 1;
    int sy1 = sy0 + 1;
    if (sx0 < 0) sx0 = 0;
    if (sy0 < 0) sy0 = 0;
    if (sx1 >= src_w) sx1 = src_w - 1;
    if (sy1 >= src_h) sy1 = src_h - 1;

    // BGR is interleaved: each pixel is 3 bytes (B, G, R).
    auto sample = [&](int sx_, int sy_, int chan) -> float {
        return src_bgr[sy_ * src_pitch + sx_ * 3 + chan];
    };

    auto bilerp = [&](int chan) -> float {
        const float v00 = sample(sx0, sy0, chan);
        const float v01 = sample(sx1, sy0, chan);
        const float v10 = sample(sx0, sy1, chan);
        const float v11 = sample(sx1, sy1, chan);
        return (1 - fx) * (1 - fy) * v00 + fx * (1 - fy) * v01 +
               (1 - fx) *      fy  * v10 + fx *      fy  * v11;
    };

    // Source is BGR, model wants RGB → swap order.
    const float b = bilerp(0);
    const float g = bilerp(1);
    const float r = bilerp(2);

    dst_r[dst_idx] = r * (1.0f / 255.0f);
    dst_g[dst_idx] = g * (1.0f / 255.0f);
    dst_b[dst_idx] = b * (1.0f / 255.0f);
}

}  // namespace

struct Preprocessor::Impl {
    int dst_w;
    int dst_h;
    float*  d_buf = nullptr;
    size_t  bytes = 0;
    cudaStream_t stream = nullptr;
    // Staging buffer for the BGR-upload variant. Sized on first call
    // and grown if the source resolution changes.
    uint8_t* d_bgr_stage = nullptr;
    size_t   bgr_bytes = 0;
};

Preprocessor::Preprocessor(int dst_w, int dst_h)
    : impl_(new Impl()) {
    impl_->dst_w = dst_w;
    impl_->dst_h = dst_h;
    impl_->bytes = static_cast<size_t>(dst_w) * dst_h * 3 * sizeof(float);
    cudaError_t e = cudaMalloc(&impl_->d_buf, impl_->bytes);
    if (e != cudaSuccess) {
        delete impl_;
        impl_ = nullptr;
        std::fprintf(stderr, "[preprocess] cudaMalloc failed: %s\n",
                     cudaGetErrorString(e));
        throw std::runtime_error("cudaMalloc");
    }
    cudaStreamCreate(&impl_->stream);
}

Preprocessor::~Preprocessor() {
    if (!impl_) return;
    if (impl_->d_buf)        cudaFree(impl_->d_buf);
    if (impl_->d_bgr_stage)  cudaFree(impl_->d_bgr_stage);
    if (impl_->stream)       cudaStreamDestroy(impl_->stream);
    delete impl_;
}

PreprocessOutput Preprocessor::run_bgr(
    const uint8_t* host_bgr, int src_w, int src_h) {
    const size_t needed = static_cast<size_t>(src_w) * src_h * 3;
    if (needed > impl_->bgr_bytes) {
        if (impl_->d_bgr_stage) cudaFree(impl_->d_bgr_stage);
        cudaError_t e = cudaMalloc(&impl_->d_bgr_stage, needed);
        if (e != cudaSuccess) {
            impl_->d_bgr_stage = nullptr;
            impl_->bgr_bytes = 0;
            throw std::runtime_error("cudaMalloc bgr stage");
        }
        impl_->bgr_bytes = needed;
    }
    // Async upload to bridge host BGR into GPU memory. Then the
    // letterbox+normalise kernel runs straight out of that staging
    // buffer — no extra intermediate.
    cudaMemcpyAsync(impl_->d_bgr_stage, host_bgr, needed,
                    cudaMemcpyHostToDevice, impl_->stream);

    const float sx = static_cast<float>(impl_->dst_w) / src_w;
    const float sy = static_cast<float>(impl_->dst_h) / src_h;
    const float scale = sx < sy ? sx : sy;
    const int scaled_w = static_cast<int>(src_w * scale + 0.5f);
    const int scaled_h = static_cast<int>(src_h * scale + 0.5f);
    const int pad_x = (impl_->dst_w - scaled_w) / 2;
    const int pad_y = (impl_->dst_h - scaled_h) / 2;

    dim3 block(16, 16);
    dim3 grid((impl_->dst_w + 15) / 16, (impl_->dst_h + 15) / 16);

    bgr_letterbox_kernel<<<grid, block, 0, impl_->stream>>>(
        impl_->d_bgr_stage,
        static_cast<size_t>(src_w) * 3,  // tight pitch, no row padding
        src_w, src_h,
        impl_->d_buf,
        impl_->dst_w, impl_->dst_h,
        scale, pad_x, pad_y, scaled_w, scaled_h);

    cudaStreamSynchronize(impl_->stream);

    PreprocessOutput out;
    out.device_ptr = impl_->d_buf;
    out.bytes      = impl_->bytes;
    out.n = 1;
    out.c = 3;
    out.h = impl_->dst_h;
    out.w = impl_->dst_w;
    return out;
}

PreprocessOutput Preprocessor::run(
    const uint8_t* src_y,  size_t src_y_pitch,
    const uint8_t* src_uv, size_t src_uv_pitch,
    int src_w, int src_h) {
    // Letterbox math (host side — kernel just looks it up).
    const float sx = static_cast<float>(impl_->dst_w) / src_w;
    const float sy = static_cast<float>(impl_->dst_h) / src_h;
    const float scale = sx < sy ? sx : sy;
    const int scaled_w = static_cast<int>(src_w * scale + 0.5f);
    const int scaled_h = static_cast<int>(src_h * scale + 0.5f);
    const int pad_x = (impl_->dst_w - scaled_w) / 2;
    const int pad_y = (impl_->dst_h - scaled_h) / 2;

    dim3 block(16, 16);
    dim3 grid((impl_->dst_w + 15) / 16, (impl_->dst_h + 15) / 16);

    nv12_to_rgb_letterbox_kernel<<<grid, block, 0, impl_->stream>>>(
        src_y, src_y_pitch,
        src_uv, src_uv_pitch,
        src_w, src_h,
        impl_->d_buf,
        impl_->dst_w, impl_->dst_h,
        scale, pad_x, pad_y, scaled_w, scaled_h);

    cudaStreamSynchronize(impl_->stream);

    PreprocessOutput out;
    out.device_ptr = impl_->d_buf;
    out.bytes      = impl_->bytes;
    out.n = 1;
    out.c = 3;
    out.h = impl_->dst_h;
    out.w = impl_->dst_w;
    return out;
}

bool Preprocessor::cuda_available() {
    int n = 0;
    return cudaGetDeviceCount(&n) == cudaSuccess && n > 0;
}

}  // namespace vizor::decode
