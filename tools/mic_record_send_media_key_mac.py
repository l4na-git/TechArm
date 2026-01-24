#!/usr/bin/env python3
"""Record audio while holding a Mac media key (e.g., play/pause)."""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import tempfile
import threading
import wave
from typing import Optional
from urllib.parse import urljoin

import numpy as np
import requests
import sounddevice as sd
from AppKit import NSEvent
from CoreFoundation import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRunInMode,
    CFRunLoopStop,
    kCFRunLoopDefaultMode,
    kCFRunLoopCommonModes,
)
from Quartz.CoreGraphics import (
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCGHeadInsertEventTap,
    kCGHIDEventTap,
    kCGEventTapOptionDefault,
)


KEY_CODE_MAP = {
    "play": 16,  # NX_KEYTYPE_PLAY
    "next": 17,  # NX_KEYTYPE_NEXT
    "prev": 18,  # NX_KEYTYPE_PREVIOUS
    "fast": 19,  # NX_KEYTYPE_FAST
    "rewind": 20,  # NX_KEYTYPE_REWIND
}

NX_SUBTYPE_AUX_CONTROL_BUTTONS = 8
KEY_STATE_DOWN = 0x0A
KEY_STATE_UP = 0x0B
K_CG_EVENT_SYSTEM_DEFINED = 14


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


def send_audio(
    endpoint: str,
    path: str,
    language: Optional[str],
    play_response: bool,
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
    try:
        response = requests.post(endpoint, files=files, data=data, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Failed to send audio: {exc}")
        return
    try:
        payload = response.json()
    except json.JSONDecodeError:
        print(response.text)
        return

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    audio_path = payload.get("audio_path")
    if not play_response or not audio_path:
        return
    if os.path.exists(audio_path):
        print(f"Playing: {audio_path}")
        play_audio(audio_path)
        return

    filename = os.path.basename(audio_path)
    endpoint_base = endpoint.rsplit("/api/", 1)[0] + "/"
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record while holding a Mac media key and send to TeachArm API."
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
        "--media-key",
        type=str,
        default="play",
        choices=sorted(KEY_CODE_MAP.keys()),
        help="Media key to hold (default: play).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="hold",
        choices=["hold", "toggle"],
        help="Recording mode: hold or toggle.",
    )
    parser.add_argument(
        "--play-response",
        action="store_true",
        default=True,
        help="Play the synthesized response audio when available (default: on).",
    )
    parser.add_argument(
        "--no-play-response",
        dest="play_response",
        action="store_false",
        help="Disable response audio playback.",
    )
    args = parser.parse_args()

    if args.device is not None:
        sd.default.device = args.device
    sd.default.samplerate = args.samplerate
    sd.default.channels = args.channels

    target_key_code = KEY_CODE_MAP[args.media_key]
    buffer_lock = threading.Lock()
    frames: list[np.ndarray] = []
    recording = threading.Event()
    sending = threading.Event()
    stop_event = threading.Event()
    control_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

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
            send_audio(
                args.endpoint,
                args.output,
                args.language,
                args.play_response,
            )
        finally:
            sending.clear()

    def toggle_recording() -> None:
        if recording.is_set():
            stop_recording()
        else:
            start_recording()

    def control_loop() -> None:
        while not stop_event.is_set():
            try:
                action = control_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if action == "press":
                start_recording()
            elif action == "release":
                stop_recording()
            elif action == "toggle":
                toggle_recording()
            elif action == "stop":
                break

    def event_callback(_proxy, event_type, event, _refcon):
        if event_type != K_CG_EVENT_SYSTEM_DEFINED:
            return event
        ns_event = NSEvent.eventWithCGEvent_(event)
        if ns_event is None or ns_event.subtype() != NX_SUBTYPE_AUX_CONTROL_BUTTONS:
            return event
        data = ns_event.data1()
        key_code = (data & 0xFFFF0000) >> 16
        key_state = (data & 0x0000FF00) >> 8
        if key_code != target_key_code:
            return event
        if key_state == KEY_STATE_DOWN:
            if args.mode == "toggle":
                control_queue.put("toggle")
            else:
                control_queue.put("press")
        elif key_state == KEY_STATE_UP and args.mode == "hold":
            control_queue.put("release")
        return event

    tap = CGEventTapCreate(
        kCGHIDEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        CGEventMaskBit(K_CG_EVENT_SYSTEM_DEFINED),
        event_callback,
        None,
    )
    if tap is None:
        print(
            "Failed to create event tap. "
            "Grant Accessibility permission to your Python app."
        )
        return

    run_loop = CFRunLoopGetCurrent()

    def handle_sigint(_sig, _frame) -> None:
        stop_event.set()
        control_queue.put("stop")
        CFRunLoopStop(run_loop)

    signal.signal(signal.SIGINT, handle_sigint)

    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(run_loop, source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)

    control_thread = threading.Thread(target=control_loop, daemon=True)
    control_thread.start()

    if args.mode == "toggle":
        hint = f"Press the {args.media_key} key to toggle recording."
    else:
        hint = f"Hold the {args.media_key} key to record."
    print(f"{hint} Press Ctrl+C to quit.")
    with sd.InputStream(callback=on_audio):
        try:
            while not stop_event.is_set():
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, True)
        except KeyboardInterrupt:
            stop_event.set()
            control_queue.put("stop")
            CFRunLoopStop(run_loop)


if __name__ == "__main__":
    main()
