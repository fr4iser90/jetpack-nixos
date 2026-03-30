#!/usr/bin/env python3
"""Minimal CLI: transcribe one audio file (faster-whisper)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> int:
    p = argparse.ArgumentParser(description="Transcribe audio with faster-whisper")
    p.add_argument(
        "audio",
        nargs="?",
        default="/data/audio.wav",
        help="Path to audio file (default: /data/audio.wav)",
    )
    p.add_argument(
        "--model",
        default="tiny",
        help="Model size: tiny, base, small, medium, large-v2, ...",
    )
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    p.add_argument(
        "--compute-type",
        default="int8",
        help="e.g. int8 (CPU), float16 (GPU)",
    )
    args = p.parse_args()
    path = Path(args.audio)
    if not path.is_file():
        print(f"Missing audio file: {path}", file=sys.stderr)
        return 1

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(str(path))
    print(f"language={info.language} probability={info.language_probability:.3f}")
    for seg in segments:
        print(seg.text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
