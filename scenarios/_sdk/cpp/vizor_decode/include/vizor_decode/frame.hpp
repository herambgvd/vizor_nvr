// vizor_decode/frame.hpp
//
// Decoded frame descriptor returned by Decoder::next_frame().
//
// Day 1 design: caller gets pixel data as a host-side vector. Simple,
// proves the pipeline works end-to-end. Day 2 swaps in a zero-copy
// GPU surface variant for the numpy / Triton path.

#pragma once

#include <cstdint>
#include <vector>

namespace vizor::decode {

struct Frame {
    // Decoded pixels in BGR24 layout (3 bytes per pixel, packed).
    // Row stride == width * 3 — no padding. OpenCV-compatible.
    std::vector<uint8_t> bgr;

    int width = 0;
    int height = 0;

    // Presentation timestamp in microseconds since stream start.
    // -1 if FFmpeg couldn't recover one (rare).
    int64_t pts_us = -1;

    // True if this frame came off the GPU (NVDEC succeeded).
    // False = software fallback fired.
    bool hw_decoded = false;
};

}  // namespace vizor::decode
