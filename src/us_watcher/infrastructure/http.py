"""Shared HTTP client construction.

Building an ``httpx`` client constructs an ``ssl.SSLContext`` via
``ssl.create_default_context()``, which loads the entire OS trust store. On
Windows (notably under CPython 3.14) that load is CPU-heavy. Creating a fresh
client per request therefore rebuilds the SSL context every single time.

Under the market-overview fan-out (~11 symbols) and the recommendation
universe (~190), this rebuilt the trust store dozens of times *on the event
loop thread*, pegging a core and making the API hang — ``/health`` itself timed
out — until the process was restarted. (The retry note in
``market/service.py`` already observed that "a retry storm of new TLS clients
spikes CPU"; this is the underlying cause.)

The fix: build the SSL context **once per process** and reuse it for every
client via ``verify=``. httpx skips ``create_ssl_context`` when ``verify`` is an
``ssl.SSLContext``, so the expensive trust-store load happens a single time.
We still create a client per call (cheap once the context is shared), which
keeps each caller's ``async with`` lifecycle and avoids binding one client to a
single event loop.
"""

from __future__ import annotations

import ssl
from typing import Any

import httpx

_ssl_context: ssl.SSLContext | None = None


def shared_ssl_context() -> ssl.SSLContext:
    """Return a process-wide SSL context, built once and reused thereafter."""
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context()
    return _ssl_context


def new_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """``httpx.AsyncClient`` that reuses the process-wide SSL context.

    Accepts the same keyword arguments as ``httpx.AsyncClient`` (``timeout``,
    ``headers``, ``follow_redirects``, …). ``verify`` defaults to the shared
    context unless the caller passes its own.
    """
    kwargs.setdefault("verify", shared_ssl_context())
    return httpx.AsyncClient(**kwargs)
