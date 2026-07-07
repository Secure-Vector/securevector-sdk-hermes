"""Hermes attach points — the plugin hooks (primary) and ``install()`` (fallback).

**1. Hermes plugin — zero-config, the primary path.** This package declares a
``hermes_agent.plugins`` entry point targeting this module; the Hermes plugin
manager auto-discovers it on startup (CLI, gateway, and ACP modes all share
the loader) and calls :func:`register`. The ``pre_tool_call`` hook is Hermes's
documented enforcement surface: returning
``{"action": "block", "message": ...}`` stops the tool before it runs, in
every mode — including the gateway/headless contexts where Hermes's own
dangerous-command approval is known to fail open (upstream #30882). The
``post_tool_call`` hook scans the tool result (observe-only; the tool already
ran).

**2. ``install()`` — programmatic embeddings.** When Hermes is driven as a
library (no plugin manager), ``install(mode="enforce")`` wraps
``tools.registry.registry.dispatch`` — the bottom-of-the-funnel choke point
that every execution path funnels through. We deliberately do NOT patch
``model_tools.handle_function_call``: ``run_agent`` re-imports it by
reference, so a patch there misses ``AIAgent._invoke_tool``. A blocked call
returns the registry's own ``{"error": ...}`` JSON shape, so the model sees a
clean tool error, not a crashed run.

Both paths fail open **within our control**: any adapter exception → the tool
call proceeds (and the failure is logged). Whether a *policy decision* fails
open is the mode's job: ``observe`` never blocks; ``enforce`` blocks on deny
and fails closed when the app is unreachable.
"""

import json
import logging
import sys
import uuid
from typing import Any, Optional

from .config import Config
from .core import Decision, Interceptor
from .costs import CostTracker, make_cost_hook
from .tool_id import normalize_tool_id

log = logging.getLogger("securevector_sdk_hermes")

_BRAND = "SecureVector Guard"
_COLD_INSTALL_NOTICE = (
    f"[{_BRAND}] Local SecureVector app not reachable — tool calls are allowed "
    "but not governed. Install & start the free SecureVector app to activate: "
    "pip install securevector-ai-monitor && securevector-monitor\n"
)

_notified_unreachable = False


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


def _notice_once(decision: Decision) -> None:
    """One-line cold-install / app-down notice, once per process."""
    global _notified_unreachable
    if decision.risk == "unreachable" and not _notified_unreachable:
        _notified_unreachable = True
        sys.stderr.write(_COLD_INSTALL_NOTICE)


def _request_id(tool_call_id: str, api_request_id: str) -> str:
    return (tool_call_id or api_request_id or uuid.uuid4().hex)[:64]


def _block_message(tool_id: str, reason: str) -> str:
    return f"{_BRAND}: tool '{tool_id}' blocked — {reason}"


class _HermesGuard:
    """The hook callbacks, bound to one Interceptor (one mode/config)."""

    def __init__(self, interceptor: Interceptor):
        self.interceptor = interceptor

    # Hermes invokes hooks with keyword arguments; accept **kwargs so future
    # Hermes versions adding fields never break the guard (fail-open contract).
    def pre_tool_call(
        self,
        tool_name: str = "",
        args: Optional[dict] = None,
        session_id: str = "",
        tool_call_id: str = "",
        api_request_id: str = "",
        **kwargs: Any,
    ) -> Optional[dict]:
        try:
            tool_id = normalize_tool_id(tool_name)
            decision = self.interceptor.evaluate_input(
                tool_id,
                _to_text(args),
                session_id=session_id or None,
                request_id=_request_id(tool_call_id, api_request_id),
            )
            _notice_once(decision)
            if decision.blocked:
                return {
                    "action": "block",
                    "message": _block_message(tool_id, decision.reason),
                }
        except Exception as exc:  # fail-open: never break the agent loop
            log.warning("pre_tool_call guard error (allowing call): %s", exc)
        return None

    def post_tool_call(
        self,
        tool_name: str = "",
        result: Any = None,
        session_id: str = "",
        tool_call_id: str = "",
        api_request_id: str = "",
        **kwargs: Any,
    ) -> None:
        try:
            self.interceptor.scan_output(
                normalize_tool_id(tool_name),
                _to_text(result),
                session_id=session_id or None,
                request_id=_request_id(tool_call_id, api_request_id),
            )
        except Exception as exc:  # observer only — never raises into Hermes
            log.debug("post_tool_call guard error: %s", exc)


