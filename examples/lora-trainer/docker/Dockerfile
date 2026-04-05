# CPU PyTorch — good for wiring the compose layout; real LoRA training usually wants Dockerfile.gpu + profile gpu.
FROM python:3.11-slim-bookworm

WORKDIR /work

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY scripts/ /work/scripts/

CMD ["python", "-c", "print('lora-trainer: use docker compose run … or exec into container')"]
