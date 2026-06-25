# vizor_decode — RTSP + NVDEC C++ decode pipeline.
#
# Build:
#   cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build build -j
#
# Targets:
#   vizor_decode       — static lib (Day 1) + shared lib later
#   cli_decode         — standalone test binary

cmake_minimum_required(VERSION 3.20)

# CUDA optional — preprocess kernels build only when nvcc is found.
# Workers without CUDA SDK can still ship the CPU-only decode lib.
option(VIZOR_DECODE_WITH_CUDA "Build CUDA preprocess kernels" ON)
if(VIZOR_DECODE_WITH_CUDA)
    project(vizor_decode CXX CUDA)
else()
    project(vizor_decode CXX)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# nvcc 12.5 supports up to --std=c++17 on the device side; using
# CUDA20 confuses CMake because it propagates CXX_STANDARD to CUDA
# unless we override. Pin the CUDA dialect to 17 — our kernels
# use no >C++17 features anyway.
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)

# Default to RelWithDebInfo if not specified — fast + still has symbols
# for valgrind / perf.
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

# Treat warnings as compile-time noise (not errors) for now — easy to
# flip on once code stabilises.
add_compile_options(-Wall -Wextra -Wpedantic)

# ------------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------------
find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)

pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET
    libavcodec libavformat libavutil libswscale libavfilter
)

# nv-codec-headers (cuvid header definitions used by libavcodec build,
# not directly by us yet — kept here so the env check fails fast).
pkg_check_modules(FFNVCODEC ffnvcodec)

# spdlog for structured logging (Day 1 we still use std::cout for the
# CLI, but the lib will adopt spdlog on Day 2).
find_package(spdlog QUIET)

# ------------------------------------------------------------------
# vizor_decode static library
# ------------------------------------------------------------------
set(VIZOR_DECODE_SOURCES
    src/decoder.cpp
    src/async_decoder.cpp
)
if(VIZOR_DECODE_WITH_CUDA)
    list(APPEND VIZOR_DECODE_SOURCES src/preprocess.cu)
    # Default arch covers Ampere (RTX 30xx), Ada (RTX 40xx, A2000
    # Ada — what SMCC runs), Hopper (PRO datacenter), Blackwell
    # (RTX 50xx, RTX PRO 5000 — what Danzo runs). Override at
    # configure time with -DCMAKE_CUDA_ARCHITECTURES="89".
    # 86 = Ampere (RTX 30xx), 89 = Ada (RTX 40xx, A2000 Ada), 90 =
    # Hopper. Blackwell (sm_120) needs nvcc >= 12.8 — set
    # CMAKE_CUDA_ARCHITECTURES manually at configure time on those
    # boxes (e.g. -DCMAKE_CUDA_ARCHITECTURES="86;89;90;120").
    set(CMAKE_CUDA_ARCHITECTURES "86;89;90"
        CACHE STRING "CUDA arch list" FORCE)
endif()

add_library(vizor_decode STATIC ${VIZOR_DECODE_SOURCES})

if(VIZOR_DECODE_WITH_CUDA)
    target_compile_definitions(vizor_decode PUBLIC VIZOR_DECODE_HAS_CUDA=1)
endif()

target_include_directories(vizor_decode
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(vizor_decode
    PUBLIC  PkgConfig::FFMPEG Threads::Threads
)

if(spdlog_FOUND)
    target_link_libraries(vizor_decode PRIVATE spdlog::spdlog)
endif()

# ------------------------------------------------------------------
# cli_decode test binary
# ------------------------------------------------------------------
add_executable(cli_decode examples/cli_decode.cpp)
target_link_libraries(cli_decode PRIVATE vizor_decode)

# ------------------------------------------------------------------
# pybind11 Python module (vizor_decode.so importable from Python)
# ------------------------------------------------------------------
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 CONFIG QUIET)

if(NOT pybind11_FOUND)
    # System Debian pybind11 ships the CMake config under a different
    # path on Ubuntu — fall back to pkg-config / direct headers.
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c
            "import pybind11; print(pybind11.get_cmake_dir())"
        OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE)
    list(APPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
    find_package(pybind11 CONFIG REQUIRED)
endif()

pybind11_add_module(vizor_decode_py MODULE
    bindings/pybind11_module.cpp
)
# Rename the produced .so so Python imports as `vizor_decode`.
set_target_properties(vizor_decode_py PROPERTIES
    OUTPUT_NAME vizor_decode
    PREFIX ""
)
target_link_libraries(vizor_decode_py PRIVATE vizor_decode)

# ------------------------------------------------------------------
# Tests (gtest) — optional. Skipped in production builds (Docker) so
# the builder stage doesn't need libgtest-dev.
# ------------------------------------------------------------------
option(VIZOR_DECODE_BUILD_TESTS "Build gtest suite" OFF)
if(VIZOR_DECODE_BUILD_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
    add_executable(vizor_decode_tests tests/test_ringbuffer.cpp)
    target_link_libraries(vizor_decode_tests PRIVATE
        vizor_decode GTest::gtest GTest::gtest_main Threads::Threads
    )
    include(GoogleTest)
    gtest_discover_tests(vizor_decode_tests)

    if(VIZOR_DECODE_WITH_CUDA)
        add_executable(test_preprocess tests/test_preprocess.cu)
        target_link_libraries(test_preprocess PRIVATE vizor_decode)
        add_test(NAME preprocess_smoke COMMAND test_preprocess)
    endif()
endif()

# ------------------------------------------------------------------
# Install rules (placeholder for Day 3+)
# ------------------------------------------------------------------
install(TARGETS vizor_decode cli_decode
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)
install(DIRECTORY include/ DESTINATION include)

message(STATUS "vizor_decode configured")
message(STATUS "  CXX           : ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "  FFmpeg avcodec: ${FFMPEG_libavcodec_VERSION}")
message(STATUS "  FFmpeg avformat: ${FFMPEG_libavformat_VERSION}")
message(STATUS "  ffnvcodec     : ${FFNVCODEC_VERSION}")
