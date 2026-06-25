// vizor_decode Python module.
//
// Exposes a Decoder class to Python:
//
//   import vizor_decode as vd
//   dec = vd.Decoder("rtsp://...", hwaccel=True)
//   while frame := dec.next_frame():
//       arr = frame  # numpy ndarray HxWx3 uint8 BGR
//
// Design notes:
//   * next_frame() returns Optional[np.ndarray]; None on EOF.
//   * The ndarray owns its buffer via a Python capsule that holds
//     the moved-from std::vector<uint8_t>. Zero copy from C++ — the
//     vector's data pointer is reused as the numpy data ptr.
//   * GIL is released during the blocking decode call so Python
//     threads / asyncio can run concurrently.

#include "vizor_decode/async_decoder.hpp"
#include "vizor_decode/decoder.hpp"
#include "vizor_decode/errors.hpp"

#ifdef VIZOR_DECODE_HAS_CUDA
#  include "vizor_decode/preprocess.hpp"
#endif

#include <pybind11/chrono.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <chrono>
#include <memory>
#include <optional>

namespace py = pybind11;
namespace vd = vizor::decode;

// Build a numpy ndarray that takes ownership of an existing
// std::vector<uint8_t> without copying its buffer. The vector is
// moved onto the heap and freed when Python drops the ndarray's
// last reference.
static py::array_t<uint8_t> ndarray_from_vector(
    std::vector<uint8_t>&& vec, int h, int w) {
    auto* heap_vec = new std::vector<uint8_t>(std::move(vec));
    uint8_t* data = heap_vec->data();
    // Capsule deleter — runs when numpy array dies.
    py::capsule owner(heap_vec, [](void* p) {
        delete static_cast<std::vector<uint8_t>*>(p);
    });
    return py::array_t<uint8_t>(
        /*shape*/   {h, w, 3},
        /*strides*/ {w * 3, 3, 1},
        /*data*/    data,
        /*base*/    owner);
}

