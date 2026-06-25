// vizor_decode/errors.hpp
//
// Single exception type for the entire decoder. Wraps FFmpeg's int
// error codes (negative AVERROR_*) with a human-readable message so
// callers can catch one type and log it directly.
//
// Why a custom exception (not std::runtime_error):
//   1. Carry the raw AVERROR int — operators grep logs for codes.
//   2. Distinguish decode failures from std exceptions at catch site.
//   3. Free spot to attach stream URL / camera id later without
//      changing the public ABI of std::runtime_error.

#pragma once

#include <stdexcept>
#include <string>

extern "C" {
#include <libavutil/error.h>
}

namespace vizor::decode {

class DecodeError : public std::runtime_error {
public:
    // ctx: short string describing what was being attempted
    //      ("open_input", "find_decoder", etc.)
    // ff_err: raw AVERROR code returned by FFmpeg (negative).
    DecodeError(const std::string& ctx, int ff_err)
        : std::runtime_error(format(ctx, ff_err)), ff_err_(ff_err) {}

    // Variant without an FFmpeg error code (e.g. NVDEC not found).
    explicit DecodeError(const std::string& msg)
        : std::runtime_error(msg), ff_err_(0) {}

    int ff_err() const noexcept { return ff_err_; }

private:
    int ff_err_;

    static std::string format(const std::string& ctx, int err) {
        char buf[256];
        av_strerror(err, buf, sizeof(buf));
        return ctx + ": " + buf + " (code=" + std::to_string(err) + ")";
    }
};

}  // namespace vizor::decode