def register(ctx) -> None:
    """Entry point called by the Hermes plugin manager (``register(ctx)``).

    Mode comes from the environment (``SECUREVECTOR_SDK_MODE``, default
    ``observe``) — a plugin has no per-user kwargs. Set
    ``SECUREVECTOR_SDK_DISABLED=1`` to no-op without uninstalling.
    """
    cfg = Config.from_env()
    if not cfg.enabled:
        log.info("SecureVector guard disabled via SECUREVECTOR_SDK_DISABLED")
        return
    guard = _HermesGuard(Interceptor(cfg))
    ctx.register_hook("pre_tool_call", guard.pre_tool_call)
    ctx.register_hook("post_tool_call", guard.post_tool_call)

    # Cost tracking — post LLM token usage to the app's Cost Tracking. Hermes
    # fires post_api_request per API call (always carries usage) and
    # post_llm_call once per turn (carries usage on newer builds); the tracker
    # dedupes so a call is never double-counted. Observer-only — never blocks.
    cost_hook = make_cost_hook(CostTracker(cfg))
    ctx.register_hook("post_api_request", cost_hook)
    ctx.register_hook("post_llm_call", cost_hook)
    log.info("SecureVector guard attached to Hermes (mode=%s)", cfg.mode)


# ---------------------------------------------------------------------- #
# install() — dispatch wrap for programmatic / library embeddings        #
# ---------------------------------------------------------------------- #
_WRAPPED_FLAG = "_securevector_wrapped"


def _wrap_dispatch(registry, interceptor: Interceptor):
    """Wrap ``registry.dispatch`` on the singleton instance (idempotent)."""
    if getattr(registry.dispatch, _WRAPPED_FLAG, False):
        return registry.dispatch
    inner = registry.dispatch

    def dispatch(name: str, args: dict, **kwargs) -> str:
        req = uuid.uuid4().hex[:16]
        session = str(kwargs.get("session_id") or "") or None
        try:
            tool_id = normalize_tool_id(name)
            decision = interceptor.evaluate_input(
                tool_id, _to_text(args), session_id=session, request_id=req
            )
            _notice_once(decision)
            if decision.blocked:
                # The registry's own error shape — the model sees a clean
                # tool error instead of an exception unwinding the loop.
                return json.dumps({"error": _block_message(tool_id, decision.reason)})
        except Exception as exc:  # fail-open
            log.warning("dispatch guard error (allowing call): %s", exc)
        result = inner(name, args, **kwargs)
        try:
            interceptor.scan_output(
                normalize_tool_id(name), _to_text(result),
                session_id=session, request_id=req,
            )
        except Exception as exc:
            log.debug("dispatch output scan error: %s", exc)
        return result

    setattr(dispatch, _WRAPPED_FLAG, True)
    registry.dispatch = dispatch
    return dispatch


def install(mode: str = "observe", base_url: Optional[str] = None, **kwargs) -> None:
    """Attach the guard to an in-process Hermes without the plugin manager.

    Wraps ``tools.registry.registry.dispatch`` so every tool execution —
    interactive CLI, gateway, ACP, subagent — passes through the three
    controls. Idempotent. Raises ``ImportError`` when hermes-agent is not
    installed (nothing to guard).
    """
    try:
        from tools.registry import registry
    except Exception as exc:  # pragma: no cover - depends on hermes install
        raise ImportError(
            "install() requires hermes-agent (tools.registry) to be importable. "
            "When running the hermes CLI/gateway, the entry-point plugin "
            "attaches automatically instead — no install() call needed."
        ) from exc

    cfg = Config.from_env(mode=mode, base_url=base_url, **kwargs)
    if not cfg.enabled:
        log.info("SecureVector guard disabled via SECUREVECTOR_SDK_DISABLED")
        return
    _wrap_dispatch(registry, Interceptor(cfg))
    log.info("SecureVector guard wrapped Hermes registry.dispatch (mode=%s)", cfg.mode)
