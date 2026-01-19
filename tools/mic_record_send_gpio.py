#!/usr/bin/env python3
"""Record audio while holding a GPIO button and send to TeachArm API."""

from __future__ import annotations

import argparse
import os
import threading
import wave
from typing import Optional

import numpy as np
import requests
import sounddevice as sd
from gpiozero import Button


def save_wav(path: str, audio: np.ndarray, samplerate: int) -> None:
    audio = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(audio_int16.shape[1] if audio_int16.ndim > 1 else 1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio_int16.tobytes())


def send_audio(
    endpoint: str,
    path: str,
    language: Optional[str],
) -> None:
    files = {
        "audio": (
            os.path.basename(path),
            open(path, "rb"),
            "audio/wav",
        )
    }
    data = {}
    if language:
        data["language"] = language
    response = requests.post(endpoint, files=files, data=data, timeout=60)
    response.raise_for_status()
    print(response.text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record while holding a GPIO button and send to TeachArm API."
    )
    parser.add_argument(
        "--pin",
        type=int,
        default=17,
        help="GPIO pin number (BCM mode).",
    )
    parser.add_argument(
        "--pull-up",
        action="store_true",
        help="Use pull-up resistor (default: pull-down).",
    )
    parser.add_argument(
        "--bounce",
        type=float,
        default=0.05,
        help="Button debounce time in seconds.",
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

    if args.device is not None:
        sd.default.device = args.device
    sd.default.samplerate = args.samplerate
    sd.default.channels = args.channels

    buffer_lock = threading.Lock()
    frames: list[np.ndarray] = []
    recording = threading.Event()
    sending = threading.Event()

    def on_audio(indata: np.ndarray, _frames: int, _time, _status) -> None:
        if not recording.is_set():
            return
        with buffer_lock:
            frames.append(indata.copy())

    def start_recording() -> None:
        if recording.is_set() or sending.is_set():
            return
        with buffer_lock:
            frames.clear()
        recording.set()
        print("Recording...")

    def stop_recording() -> None:
        if not recording.is_set():
            return
        recording.clear()
        with buffer_lock:
            if not frames:
                print("No audio captured.")
                return
            audio = np.concatenate(frames, axis=0)
        sending.set()
        try:
            save_wav(args.output, audio, args.samplerate)
            print(f"Saved: {args.output}")
            send_audio(args.endpoint, args.output, args.language)
        finally:
            sending.clear()

    button = Button(
        args.pin, pull_up=args.pull_up, bounce_time=args.bounce
    )
    button.when_pressed = start_recording
    button.when_released = stop_recording

    print("Hold the button to record. Press Ctrl+C to quit.")
    with sd.InputStream(callback=on_audio):
        try:
            while True:
                button.wait_for_press()
                button.wait_for_release()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
