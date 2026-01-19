#!/usr/bin/env python3
"""Record audio from microphone and send to TeachArm API."""

from __future__ import annotations

import argparse
import os
import wave
from typing import Optional

import numpy as np
import requests
import sounddevice as sd


def record_audio(
    duration: float,
    samplerate: int,
    channels: int,
    device: Optional[int],
) -> np.ndarray:
    sd.default.samplerate = samplerate
    sd.default.channels = channels
    if device is not None:
        sd.default.device = device
    audio = sd.rec(int(duration * samplerate), dtype="float32")
    sd.wait()
    return audio


def save_wav(path: str, audio: np.ndarray, samplerate: int) -> None:
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(audio_int16.shape[1] if audio_int16.ndim > 1 else 1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio_int16.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record microphone audio and send to TeachArm API."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=4.0,
        help="Recording duration in seconds.",
    )
    parser.add_argument(
        "--samplerate",
        type=int,
        default=16000,
        help="Sampling rate in Hz.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Number of channels.",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Input device index (optional).",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default="http://localhost:8000/api/dialogue/audio",
        help="API endpoint URL.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="ASR language code (optional).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="recording.wav",
        help="Output WAV file path.",
    )

    args = parser.parse_args()

    print("Recording...")
    audio = record_audio(
        duration=args.duration,
        samplerate=args.samplerate,
        channels=args.channels,
        device=args.device,
    )
    save_wav(args.output, audio, args.samplerate)
    print(f"Saved: {args.output}")

    files = {
        "audio": (
            os.path.basename(args.output),
            open(args.output, "rb"),
            "audio/wav",
        )
    }
    data = {}
    if args.language:
        data["language"] = args.language

    response = requests.post(args.endpoint, files=files, data=data, timeout=60)
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()
