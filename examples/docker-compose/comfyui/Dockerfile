# ComfyUI wird hier im Image geklont — kein lokales `git clone` nötig (siehe compose.yaml).
#

#
# Ubuntu 22.04 ≈ Python 3.10. Jetson-PyTorch 2.5 braucht u. a. cuDNN9, CUPTI (*-devel*), cuSPARSELt (pip).
FROM nvidia/cuda:12.3.2-cudnn9-devel-ubuntu22.04

ARG COMFYUI_REPO=https://github.com/comfyanonymous/ComfyUI.git
# Feste ComfyUI-Version (Tag). Neuere Patches: z. B. v0.18.3 — siehe GitHub Releases.
ARG COMFYUI_REF=v0.18.2

ENV DEBIAN_FRONTEND=noninteractive

# ComfyUI-Manager ruft beim Start pip auf → sonst oft numpy 2.x → Jetson-Torch / torchvision brechen.
RUN printf '%s\n' 'numpy>=1.25.0,<2' > /constraints.txt
ENV PIP_CONSTRAINT=/constraints.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3-pip \
    python3-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libopenblas-dev \
    build-essential \
    ninja-build \
    cmake \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN set -eux; \
    if [ -n "${COMFYUI_REF}" ]; then \
      git clone --depth 1 --branch "${COMFYUI_REF}" "${COMFYUI_REPO}" /app; \
    else \
      git clone --depth 1 "${COMFYUI_REPO}" /app; \
    fi

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

RUN rm -rf /app/custom_nodes/ComfyUI-Manager /app/custom_nodes/ComfyUI-GGUF \
    && git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Manager.git /app/custom_nodes/ComfyUI-Manager \
    && pip install --no-cache-dir -r /app/custom_nodes/ComfyUI-Manager/requirements.txt \
    && git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git /app/custom_nodes/ComfyUI-GGUF \
    && pip install --no-cache-dir --upgrade gguf

# PyPI torch ist für Desktop-CUDA gebaut → auf Jetson: "driver too old (found 12060)" trotz CDI.
# Offizielles L4T-Wheel (JetPack 6.1 redist). Nur auf aarch64 bauen. Bei JP 6.0: NV_TORCH_WHEEL auf v60-*.whl setzen
# (https://developer.download.nvidia.com/compute/redist/jp/v60/pytorch/).
ARG NV_TORCH_WHEEL=https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl
# Ohne feste Architektur baut torchvision CUDA für viele SM → extrem langsam / hohe Last (SSH kann wegbrechen).
# Orin Nano/NX/AGX = 8.7. Jetson Xavier = 7.2 (build-arg in compose.yaml setzen).
ARG TORCH_CUDA_ARCH_LIST=8.7
# Bei OOM während des Wheel-Builds: z. B. COMPILE_JOBS=2 setzen (sonst 0 = nproc).
ARG COMPILE_JOBS=0
# cuSPARSELt muss VOR torchvision-Setup stehen: deren pyproject importiert torch → sonst libcusparseLt.so.0 fehlt.
# Git-Build: --no-build-isolation + python3-dev (sonst Python.h fehlt).
# Wheel-Build vision/audio: trotzdem oft 45–120+ Min auf dem Nano; pip -v zeigt Compilerzeilen (nicht nur „still running“).
RUN pip uninstall -y torch torchvision torchaudio 2>/dev/null || true \
    && pip install --no-cache-dir "${NV_TORCH_WHEEL}" \
    && pip install --no-cache-dir "nvidia-cusparselt-cu12" \
    && CUPLIB="$(dirname "$(find /usr/local/lib/python3.10/dist-packages/nvidia/cusparselt -name 'libcusparseLt.so*' -print -quit)")" \
    && test -n "$CUPLIB" && test "$CUPLIB" != "." \
    && echo "$CUPLIB" > /etc/ld.so.conf.d/nvidia-cusparselt.conf && ldconfig \
    && python3 -c "import ctypes; ctypes.CDLL('libcusparseLt.so.0'); import torch; print('torch+cusparselt: OK')" \
    && pip install --no-cache-dir "numpy>=1.25.0,<2" \
    && export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
    && if [ "${COMPILE_JOBS}" -gt 0 ] 2>/dev/null; then J="${COMPILE_JOBS}"; else J="$(nproc)"; fi \
    && export MAX_JOBS="$J" CMAKE_BUILD_PARALLEL_LEVEL="$J" NINJA_STATUS='[%f/%t] ' \
    && pip install -v --no-cache-dir --no-build-isolation "git+https://github.com/pytorch/vision@v0.20.0" --no-deps \
    && pip install -v --no-cache-dir --no-build-isolation "git+https://github.com/pytorch/audio@v2.5.0" --no-deps \
    && python3 -c "import numpy; import torch; import torchvision; print('numpy', numpy.__version__, 'torch', torch.__version__, 'torchvision', torchvision.__version__)"

ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH}

EXPOSE 8188

CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
