# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f frs/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: frs/Dockerfile.
#
# CUDA runtime base (parity with vizor-gpu) so the GStreamer live decoder can use
# NVDEC (nvh264dec) on the GPU instead of burning a CPU core per camera on software
# decode. Inference still runs on the shared Triton server (this stays a thin client);
# the CUDA runtime here is only for the GPU video decode path.
# ── builder: compile the native vizor_decode NVDEC + CUDA-preprocess module ───
# The worker decodes via this native module (NVDEC h264_cuvid through libav) AND
# runs the NV12->letterbox->float NCHW preprocess on the GPU (preprocess.cu), so the
# per-frame colour-convert + resize move OFF the CPU. That needs nvcc, so the builder
# uses the CUDA *devel* base (runtime has no compiler). The final stage stays on the
# slim runtime base — only the compiled .so is copied across.
FROM nvidia/cuda:12.5.1-devel-ubuntu22.04 AS decodebuilder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg curl git make \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev \
        cmake ninja-build pkg-config g++ \
        libavcodec-dev libavformat-dev libavutil-dev libswscale-dev \
        libavfilter-dev libswresample-dev \
        libspdlog-dev libfmt-dev \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11 - \
    && pip install --no-cache-dir "pybind11>=2.11"
# nv-codec-headers — cuvid header defs libavcodec's h264_cuvid path links against.
RUN git clone --depth 1 https://github.com/FFmpeg/nv-codec-headers.git /tmp/nvh \
    && make -C /tmp/nvh install && rm -rf /tmp/nvh
COPY _sdk/cpp/vizor_decode /build/vizor_decode
# Point CMake's FindPython3 at the deadsnakes 3.11 explicitly — otherwise it can't
# resolve the Development component on this base and configure fails.
RUN cmake -S /build/vizor_decode -B /build/vizor_decode/build -G Ninja \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo \
        -DVIZOR_DECODE_WITH_CUDA=ON \
        -DVIZOR_DECODE_BUILD_TESTS=OFF \
        -DPython3_EXECUTABLE=/usr/bin/python3.11 \
        -DPython3_FIND_STRATEGY=LOCATION \
        -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHS:-89}" \
    && cmake --build /build/vizor_decode/build -j \
    && find /build/vizor_decode/build -name 'vizor_decode*.so' -exec cp {} /vizor_decode.so \;


FROM nvidia/cuda:12.5.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Python 3.11 + ffmpeg/libgl (cv2) + the full GStreamer stack. plugins-bad ships the
# nvcodec elements (nvh264dec) which light up because the CUDA runtime is present and
# the GPU is passed through at run time. python3-gst-1.0 + gir typelibs give the Python
# bindings; no PyGObject pip build needed (system python3-gi matches this 3.10 base...
# we install 3.11 + its own gi below).
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg wget curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-distutils \
        ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 espeak-ng \
        libgirepository-1.0-1 libcairo2 \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav gstreamer1.0-nice \
        libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
        gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11 -

# PyGObject into 3.11. Pin 3.50.0 — newer needs girepository-2.0 (gi >=1.80); ubuntu
# 22.04 ships 1.72 (girepository-1.0). Build deps purged after.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && pip install --no-cache-dir "PyGObject==3.50.0" \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# YuNet landmark model (232 KB, CPU ONNX) — robust 5-point fallback when SCRFD's
# landmarks are degenerate (collapsed eyes on steep top-down / profile faces), which
# would otherwise warp to a garbage ArcFace crop and break recognition. Same model
# vizor-gpu ships. Override path with FRS_YUNET_MODEL.
RUN mkdir -p /models \
    && curl -fsSL -o /models/yunet.onnx \
       https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    || echo "WARN: YuNet download failed — alignment falls back to center-crop"

# Shared Vizor Scenario SDK (own layer — caches well).
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton,vectors]"

COPY frs/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Native NVDEC decode module (built above) + its libav runtime libs, and PyAV for
# the ffmpeg software fallback. The .so lands on PYTHONPATH at /usr/local/lib so
# `import vizor_decode` works in the worker.
COPY --from=decodebuilder /vizor_decode.so /usr/local/lib/python3.11/dist-packages/vizor_decode.so
RUN apt-get update && apt-get install -y --no-install-recommends \
        libavcodec58 libavformat58 libavutil56 libswscale5 libavfilter7 libswresample3 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "av==12.3.0"

# Application — thin entrypoint + one package per concern.
COPY frs/scenario.json frs/app.py frs/alembic.ini ./
COPY frs/config ./config
COPY frs/db ./db
COPY frs/schemas ./schemas
COPY frs/qdrant ./qdrant
COPY frs/recognition ./recognition
COPY frs/registration ./registration
COPY frs/deps ./deps
COPY frs/live ./live
COPY frs/routers ./routers

EXPOSE 8093
CMD ["python", "app.py"]
