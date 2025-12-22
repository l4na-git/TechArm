"""CLI entrypoint for launching the TeachArm server."""

from __future__ import annotations

import uvicorn

from .config import load_settings
from .server import create_app


def run() -> None:
    settings = load_settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
