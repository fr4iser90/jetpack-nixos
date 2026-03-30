# whisper.cpp — CPU-Build (portabel x86_64 / aarch64). Modell: ./models siehe compose.yml
FROM debian:bookworm-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git . \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j"$(nproc)"

# Binary + benötigte .so (libwhisper, ggml) für das Laufzeit-Image
RUN set -eux; \
    mkdir -p /artifacts/bin /artifacts/lib; \
    if [ -f build/bin/whisper-cli ]; then cp build/bin/whisper-cli /artifacts/bin/whisper-cpp; \
    elif [ -f build/bin/main ]; then cp build/bin/main /artifacts/bin/whisper-cpp; \
    else ls -la build/bin && exit 1; fi; \
    find build -name 'libwhisper.so*' -exec cp -a {} /artifacts/lib/ \;; \
    find build -name 'libggml*.so*' -exec cp -a {} /artifacts/lib/ \;; \
    find build -name 'libggml-*.so*' -exec cp -a {} /artifacts/lib/ \;; \
    ls -la /artifacts/lib

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /artifacts/bin/whisper-cpp /usr/local/bin/whisper-cpp
COPY --from=builder /artifacts/lib/ /usr/local/lib/
RUN ldconfig

WORKDIR /data

ENTRYPOINT ["/usr/local/bin/whisper-cpp"]
