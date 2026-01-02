"""CLI entrypoint for launching the TeachArm server."""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

try:
    from .config import load_settings
    from .server import create_app
except ImportError:  # fallback when executed as a script
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from teacharm.config import load_settings
    from teacharm.server import create_app


def run() -> None:
    settings = load_settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
