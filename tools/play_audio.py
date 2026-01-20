"""Play a WAV file through the default audio device."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a WAV file.")
    parser.add_argument("path", type=Path, help="Path to a WAV file")
    args = parser.parse_args()

    if not args.path.exists():
        raise SystemExit(f"File not found: {args.path}")

    audio, samplerate = read_wav(args.path)
    sd.play(audio, samplerate=samplerate)
    sd.wait()


if __name__ == "__main__":
    main()
