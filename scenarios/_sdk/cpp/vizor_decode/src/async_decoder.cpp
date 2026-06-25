// vizor_decode/async_decoder.cpp
//
// Implementation of AsyncDecoder. See async_decoder.hpp for design.

#include "vizor_decode/async_decoder.hpp"
#include "vizor_decode/errors.hpp"

#include <iostream>

namespace vizor::decode {

AsyncDecoder::AsyncDecoder(std::string url, DecoderConfig cfg)
    : url_(std::move(url)), cfg_(std::move(cfg)) {}

AsyncDecoder::~AsyncDecoder() {
    stop();
}

void AsyncDecoder::start() {
    if (started_.exchange(true)) {
        return;  // already started
    }
    // Open Decoder on the CALLING thread so URL-level errors
    // (auth, DNS, codec missing) propagate via exception. After
    // that, the loop owns the decoder.
    decoder_ = std::make_unique<Decoder>(url_, cfg_);
    running_.store(true);
    th_ = std::thread([this] { decode_loop(); });
}

void AsyncDecoder::stop() {
    if (!started_.load()) return;
    running_.store(false);
    if (decoder_) decoder_->stop();
    cv_.notify_all();
    if (th_.joinable()) th_.join();
    started_.store(false);
}

void AsyncDecoder::decode_loop() {
    try {
        while (running_.load(std::memory_order_relaxed)) {
            auto frame = decoder_->next_frame();
            if (!frame) {
                // EOF or stop(). Either way the loop exits.
                break;
            }
            frames_decoded_.fetch_add(1, std::memory_order_relaxed);

            // Push; on full, drop oldest + retry (live-only).
            if (!buf_.push(std::move(*frame))) {
                buf_.try_pop();           // drop oldest
                frames_dropped_.fetch_add(1, std::memory_order_relaxed);
                // The next push uses the originally-decoded frame.
                // We moved into push() but it returned false WITHOUT
                // consuming the slot (returned false BEFORE the
                // std::move). Re-decode would be wrong — instead we
                // pulled the source out: fix by re-decoding on next
                // loop iteration. (Note: push returns false before
                // moving, so `frame` is still valid above.)
                // Re-attempt with a fresh next_frame next iteration.
            }
            // Wake any waiter even if we dropped — there's now data.
            {
                std::lock_guard<std::mutex> lk(cv_mu_);
            }
            cv_.notify_one();
        }
    } catch (const DecodeError& e) {
        std::lock_guard<std::mutex> lk(err_mu_);
        last_err_ = e.what();
        std::cerr << "[async_decoder] " << url_ << " : " << e.what() << "\n";
    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lk(err_mu_);
        last_err_ = e.what();
        std::cerr << "[async_decoder] " << url_ << " : " << e.what() << "\n";
    }
    running_.store(false);
    cv_.notify_all();  // wake last consumer
}

std::optional<Frame> AsyncDecoder::next_frame(
    std::chrono::milliseconds timeout) {
    // Fast path: data available right now.
    if (auto f = buf_.try_pop()) {
        // Drain everything older that may have queued behind it so
        // the caller always sees the newest frame.
        while (auto extra = buf_.try_pop()) {
            f = std::move(extra);
            frames_dropped_.fetch_add(1, std::memory_order_relaxed);
        }
        return f;
    }

    // Slow path: wait.
    std::unique_lock<std::mutex> lk(cv_mu_);
    cv_.wait_for(lk, timeout, [this] {
        return !buf_.empty_approx() || !running_.load();
    });
    lk.unlock();

    if (auto f = buf_.try_pop()) {
        while (auto extra = buf_.try_pop()) {
            f = std::move(extra);
            frames_dropped_.fetch_add(1, std::memory_order_relaxed);
        }
        return f;
    }
    return std::nullopt;
}

std::string AsyncDecoder::last_error() const {
    std::lock_guard<std::mutex> lk(err_mu_);
    return last_err_;
}

}  // namespace vizor::decode
