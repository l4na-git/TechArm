"""TeachArm runtime package."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["create_app"]

if TYPE_CHECKING:
    from .server import create_app as create_app


def __getattr__(name: str):
    if name == "create_app":
        from .server import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + ["create_app"])
