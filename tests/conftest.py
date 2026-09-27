"""Shared test helpers. The whole suite is OFFLINE: real network access fails loudly."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zalat.fng import CrowdSignal, signal_from_value  # noqa: E402
from zalat.nansen_mcp import ToolResult  # noqa: E402

FAKE_KEY = "sk-test-SECRET-0123456789abcdef"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real HTTP request or internet socket connect raises NetworkBlocked."""

    async def _no_async(self: Any, request: httpx.Request) -> httpx.Response:
        raise NetworkBlocked(f"real network call attempted: {request.url}")

    def _no_sync(self: Any, request: httpx.Request) -> httpx.Response:
        raise NetworkBlocked(f"real network call attempted: {request.url}")

    real_connect = socket.socket.connect

    def _guarded_connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise NetworkBlocked(f"socket connect attempted: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _no_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_sync)
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's real key or overrides."""
    for var in ("NANSEN_API_KEY", "NANSEN_MCP_URL", "NANSEN_API_KEY_HEADER",
                "ZALAT_TIMEOUT", "ZALAT_FNG_URL"):
        monkeypatch.delenv(var, raising=False)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ok(tool: str, text: str) -> ToolResult:
    return ToolResult(tool=tool, ok=True, text=text, latency_ms=5.0)


def tool_error(tool: str, reason: str = "unclassified_failure") -> ToolResult:
    return ToolResult(tool=tool, ok=False, text=f"NANSEN_TOOL_ERROR reason: {reason}",
                      is_error=True, error_kind="tool_error", latency_ms=5.0, reason=reason)


Responder = ToolResult | Callable[[dict], ToolResult]


class FakeNansenClient:
    """In-memory stand-in for NansenMCPClient.

    ``responses`` maps tool name -> ToolResult or a callable(arguments) -> ToolResult.
    Unknown tools return a tool error. Every call is recorded in ``calls``.
    It is also its own async context manager and "factory" (``factory(settings)``).
    """

    def __init__(self, responses: dict[str, Responder] | None = None,
                 enter_exc: BaseException | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []
        self.enter_exc = enter_exc
        self.settings: Any = None

    def factory(self, settings: Any) -> "FakeNansenClient":
        self.settings = settings
        return self

    async def __aenter__(self) -> "FakeNansenClient":
        if self.enter_exc is not None:
            raise self.enter_exc
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def call(self, tool: str, arguments: dict) -> ToolResult:
        self.calls.append((tool, arguments))
        r = self.responses.get(tool)
        if r is None:
            return tool_error(tool)
        return r(arguments) if callable(r) else r


def happy_responses() -> dict[str, Responder]:
    """Search -> PEPE; flows -> SM inflow; BUY > SELL."""

    def wbs(args: dict) -> ToolResult:
        side = args["request"]["buy_or_sell"]
        name = "wbs_buy_md.txt" if side == "BUY" else "wbs_sell_md.txt"
        return ok("token_who_bought_sold", fixture_text(name))

    return {
        "general_search": ok("general_search", fixture_text("search_pepe.json")),
        "token_recent_flows_summary": ok("token_recent_flows_summary", fixture_text("flows_md.txt")),
        "token_who_bought_sold": wbs,
    }


def fng_const(value: int | None) -> Callable[[str, float], Any]:
    """A fake Fear & Greed fetcher returning a fixed value (None = unavailable)."""

    async def _fetch(url: str, timeout: float) -> CrowdSignal:
        if value is None:
            return CrowdSignal(False, error="offline")
        return signal_from_value(value, "test")

    return _fetch
