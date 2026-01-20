#!/usr/bin/env python3
"""Record audio from microphone and send to TeachArm API."""

from __future__ import annotations

import argparse
import os
import json
import tempfile
from urllib.parse import urljoin
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


def read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        samplerate = wf.getframerate()
        frames = wf.getnframes()
        data = wf.readframes(frames)

    if sampwidth == 1:
        audio = np.frombuffer(data, dtype=np.uint8)
        audio = (audio.astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        audio = np.frombuffer(data, dtype=np.int16)
        audio = audio.astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(data, dtype=np.int32)
        audio = audio.astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")

    if channels > 1:
        audio = audio.reshape(-1, channels)
    return audio, samplerate


def play_audio(path: str) -> None:
    audio, samplerate = read_wav(path)
    sd.play(audio, samplerate=samplerate)
    sd.wait()


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
    parser.add_argument(
        "--play-response",
        action="store_true",
        help="Play the synthesized response audio when available.",
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

    try:
        payload = response.json()
    except json.JSONDecodeError:
        print(response.text)
        return

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    audio_path = payload.get("audio_path")
    if args.play_response and audio_path:
        if os.path.exists(audio_path):
            print(f"Playing: {audio_path}")
            play_audio(audio_path)
            return

        filename = os.path.basename(audio_path)
        endpoint_base = args.endpoint.rsplit("/api/", 1)[0] + "/"
        audio_url = urljoin(endpoint_base, f"api/tts/audio/{filename}")
        try:
            audio_resp = requests.get(audio_url, timeout=30)
            audio_resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"Failed to fetch audio: {exc}")
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_resp.content)
            tmp_path = tmp.name

        print(f"Playing: {audio_url}")
        play_audio(tmp_path)
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
