// vizor_decode/async_decoder.hpp
//
// Wraps Decoder with a dedicated background decode thread + an SPSC
// ringbuffer so multiple cameras run concurrently without each
// Python caller blocking the others.
//
// Lifecycle:
//   AsyncDecoder ad(url, cfg);
//   ad.start();
//   auto frame = ad.next_frame(std::chrono::milliseconds(200));
//   ad.stop();        // joins decode thread
//   ~AsyncDecoder();  // safety net: also stops
//
// Semantics:
//   * Capacity 2 ringbuffer. Producer drops oldest on full so the
//     consumer never falls behind. "Live-only" — analytics need
//     fresh frames, not a backlog.
//   * next_frame() blocks up to `timeout` for a frame, then returns
//     nullopt. Returns nullopt immediately if stop() was called.
//   * stop() is idempotent + safe from any thread.

#pragma once

#include "decoder.hpp"
#include "frame.hpp"
#include "ringbuffer.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

namespace vizor::decode {

class AsyncDecoder {
public:
    AsyncDecoder(std::string url, DecoderConfig cfg);
    ~AsyncDecoder();

    AsyncDecoder(const AsyncDecoder&) = delete;
    AsyncDecoder& operator=(const AsyncDecoder&) = delete;

    // Spawn the decode thread. Throws on Decoder construction failure
    // (e.g. RTSP open). Subsequent runtime failures keep the thread
    // alive and surface via last_error().
    void start();

    // Signal decode thread to exit + join. Safe to call multiple
    // times. Called from destructor.
    void stop();

    // Wait up to `timeout` for the next frame. Returns nullopt on
    // timeout OR after stop(). Drops queued backlog before returning
    // so consumer always sees the freshest frame.
    std::optional<Frame> next_frame(
        std::chrono::milliseconds timeout = std::chrono::milliseconds(200));

    // Diagnostics.
    bool is_running() const noexcept { return running_.load(); }
    uint64_t frames_decoded() const noexcept { return frames_decoded_.load(); }
    uint64_t frames_dropped() const noexcept { return frames_dropped_.load(); }
    std::string last_error() const;

private:
    void decode_loop();

    std::string url_;
    DecoderConfig cfg_;

    std::unique_ptr<Decoder> decoder_;
    SpscRingBuffer<Frame, 2> buf_;

    std::thread th_;
    std::atomic<bool> running_{false};
    std::atomic<bool> started_{false};

    std::atomic<uint64_t> frames_decoded_{0};
    std::atomic<uint64_t> frames_dropped_{0};

    mutable std::mutex err_mu_;
    std::string last_err_;

    // Wakeup primitive for the consumer side.
    mutable std::mutex cv_mu_;
    std::condition_variable cv_;
};

}  // namespace vizor::decode
