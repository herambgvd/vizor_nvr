// cli_decode — standalone decode benchmark for the vizor_decode lib.
//
// Usage:
//   cli_decode <rtsp_url> [--frames N] [--no-hwaccel] [--save out.bgr]
//
// Prints decode stats (frames/sec, packets, hw vs cpu) every 30 frames.

#include "vizor_decode/decoder.hpp"
#include "vizor_decode/errors.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>

using namespace std::chrono;

namespace vd = vizor::decode;

static void print_usage(const char* prog) {
    std::cerr << "Usage: " << prog
              << " <rtsp_url> [--frames N] [--no-hwaccel] [--save first.bgr]\n";
}

int main(int argc, char** argv) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    std::string url = argv[1];
    int target_frames = 100;
    bool hwaccel = true;
    std::string save_path;

    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--frames" && i + 1 < argc) {
            target_frames = std::atoi(argv[++i]);
        } else if (a == "--no-hwaccel") {
            hwaccel = false;
        } else if (a == "--save" && i + 1 < argc) {
            save_path = argv[++i];
        } else {
            print_usage(argv[0]);
            return 1;
        }
    }

    vd::DecoderConfig cfg;
    cfg.prefer_hwaccel = hwaccel;

    try {
        std::cout << "[cli_decode] opening " << url
                  << " (hwaccel=" << (hwaccel ? "on" : "off") << ")\n";

        vd::Decoder dec(url, cfg);

        std::cout << "[cli_decode] decoder ready: "
                  << (dec.is_hw_decoder() ? "NVDEC (h264_cuvid)"
                                          : "software (libavcodec)")
                  << "\n";

        auto t0 = steady_clock::now();
        int got = 0;
        bool saved = save_path.empty();

        while (got < target_frames) {
            auto frame = dec.next_frame();
            if (!frame) {
                std::cout << "[cli_decode] stream ended at frame " << got << "\n";
                break;
            }
            ++got;

            // Dump the first frame to disk as raw BGR for sanity check.
            // Convert offline:
            //   convert -size WxH -depth 8 bgr:first.bgr first.png
            if (!saved) {
                std::ofstream out(save_path, std::ios::binary);
                out.write(reinterpret_cast<const char*>(frame->bgr.data()),
                          static_cast<std::streamsize>(frame->bgr.size()));
                std::cout << "[cli_decode] saved first frame "
                          << frame->width << "x" << frame->height
                          << " -> " << save_path << "\n";
                saved = true;
            }

            if (got % 30 == 0) {
                auto dt = duration_cast<milliseconds>(
                    steady_clock::now() - t0).count();
                double fps = dt > 0 ? (got * 1000.0 / dt) : 0.0;
                std::cout << "[cli_decode] frames=" << got
                          << " packets=" << dec.packets_read()
                          << " elapsed_ms=" << dt
                          << " fps=" << fps
                          << " hw=" << dec.is_hw_decoder() << "\n";
            }
        }

        auto dt = duration_cast<milliseconds>(steady_clock::now() - t0).count();
        double fps = dt > 0 ? (got * 1000.0 / dt) : 0.0;
        std::cout << "[cli_decode] DONE frames=" << got
                  << " elapsed_ms=" << dt
                  << " fps=" << fps
                  << " hw=" << dec.is_hw_decoder() << "\n";

        return 0;
    } catch (const vd::DecodeError& e) {
        std::cerr << "[cli_decode] DecodeError: " << e.what() << "\n";
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "[cli_decode] error: " << e.what() << "\n";
        return 3;
    }
}
