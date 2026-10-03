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

import os
from dataclasses import dataclass
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
    return Provider(name="deepseek", model=MODEL, base_url=BASE_URL, client=client)


def provider_status() -> dict[str, Any]:
    """What /health may say about the provider. Never includes the key or its value."""
    return {"provider": "deepseek", "model": MODEL, "base_url": BASE_URL,
            "key": "PRESENT" if key_present() else "ABSENT"}


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
