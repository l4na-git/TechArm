"""Scan Feetech motor IDs on a single bus.

Usage:
  python scripts/scan_motor_ids.py --port /dev/tty.usbmodemXXXX --baudrate 1000000
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
from pathlib import Path

try:
    from teacharm.config import load_settings
except ImportError:  # fallback when executed as a script
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from teacharm.config import load_settings

try:
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
except ImportError:
    from lerobot.motors.feetech import FeetechMotorsBus


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan Feetech motor IDs on the bus"
    )
    parser.add_argument(
        "--port",
        type=str,
        default=None,
        help="Serial port (defaults to .env SO101_PORT)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=None,
        help="Baudrate (defaults to config motor_config.baudrate)",
    )
    return parser


def _maybe_await(result: object) -> object:
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _read_model_number(bus: FeetechMotorsBus, motor_id: int) -> int | None:
    read = getattr(bus, "read", None)
    if read is None:
        return None
    for args in (("Model_Number", motor_id), ("Model_Number",)):
        try:
            value = _maybe_await(read(*args))
            return int(value) if value is not None else None
        except TypeError:
            continue
        except Exception:
            return None
    return None


def main() -> None:
    args = _build_parser().parse_args()
    settings = load_settings()
    port = args.port or settings.so101_port
    if not port:
        raise SystemExit("Missing port. Use --port or set SO101_PORT.")
    baudrate = args.baudrate or settings.so101_baudrate or 1_000_000

    kwargs = {"port": port, "baudrate": baudrate}
    try:
        signature = inspect.signature(FeetechMotorsBus)
        kwargs = {k: v for k, v in kwargs.items() if k in signature.parameters}
        if "motors" in signature.parameters and "motors" not in kwargs:
            # Some versions require a motors dict even for raw bus access.
            kwargs["motors"] = {}
    except (TypeError, ValueError):
        pass
    bus = FeetechMotorsBus(**kwargs)
    try:
        bus.connect(handshake=False)  # Avoid handshake for unstable motors
        found = []
        for motor_id in list(range(0, 254)) + [254]:
            try:
                if bus.ping(motor_id):
                    found.append(motor_id)
            except Exception:
                pass
        print("FOUND:", found)
        if found:
            model_numbers = {
                motor_id: _read_model_number(bus, motor_id)
                for motor_id in found
            }
            print("MODEL_NUMBER:", model_numbers)
    finally:
        for fn in ("disconnect", "close"):
            if hasattr(bus, fn):
                try:
                    getattr(bus, fn)()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