PYBIND11_MODULE(vizor_decode, m) {
    m.doc() = "vizor_decode — RTSP + NVDEC H.264 decoder (C++ core)";

    py::register_exception<vd::DecodeError>(m, "DecodeError");

    py::class_<vd::DecoderConfig>(m, "DecoderConfig")
        .def(py::init<>())
        .def_readwrite("rtsp_transport",   &vd::DecoderConfig::rtsp_transport)
        .def_readwrite("socket_timeout_us",&vd::DecoderConfig::socket_timeout_us)
        .def_readwrite("prefer_hwaccel",   &vd::DecoderConfig::prefer_hwaccel)
        .def_readwrite("gpu_index",        &vd::DecoderConfig::gpu_index);

    py::class_<vd::Decoder>(m, "Decoder")
        .def(py::init([](const std::string& url, bool hwaccel,
                          const std::string& rtsp_transport,
                          int gpu_index) {
                 vd::DecoderConfig cfg;
                 cfg.prefer_hwaccel = hwaccel;
                 cfg.rtsp_transport = rtsp_transport;
                 cfg.gpu_index = gpu_index;
                 return std::make_unique<vd::Decoder>(url, cfg);
             }),
             py::arg("url"),
             py::arg("hwaccel") = true,
             py::arg("rtsp_transport") = "tcp",
             py::arg("gpu_index") = 0,
             "Open an RTSP URL and start decoding.")

        .def("next_frame",
             [](vd::Decoder& self) -> py::object {
                 std::optional<vd::Frame> frame;
                 {
                     // Release the GIL so other Python threads run
                     // while we block on socket / decode.
                     py::gil_scoped_release rel;
                     frame = self.next_frame();
                 }
                 if (!frame) return py::none();
                 return ndarray_from_vector(
                     std::move(frame->bgr),
                     frame->height, frame->width);
             },
             "Block until next BGR frame, or return None on EOF.")

        .def("stop", &vd::Decoder::stop,
             "Signal next_frame() to wake up and return None.")

        .def_property_readonly("is_hw_decoder", &vd::Decoder::is_hw_decoder)
        .def_property_readonly("frames_decoded", &vd::Decoder::frames_decoded)
        .def_property_readonly("packets_read",  &vd::Decoder::packets_read);

    py::class_<vd::AsyncDecoder>(m, "AsyncDecoder")
        .def(py::init([](const std::string& url, bool hwaccel,
                          const std::string& rtsp_transport,
                          int gpu_index) {
                 vd::DecoderConfig cfg;
                 cfg.prefer_hwaccel = hwaccel;
                 cfg.rtsp_transport = rtsp_transport;
                 cfg.gpu_index = gpu_index;
                 return std::make_unique<vd::AsyncDecoder>(url, cfg);
             }),
             py::arg("url"),
             py::arg("hwaccel") = true,
             py::arg("rtsp_transport") = "tcp",
             py::arg("gpu_index") = 0,
             "Threaded RTSP decoder. Call start() then next_frame().")

        .def("start",
             [](vd::AsyncDecoder& self) {
                 py::gil_scoped_release rel;
                 self.start();
             },
             "Open the stream and spawn the background decode thread.")

        .def("stop",
             [](vd::AsyncDecoder& self) {
                 py::gil_scoped_release rel;
                 self.stop();
             },
             "Signal decode thread to exit and join it. Idempotent.")

        .def("next_frame",
             [](vd::AsyncDecoder& self, int timeout_ms) -> py::object {
                 std::optional<vd::Frame> frame;
                 {
                     py::gil_scoped_release rel;
                     frame = self.next_frame(
                         std::chrono::milliseconds(timeout_ms));
                 }
                 if (!frame) return py::none();
                 return ndarray_from_vector(
                     std::move(frame->bgr),
                     frame->height, frame->width);
             },
             py::arg("timeout_ms") = 200,
             "Block up to timeout_ms for next BGR frame. None on timeout.")

        .def_property_readonly("is_running",      &vd::AsyncDecoder::is_running)
        .def_property_readonly("frames_decoded",  &vd::AsyncDecoder::frames_decoded)
        .def_property_readonly("frames_dropped",  &vd::AsyncDecoder::frames_dropped)
        .def_property_readonly("last_error",      &vd::AsyncDecoder::last_error);

#ifdef VIZOR_DECODE_HAS_CUDA
    // Preprocessor binding. Mostly low-level — the worker wraps it
    // through a Python helper that takes a numpy frame, copies into
    // GPU, runs the kernel, and returns either a numpy ndarray
    // (for callers still on the legacy CPU path) or the raw device
    // pointer (for the Triton-CUDA-shared-memory path).
    py::class_<vd::PreprocessOutput>(m, "PreprocessOutput")
        .def_property_readonly(
            "device_ptr_int",
            [](const vd::PreprocessOutput& o) {
                return reinterpret_cast<uintptr_t>(o.device_ptr);
            },
            "Raw CUDA device pointer as an int. Pass to "
            "tritonclient.utils.cuda_shared_memory.")
        .def_readonly("bytes", &vd::PreprocessOutput::bytes)
        .def_readonly("n", &vd::PreprocessOutput::n)
        .def_readonly("c", &vd::PreprocessOutput::c)
        .def_readonly("h", &vd::PreprocessOutput::h)
        .def_readonly("w", &vd::PreprocessOutput::w);

    py::class_<vd::Preprocessor>(m, "Preprocessor")
        .def(py::init<int, int>(),
             py::arg("dst_w"), py::arg("dst_h"),
             "Allocate a GPU resize+normalise context for a fixed "
             "destination size (e.g. 640x640 for yolov12m).")
        .def("run",
             [](vd::Preprocessor& self,
                uintptr_t src_y_ptr, size_t src_y_pitch,
                uintptr_t src_uv_ptr, size_t src_uv_pitch,
                int src_w, int src_h) {
                 py::gil_scoped_release rel;
                 return self.run(
                     reinterpret_cast<const uint8_t*>(src_y_ptr), src_y_pitch,
                     reinterpret_cast<const uint8_t*>(src_uv_ptr), src_uv_pitch,
                     src_w, src_h);
             },
             "Run NV12 -> letterboxed CHW float RGB. Pointer args "
             "must already live on the GPU (cudaMalloc'd).")
        .def("run_bgr",
             [](vd::Preprocessor& self,
                py::array_t<uint8_t, py::array::c_style | py::array::forcecast> bgr) {
                 if (bgr.ndim() != 3 || bgr.shape(2) != 3)
                     throw std::runtime_error(
                         "run_bgr expects HxWx3 uint8 ndarray");
                 const int h = static_cast<int>(bgr.shape(0));
                 const int w = static_cast<int>(bgr.shape(1));
                 const uint8_t* data = bgr.data();
                 py::gil_scoped_release rel;
                 return self.run_bgr(data, w, h);
             },
             "Upload a host BGR ndarray to GPU and run the "
             "letterbox+normalise kernel. Returns PreprocessOutput "
             "with device_ptr_int pointing at the GPU tensor.")
        .def_static("cuda_available", &vd::Preprocessor::cuda_available);
#endif
}
