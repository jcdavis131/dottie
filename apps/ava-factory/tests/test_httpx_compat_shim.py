"""The conftest httpx>=0.28 shim must be lossless, not merely quiet.

httpx 0.28 removed `Client(app=...)`. starlette 0.27's TestClient still passes it --
alongside the real `transport=` it built itself -- so all 21 server-endpoint tests
died at setup with TypeError. conftest.py restores the parameter by dropping it.

Dropping it is only safe BECAUSE a transport came with it. `app=` alone *was* the
routing; discarding that silently makes httpx open a real socket to base_url, and a
test that believes it is sandboxed would quietly hit the network. So the shim refuses
that case, and this file exists to prove the refusal actually fires -- a guard nothing
exercises is indistinguishable from no guard.

    AVA_FACTORY_ROOT="$PWD" python -m pytest tests/test_httpx_compat_shim.py -q
"""

import inspect

import pytest

httpx = pytest.importorskip("httpx")

# The shim only installs on httpx >= 0.28. On older httpx `app` is native and there is
# nothing to test -- skipping is correct, but it must be VISIBLE, not silent, or this
# file could pass forever while testing nothing.
SHIM_INSTALLED = getattr(httpx.Client.__init__, "_ava_drops_app", False)
pytestmark = pytest.mark.skipif(
    not SHIM_INSTALLED,
    reason=f"shim not installed (httpx {httpx.__version__} accepts `app` natively)",
)


def test_the_shim_is_actually_installed_on_this_box():
    """Anti-vacuity. Pairs with the skipif: on the versions we ship, it must be on.
    If httpx is >= 0.28 and the shim is missing, every test below silently skips."""
    major, minor = (int(p) for p in httpx.__version__.split(".")[:2])
    if (major, minor) >= (0, 28):
        assert SHIM_INSTALLED, (
            f"httpx {httpx.__version__} dropped `app` but conftest did not patch it"
        )


def test_app_is_gone_from_the_underlying_signature():
    """Establishes the premise. If httpx ever restores `app`, the shim is dead weight
    and this test says so instead of leaving it to rot."""
    unwrapped = inspect.unwrap(httpx.Client.__init__)
    assert "app" not in inspect.signature(unwrapped).parameters


def test_app_plus_transport_is_accepted_and_routes_through_the_transport():
    """The starlette shape. `app` is dropped; the transport still does the routing --
    proven by a real in-process response, not by the constructor merely not raising."""

    def _asgi_app(scope, receive, send):
        raise AssertionError("`app` was used for routing; it should have been dropped")

    calls = []

    class _RecordingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            calls.append(request.url.path)
            return httpx.Response(200, text="from-transport")

    with httpx.Client(
        app=_asgi_app,
        transport=_RecordingTransport(),
        base_url="http://testserver",
    ) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.text == "from-transport"
    assert calls == ["/health"], f"transport was bypassed: {calls}"


def test_app_without_transport_is_refused_loudly():
    """The dangerous case. Dropping `app` here would silently un-sandbox the caller."""

    def _asgi_app(scope, receive, send):  # pragma: no cover - never invoked
        raise AssertionError("unreachable")

    with pytest.raises(TypeError) as excinfo:
        httpx.Client(app=_asgi_app, base_url="http://testserver")

    msg = str(excinfo.value)
    assert "without transport" in msg, f"unhelpful message: {msg}"
    assert "ASGITransport" in msg, "the error must name the fix, not just the problem"


def test_explicit_transport_none_is_also_refused():
    """`transport=None` is the default spelled out. A `in kwargs` check would let it
    through; the shim tests the VALUE. Regression guard against that exact rewrite."""

    def _asgi_app(scope, receive, send):  # pragma: no cover - never invoked
        raise AssertionError("unreachable")

    with pytest.raises(TypeError):
        httpx.Client(app=_asgi_app, transport=None, base_url="http://testserver")


def test_ordinary_construction_is_untouched():
    """The shim must not perturb the 17 packages that share httpx on this box --
    anthropic, openai, mcp, litellm, chromadb, qdrant-client, scout-cli. None of them
    pass `app`, so none of them may notice the wrapper."""

    class _Stub(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(204)

    with httpx.Client(transport=_Stub(), base_url="http://example.invalid") as client:
        assert client.get("/").status_code == 204
        assert str(client.base_url) == "http://example.invalid"


def test_shim_is_idempotent():
    """conftest is imported once per session, but pytest-xdist and nested test runs
    can re-enter it. The `_ava_drops_app` sentinel must prevent stacked wrappers --
    each extra layer adds another silent `app=None` default."""
    depth = 0
    fn = httpx.Client.__init__
    while getattr(fn, "_ava_drops_app", False):
        depth += 1
        nxt = getattr(fn, "__wrapped__", None)
        assert nxt is not None, "wrapper has no __wrapped__; signature cannot resolve"
        assert depth < 10, "unwrap did not terminate"
        fn = nxt
    assert depth == 1, f"shim applied {depth} times; sentinel is not holding"
