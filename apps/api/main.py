"""API entrypoint: ``uvicorn main:app --app-dir apps/api --port 8000``."""

from __future__ import annotations

from us_watcher.api.app import create_app

app = create_app()
