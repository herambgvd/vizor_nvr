// vizor_decode/ringbuffer.hpp
//
// Single-producer / single-consumer lock-free ring buffer for Frame
// objects. Used to decouple the decode thread from the Python caller.
//
// Capacity 2 by default — gives the decoder one frame of headroom
// while it produces the next, but never lets the consumer fall more
// than ~1 frame behind. On full, push() returns false and the caller
// can choose to drop_front() then re-push (live-only semantics) or
// just discard the new frame.
//
// Why not std::queue + mutex?
//   * Mutex contention sneaks in even at low rates on multi-cam
//     workloads (8+ cams × 30 fps = ~240 push/pop ops per second
//     hitting the same kernel futex on some platforms).
//   * Lock-free SPSC is the simplest correct primitive for this
//     pattern — two atomic indices and a fixed-size array.
//
// Memory ordering:
//   * Producer publishes write_ with release; consumer loads with
//     acquire. Synchronises payload visibility.
//   * Consumer publishes read_ with release; producer loads with
//     acquire (for full() check).

#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <optional>
#include <utility>

namespace vizor::decode {

template <typename T, std::size_t Capacity>
class SpscRingBuffer {
    static_assert(Capacity >= 2, "SPSC ring needs at least 2 slots");

public:
    SpscRingBuffer() = default;
    SpscRingBuffer(const SpscRingBuffer&) = delete;
    SpscRingBuffer& operator=(const SpscRingBuffer&) = delete;

    // Producer-side: try to push. Returns false if full.
    // Overloaded so callers can pass either an lvalue (copied) or an
    // rvalue (moved). The Frame type holds a vector<uint8_t> that
    // moves cheaply — both paths exist so the SPSC primitive stays
    // generally useful for trivially-copyable Ts too.
    bool push(const T& t) {
        const auto w = write_.load(std::memory_order_relaxed);
        const auto next = (w + 1) % Capacity;
        if (next == read_.load(std::memory_order_acquire)) {
            return false;
        }
        slots_[w] = t;
        write_.store(next, std::memory_order_release);
        return true;
    }
    bool push(T&& t) {
        const auto w = write_.load(std::memory_order_relaxed);
        const auto next = (w + 1) % Capacity;
        if (next == read_.load(std::memory_order_acquire)) {
            return false;
        }
        slots_[w] = std::move(t);
        write_.store(next, std::memory_order_release);
        return true;
    }

    // Consumer-side: try to pop. Returns nullopt if empty.
    std::optional<T> try_pop() {
        const auto r = read_.load(std::memory_order_relaxed);
        if (r == write_.load(std::memory_order_acquire)) {
            return std::nullopt;  // empty
        }
        T out = std::move(slots_[r]);
        read_.store((r + 1) % Capacity, std::memory_order_release);
        return out;
    }

    // Consumer-side: drop everything currently buffered.
    // Producer keeps running unaffected.
    void drain() {
        read_.store(write_.load(std::memory_order_acquire),
                    std::memory_order_release);
    }

    // Approximate count — racy but useful for diagnostics.
    std::size_t size_approx() const noexcept {
        const auto w = write_.load(std::memory_order_acquire);
        const auto r = read_.load(std::memory_order_acquire);
        return (w + Capacity - r) % Capacity;
    }

    bool empty_approx() const noexcept {
        return write_.load(std::memory_order_acquire) ==
               read_.load(std::memory_order_acquire);
    }

private:
    // 64-byte alignment defeats false-sharing between the producer
    // and consumer cache lines (a typical x86_64 cache line is 64B;
    // putting write_ and read_ on the same line caused 3-4x slower
    // pushes under contention in early benchmarks).
    alignas(64) std::atomic<std::size_t> write_{0};
    alignas(64) std::atomic<std::size_t> read_{0};
    alignas(64) std::array<T, Capacity> slots_{};
};

}  // namespace vizor::decode
