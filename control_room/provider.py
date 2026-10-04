"""The provider seam: an OpenAI-compatible DeepSeek client, built explicitly at runtime.

This is the ONE place the agentic assistance surface is allowed to reach a paid provider
(AGENTS.md D6, Amendment 1). It is not on the enforcement path: no model output here is ever
an authorization decision - the kernel's verdict is the only execution boundary.

Rules this module keeps:

* the client is built from ``DEEPSEEK_API_KEY`` read **by name**; no code path here touches
  ``OPENAI_API_KEY`` (the SDK's implicit env-based client is never used);
* the key is never printed, logged, echoed or returned - :func:`provider_status` reports
  PRESENT/ABSENT only;
* a missing key or a provider failure degrades (returns ``None``); it never crashes the
  process and never turns into an allow.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://api.deepseek.com"
MODEL = os.environ.get("TENET_MODEL", "deepseek-chat")
KEY_ENV = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class Provider:
    """A configured provider handle. ``client`` is an ``AsyncOpenAI`` bound to DeepSeek."""

    name: str
    model: str
    base_url: str
    client: Any


# The provider's own event journal: one safe line per real call, so the deployment can show
# what the answer above it was built from without ever writing a key, a header or a body. The
# path is env-named so the platform can keep it next to the rest of the state.
EVENT_LOG_ENV = "TENET_DEEPSEEK_LOG"
DEFAULT_EVENT_LOG = "state/provider/deepseek-events.jsonl"

# The run id the orchestrator is currently serving. A context var, so an async caller cannot
# stamp its events onto another caller's run.
_RUN_ID: "contextvars.ContextVar[str | None]" = contextvars.ContextVar("tenet_run_id", default=None)


def set_run_id(run_id: str | None) -> None:
    """Bind the run id that every provider event must carry. Set once, by :func:`answer`."""
    _RUN_ID.set(run_id)


def current_run_id() -> str | None:
    return _RUN_ID.get()


def event_log_path() -> str:
    return os.environ.get(EVENT_LOG_ENV, "").strip() or DEFAULT_EVENT_LOG


def emit(event: dict) -> None:
    """Append one event. Safe fields only - never a key, a header value, a prompt or a body."""
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    print("[deepseek] " + line, flush=True)  # the platform's log carries it too
    path = Path(event_log_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_events(run_id: str = "") -> list[dict]:
    """Read the journal back. This is a read: it never calls the provider and never invents.

    An unreadable or missing journal is an empty list, which the caller must report as an
    absent step - not as a chain that passed.
    """
    out: list[dict] = []
    try:
        with open(event_log_path(), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if run_id and str(row.get("run_id") or "") != run_id:
                    continue
                out.append(row)
    except OSError:
        return []
    return out


class _EvidenceTransport:
    """The client's own transport, wrapped: one event pair per real provider call.

    It delegates every attribute and every request to the real transport under it, so the
    call path is unchanged; it only observes. A read of the response body is taken from the
    same object the SDK is about to read, so nothing is rewrapped and no connection is
    disturbed.
    """

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def handle_async_request(self, request: Any) -> Any:
        started = time.perf_counter()
        body = b""
        try:
            body = request.content if isinstance(request.content, (bytes, bytearray)) else b""
        except Exception:  # noqa: BLE001 - a body we cannot read must not break the call
            pass
        try:
            payload = json.loads(body.decode("utf-8", "ignore") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        base = {
            "run_id": current_run_id(),
            "provider": "deepseek",
            "base_url": "https://" + str(request.url.host),
            "path": str(request.url.path),
            "model_requested": payload.get("model"),
            "stream": bool(payload.get("stream")),
            "messages": len(payload.get("messages") or []),
            "tools_offered": len(payload.get("tools") or []),
            "prompt_sha256": hashlib.sha256(body).hexdigest(),
            # presence only: the header's value is never read out
            "has_authorization_header": bool(request.headers.get("authorization")),
        }
        emit({**base, "event": "deepseek.request.started"})
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:  # noqa: BLE001 - record, then let the failure travel
            emit({**base, "event": "deepseek.request.failed", "status": None,
                  "latency_ms": int((time.perf_counter() - started) * 1000),
                  "error": type(exc).__name__})
            raise
        raw = b""
        try:
            raw = await response.aread()
        except Exception:  # noqa: BLE001 - a stream we cannot buffer is still a real response
            pass
        try:
            parsed = json.loads(raw.decode("utf-8", "ignore") or "{}")
        except Exception:  # noqa: BLE001
            parsed = {}
        usage = parsed.get("usage") or {}
        choice = (parsed.get("choices") or [{}])[0] if isinstance(parsed.get("choices"), list) else {}
        emit({**base, "event": "deepseek.request.completed",
              "status": response.status_code,
              "request_id": response.headers.get("x-ds-trace-id"),
              "provider_response_id": parsed.get("id"),
              "model_served": parsed.get("model"),
              "finish_reason": choice.get("finish_reason"),
              "latency_ms": int((time.perf_counter() - started) * 1000),
              "input_tokens": usage.get("prompt_tokens"),
              "output_tokens": usage.get("completion_tokens"),
              "total_tokens": usage.get("total_tokens"),
              "response_sha256": hashlib.sha256(raw).hexdigest(),
              # the model may reason and propose; it never holds authority
              "llm_authority": False,
              "authority_source": "tenet-kernel"})
        return response



def summarize_events(events: list[dict]) -> dict[str, Any]:
    """Summarize one run's provider events without turning missing usage into zero."""
    completed = [e for e in events if e.get("event") == "deepseek.request.completed"]
    started = [e for e in events if e.get("event") == "deepseek.request.started"]
    failed = [e for e in events if e.get("event") == "deepseek.request.failed"]
    fields = ("input_tokens", "output_tokens", "total_tokens")
    usage_reported = bool(completed) and all(
        all(e.get(field) is not None for field in fields) for e in completed
    )
    if not started:
        token_status = "not_applicable"
        tokens: dict[str, int | None] = {field: 0 for field in fields}
    elif usage_reported:
        token_status = "reported"
        tokens = {field: sum(int(e.get(field) or 0) for e in completed) for field in fields}
    else:
        token_status = "not_reported"
        tokens = {field: None for field in fields}
    latest = completed[-1] if completed else (failed[-1] if failed else None)
    return {
        "model_called": bool(started),
        "model_completed": bool(completed),
        "model_calls": len(started),
        "calls_completed": len(completed),
        "calls_failed": len(failed),
        **tokens,
        "token_status": token_status,
        "model_requested": MODEL,
        "model_served": (latest or {}).get("model_served"),
        "trace_id": (latest or {}).get("request_id"),
    }

