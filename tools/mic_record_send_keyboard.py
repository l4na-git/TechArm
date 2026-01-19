#!/usr/bin/env python3
"""Record audio while holding a keyboard key and send to TeachArm API."""

from __future__ import annotations

import argparse
import os
import threading
import wave
from typing import Optional

import numpy as np
import requests
import sounddevice as sd
from pynput import keyboard


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
        description="Record while holding a key and send to TeachArm API."
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
        "--key",
        type=str,
        default="space",
        help="Key to hold for recording (default: space).",
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
    stop_event = threading.Event()

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

    def _matches_key(key_obj) -> bool:
        if args.key.lower() == "space":
            return key_obj == keyboard.Key.space
        if args.key.lower() == "enter":
            return key_obj == keyboard.Key.enter
        if isinstance(key_obj, keyboard.KeyCode):
            return key_obj.char == args.key
        return False

    def on_press(key_obj) -> None:
        if key_obj == keyboard.Key.esc:
            stop_event.set()
            return False
        if _matches_key(key_obj):
            start_recording()

    def on_release(key_obj) -> None:
        if _matches_key(key_obj):
            stop_recording()

    print("Hold the key to record. Press ESC to quit.")
    with sd.InputStream(callback=on_audio):
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            stop_event.wait()
            listener.stop()


if __name__ == "__main__":
    main()
