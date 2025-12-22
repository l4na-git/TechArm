"""TeachArm runtime package."""

__all__ = [
    "create_app",
]

from .server import create_app  # noqa: E402
