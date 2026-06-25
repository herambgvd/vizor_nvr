# vizor_decode

> **Status 2026-05-27: DEPRECATED safety net.**
> GStreamer is the canonical decoder + recorder for Vizor (Phase D1).
> This native C++/CUDA path stays in the repo only as a rollback
> escape hatch during the cutover. Slated for deletion after the
> Phase D1 production pipeline ships with watchdog + metrics + atomic
> segment register validated on single-tenant N-camera load.
> See `../../docs/DECODER.md` for the deletion timeline.
> Do NOT add features here; do NOT pick `VIZOR_DECODER=cpp` for new
> deployments.

Native RTSP → NVDEC → preprocess pipeline that backs the Vizor edge
workers. Built so the Python AI pipeline can stay on familiar
asyncio control flow while the hot path (demux, decode, colour
convert, resize, normalise) runs in C++ / CUDA.

## Why

The PyAV path:
- Holds the GIL during decode (single-thread bottleneck per worker)
- Cannot select `h264_cuvid` cleanly on PyAV 17+ (read-only
  `codec_context`)
- Allocates fresh numpy buffers per frame (Python heap churn)
- Copies frames host→device twice (decode on CPU → resize on CPU →
  upload to Triton)

Eight 1080p cameras saturate around 16 CPU cores with the PyAV path
on a 25 fps stream. The native build targets <0.5 cores per camera,
preprocess included.

## Components

| File                                      | What it does                                    |
| ----------------------------------------- | ----------------------------------------------- |
| `src/decoder.cpp`                         | FFmpeg open + h264_cuvid decode loop            |
| `src/async_decoder.cpp`                   | Background decode thread + SPSC ringbuffer     |
| `src/preprocess.cu`                       | CUDA NV12 → letterbox → CHW float32 RGB kernel |
| `include/vizor_decode/ringbuffer.hpp`     | Lock-free SPSC ring                             |
| `bindings/pybind11_module.cpp`            | Python module entry                             |
| `examples/cli_decode.cpp`                 | Standalone benchmark binary                     |
| `examples/py_demo.py`                     | Python smoke test                               |

## Build

System deps (Ubuntu 24.04):

```bash
sudo apt install -y build-essential cmake ninja-build pkg-config \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev \
    libavfilter-dev libswresample-dev \
    libgtest-dev libspdlog-dev libfmt-dev \
    nvidia-cuda-toolkit \
    python3-dev python3-pybind11
sudo make -C /usr/local/src/nv-codec-headers install   # or git clone + make
```

Configure + build:

```bash
cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DVIZOR_DECODE_BUILD_TESTS=ON      # optional
cmake --build build -j
```

On Blackwell GPUs (RTX 50xx, RTX PRO 5000) override the arch list:

```bash
cmake -S . -B build -G Ninja \
    -DCMAKE_CUDA_ARCHITECTURES="86;89;90;120"
```

## Use from Python

```python
import vizor_decode as vd

# Synchronous, one frame at a time:
dec = vd.Decoder("rtsp://cam/stream", hwaccel=True)
arr = dec.next_frame()        # numpy ndarray HxWx3 uint8 BGR, None on EOF

# Threaded, multi-camera, ringbuffered:
ad = vd.AsyncDecoder("rtsp://cam/stream", hwaccel=True)
ad.start()
while True:
    arr = ad.next_frame(timeout_ms=500)   # newest frame, drops backlog
    if arr is None:                       # timeout or stopped
        break
ad.stop()
```

## Hardware requirements

* NVIDIA driver new enough to expose `libnvcuvid.so.1` (>= 470).
* NVDEC silicon present (`nvidia-smi` shows a `dec` column).
* VRAM headroom for the decoder context (~150 MB / 1080p stream).
  **On 6 GB consumer GPUs sharing the device with Triton + Ollama,
  NVDEC alloc can fail with `CUDA_ERROR_OUT_OF_MEMORY`. The decoder
  falls back to software decode automatically.** Production
  deployments target ≥ 16 GB VRAM (RTX 4060 Ti, A2000 Ada,
  RTX PRO 5000) to avoid the fallback path.

## Worker integration

`ai_workers/_base/cpp_frame_source.py` wraps `AsyncDecoder` behind
the `FrameSource` async iterator the rest of the codebase already
uses. Switch backends via env:

```yaml
environment:
  VIZOR_DECODER: cpp        # native (default)
  # VIZOR_DECODER: ffmpeg   # PyAV bridge (fallback)
  # VIZOR_DECODER: pyav     # pure Python
```

The Docker images (`ai_workers/ppe/Dockerfile`,
`ai_workers/frs/Dockerfile`) build the `.so` in a multi-stage
builder and copy it into the runtime stage. No external pip
package — the module ships inside the worker image.

## CUDA preprocess (status)

The `preprocess.cu` kernel exists and tests pass on host builds with
the CUDA toolkit installed. Inside the worker Docker image the
module is currently built with `-DVIZOR_DECODE_WITH_CUDA=OFF`
because the python:3.11-slim base lacks `nvcc` and we haven't yet
swapped the builder to `nvidia/cuda:12.5.0-devel-ubuntu22.04`.

Pipeline impact today: workers get the NVDEC decode CPU win but
still pull frames back to host for resize/normalise. End-to-end
zero-copy (decode → preprocess → Triton via CUDA shared memory)
ships in the next iteration once the builder switches to the
NVIDIA CUDA base image AND the Triton client gains the
CUDA-shared-memory call site.
