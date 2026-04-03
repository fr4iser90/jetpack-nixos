# Pipeline Core

Pipeline Core is the central orchestration service for a modular AI pipeline system.

It acts as the "brain" of the infrastructure by coordinating multiple independent services such as LLMs, image generation tools, and audio processing workers.

---

## 🧠 Purpose

The goal of Pipeline Core is to unify and control different AI services through a single API layer.

Instead of interacting with each service individually, clients communicate only with Pipeline Core, which handles:

* Prompt generation (via LLMs)
* Task distribution (e.g. ComfyUI, Whisper)
* Job lifecycle management
* Asset storage and organization

---

## 🏗️ Architecture Overview

```
Clients (Discord / Web / CLI)
            ↓
      Pipeline Core (API)
        /     |      \
     LLM   ComfyUI   Whisper
```

* **Pipeline Core** → orchestration & logic
* **Workers** → execute tasks (generation, transcription, etc.)
* **Clients** → trigger jobs and consume results

---

## ⚙️ Responsibilities

Pipeline Core is responsible for:

* Providing a unified API (`/generate`, `/jobs`, `/assets`)
* Managing job queues and execution flow
* Generating or transforming prompts via LLM services
* Communicating with worker services via their APIs
* Storing outputs and metadata (e.g. prompts, seeds, timestamps)
* Handling retries, failures, and logging

---

## 🚀 Example Workflow

1. A client sends a request:

```json
POST /generate
{
  "type": "image",
  "style": "sci-fi",
  "amount": 10
}
```

2. Pipeline Core:

   * generates prompts using an LLM
   * sends jobs to ComfyUI
   * collects results

3. Assets are stored and made accessible via the API.

---

## 🔌 Integrated Services

Typical integrations include:

* ComfyUI (image generation)
* Ollama or other LLM providers (prompt generation)
* Whisper (speech-to-text)
* Additional custom workers

---

## 📦 Project Structure (WIP)

```
pipeline-core/
├── app/
├── routes/
├── services/
├── models/
├── workers/
└── main.py
```

---

## 🧪 Status

Work in progress.
The system is under active development and subject to change.

---

## 💡 Vision

Pipeline Core is designed to evolve into a fully autonomous AI asset pipeline, capable of:

* Continuous asset generation
* Multi-modal processing (image, text, audio)
* Integration with external systems (Discord bots, web dashboards)
* Scalable, distributed workloads

---

## 📜 License

TBD
