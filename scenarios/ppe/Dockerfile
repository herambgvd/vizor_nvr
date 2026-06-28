# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f ppe/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: ppe/Dockerfile.
#
# CUDA runtime base (parity with FRS + vizor-gpu) so the GStreamer live decoder can
# use NVDEC (nvh264dec) on the GPU instead of a CPU core per camera. Inference still
# runs on the shared Triton server; the CUDA runtime here is only for GPU video decode.
# ── builder: compile the native vizor_decode NVDEC module (parity with FRS) ───
# The worker decodes via this native module (NVDEC h264_cuvid through libav). Without
# it the worker falls back to PyAV software decode, which SIGSEGVs ~every 3 min under
# load. Build it here so VIZOR_DECODER=cpp works out of the box (no client-side copy).
# Decode-only (WITH_CUDA=OFF) — same proven config as FRS.
FROM nvidia/cuda:12.5.1-runtime-ubuntu22.04 AS decodebuilder
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
RUN cmake -S /build/vizor_decode -B /build/vizor_decode/build -G Ninja \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo \
        -DVIZOR_DECODE_WITH_CUDA=OFF \
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
# the GPU is passed through at run time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg wget curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-distutils \
        ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 \
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

# PyGObject into 3.11. Pin 3.50.0 — newer needs girepository-2.0; ubuntu 22.04 ships
# girepository-1.0. Build deps purged after.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && pip install --no-cache-dir "PyGObject==3.50.0" \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well). [app] = fastapi/pydantic,
# [triton] = tritonclient[http]. NO ultralytics/torch — inference is on Triton.
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton]"

COPY ppe/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# PyAV + libav runtime libs for the ffmpeg (software) decode path in the worker —
# parity with FRS. Without PyAV the ffmpeg decoder crashes with "No module named 'av'".
RUN apt-get update && apt-get install -y --no-install-recommends \
        libavcodec58 libavformat58 libavutil56 libswscale5 libavfilter7 libswresample3 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "av==12.3.0"

# Native cpp NVDEC decoder (compiled in the builder stage). The worker sets
# VIZOR_DECODER=cpp and imports this; without it, it falls back to PyAV (SIGSEGV-prone).
COPY --from=decodebuilder /vizor_decode.so /usr/local/lib/python3.11/dist-packages/vizor_decode.so

# Application — thin entrypoint + one package per concern.
COPY ppe/scenario.json ppe/app.py ppe/alembic.ini ./
COPY ppe/config ./config
COPY ppe/db ./db
COPY ppe/schemas ./schemas
COPY ppe/inference ./inference
COPY ppe/pipeline ./pipeline
COPY ppe/registration ./registration
COPY ppe/deps ./deps
COPY ppe/live ./live
COPY ppe/routers ./routers
# (no ppe/models — the SigLIP/DINOv2 verifier heads were removed; the model runs on Triton)

EXPOSE 8092
CMD ["python", "app.py"]
