"""Regression test: pin the `httptools.HttpRequestParser` symbol.

Background — v0.2 web-UI "hang" investigation
-----------------------------------------------
In v0.2, the Web UI server (`hello-agent serve serve`) would boot, log
"Application startup complete", and then silently fail every HTTP
request with::

    AttributeError: module 'httptools' has no attribute 'HttpRequestParser'

The TCP listener stayed up, but no request was ever parsed — the
`uvicorn.protocols.http.httptools_impl` protocol needs the
`httptools.HttpRequestParser` C-extension class, and the locked
environment in the failing setup pulled in a *stub* `httptools`
package (e.g. a meta-package or a too-old `sdist` without the
compiled extension). uvicorn>=0.30 requires httptools>=0.6 with
`HttpRequestParser`; anything older or stubbed produces the
AttributeError above and a hard server hang.

This test pins two things:

1. The installed `httptools` exposes `HttpRequestParser` (the symbol
   uvicorn's httptools protocol reaches for on every connection).
2. The protocol class `uvicorn.protocols.http.httptools_impl.HttpToolsProtocol`
   can be imported (it requires a working `httptools` to even load).

If either regresses — for example after a bad `uv lock --upgrade-package httptools`
that lands a stub — the test fails fast with a clear message,
before a user has to discover the failure by clicking around the UI.
"""
from __future__ import annotations

import httptools
import pytest


def test_httptools_exposes_HttpRequestParser() -> None:
    """httptools must expose `HttpRequestParser` (uvicorn>=0.30 requirement)."""
    assert hasattr(httptools, "HttpRequestParser"), (
        f"httptools {httptools.__version__} is missing HttpRequestParser — "
        "uvicorn's httptools protocol will AttributeError on every connection. "
        "Check the lockfile: a stub or too-old sdist may have been pulled in. "
        "uvicorn>=0.30 needs httptools>=0.6 with the compiled extension."
    )


def test_httptools_exposes_HttpResponseParser() -> None:
    """httptools must also expose `HttpResponseParser` (response side)."""
    assert hasattr(httptools, "HttpResponseParser"), (
        f"httptools {httptools.__version__} is missing HttpResponseParser. "
        "The compiled httptools extension is not installed correctly."
    )


def test_uvicorn_httptools_protocol_imports() -> None:
    """`HttpToolsProtocol` must be importable — it depends on a working httptools."""
    from uvicorn.protocols.http import httptools_impl

    assert hasattr(httptools_impl, "HttpToolsProtocol"), (
        "uvicorn's HttpToolsProtocol class is missing — httptools is broken."
    )
    # Sanity: protocol module's `httptools` symbol points at the real package.
    assert httptools_impl.httptools is httptools, (
        "uvicorn.protocols.http.httptools_impl is bound to a different "
        "httptools module than the one imported here. Multiple installs?"
    )


@pytest.mark.parametrize("name", ["parse_url", "HttpParserError"])
def test_httptools_public_api(name: str) -> None:
    """Other public httptools symbols uvicorn / pytdantic / downstream tools rely on."""
    assert hasattr(httptools, name), f"httptools missing public symbol: {name!r}"