def key_present() -> bool:
    """PRESENT / ABSENT only. The value never leaves this expression."""
    return bool(os.environ.get(KEY_ENV, "").strip())


def build_provider() -> Optional[Provider]:
    """Build the DeepSeek client, or return ``None`` when it cannot be built.

    ``None`` is a degradation, not an error: the caller reports DEGRADED and refuses /api/ask
    with a reason. We never fall back to ``OPENAI_API_KEY`` or the SDK's default client.
    """
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        return None
    try:
        from openai import AsyncOpenAI
    except Exception:  # noqa: BLE001 - missing SDK is a degradation, not a crash
        return None
    try:
        client = AsyncOpenAI(api_key=key, base_url=BASE_URL)
    except Exception:  # noqa: BLE001
        return None
    # Wrap the client's own transport so every real call is journalled. Inside its own try: an
    # unwireable journal must never stop the provider from being built (the call path is older
    # and more important than the evidence about it).
    try:
        client._client._transport = _EvidenceTransport(client._client._transport)
    except Exception:  # noqa: BLE001
        pass
    return Provider(name="deepseek", model=MODEL, base_url=BASE_URL, client=client)


def provider_status() -> dict[str, Any]:
    """What /health may say about the provider. Never includes the key or its value."""
    return {"provider": "deepseek", "model": MODEL, "base_url": BASE_URL,
            "key": "PRESENT" if key_present() else "ABSENT",
            "event_log": event_log_path()}


def build_model(provider: "Provider") -> Any:
    """Wrap the DeepSeek client as an SDK model handle.

    The agents SDK defaults to ``OpenAIResponsesModel`` with an implicitly-constructed
    ``AsyncOpenAI()`` client, which reads ``OPENAI_API_KEY`` from the environment - a name this
    codebase must never depend on. We therefore build the chat-completions model **explicitly**
    around our DeepSeek client, so no code path can silently fall back to a default OpenAI
    client. Returns ``None`` when the SDK is missing (a degradation, not a crash).
    """
    try:
        from agents import OpenAIChatCompletionsModel
    except Exception:  # noqa: BLE001
        return None
    try:
        return OpenAIChatCompletionsModel(model=provider.model, openai_client=provider.client)
    except Exception:  # noqa: BLE001
        return None


def bind_sdk(provider: "Provider") -> Any:
    """Point the SDK's defaults at DeepSeek and hand back the model for the four agents."""
    model = build_model(provider)
    if model is None:
        return None
    try:
        from agents import set_default_openai_api, set_default_openai_client, set_tracing_disabled

        # Belt and braces: the run path also picks up an explicitly-set model, but a tool or a
        # handoff that resolves a model by default must resolve to DeepSeek too, never to a
        # client built from ``OPENAI_API_KEY``.
        set_default_openai_client(provider.client, use_for_tracing=False)
        set_default_openai_api("chat_completions")
        set_tracing_disabled(True)
    except Exception:  # noqa: BLE001 - the explicit model still works without the defaults
        pass
    return model
