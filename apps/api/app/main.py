"""ASGI app re-export for ``uvicorn app.main:app`` (same instance as ``main:app``).

The project root module ``main`` lives next to the ``app`` package; keep
``PYTHONPATH`` set to ``apps/api`` (repo default for Docker / local runs).
"""

from main import app

__all__ = ["app"]
