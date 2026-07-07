"""LLM cost tracking — post Hermes model-call token usage to the local app.

The tool hooks secure tool calls but never see the model call, so Hermes
agents were invisible to the app's Cost Tracking. Hermes fires a
``post_api_request`` hook after every provider API call carrying a
pre-normalized ``usage`` dict (Hermes's own ``CanonicalUsage``:
``input_tokens`` / ``output_tokens`` / ``cache_read_tokens`` / …) plus the
``provider`` and ``model``. This module reads that payload and POSTs it to the
app's ``POST /api/costs/track``, which looks up pricing by exact
``"{provider}/{model_id}"`` and computes dollars. Hermes runs on the user's
own API keys, so the dollar cost is real.

Wiring is zero-config: the plugin's :func:`register` (see ``plugin.py``)
registers the cost hooks alongside the tool-guard hooks, so installing the
package is enough. ``post_api_request`` (fires per API call, always carries
``usage``) is primary; ``post_llm_call`` (fires once per turn, carries
``usage`` on newer Hermes builds) is also registered for version tolerance —
:class:`CostTracker` dedupes so a turn is never double-counted.

Unlike the LangChain SDK we do NOT dig token counts out of message objects:
Hermes hands us clean buckets. The only real work is mapping Hermes's provider
slug + versioned model id onto the app's pricing-table keys.

Everything here is best-effort: an unreachable app, an unknown provider, or an
exotic payload shape never breaks the agent (mirrors the audit fail-soft).
"""

import logging
from typing import Any, Dict, Optional

from .client import LocalAppClient
from .config import Config
from .tool_id import RUNTIME_KIND

log = logging.getLogger("securevector_sdk_hermes")

# Map versioned model ids to the canonical pricing keys the app's pricing
# table uses. Mirrors the app-side cost_recorder MODEL_ID_ALIASES: the
# /api/costs/track lookup is an EXACT "provider/model_id" match with no
# normalization, so the SDK must normalize client-side or records land as
# pricing_known=false. Hermes usually reports canonical ids already; these
# cover the versioned spellings some providers/routers return.
MODEL_ID_ALIASES: Dict[str, str] = {
    # OpenAI versioned → canonical
    "gpt-4o-2024-11-20": "gpt-4o",
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-2024-05-13": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4-turbo-2024-04-09": "gpt-4-turbo",
    "gpt-4-turbo-preview": "gpt-4-turbo",
    "gpt-3.5-turbo-0125": "gpt-3.5-turbo",
    "gpt-3.5-turbo-1106": "gpt-3.5-turbo",
    "o1-2024-12-17": "o1",
    "o1-mini-2024-09-12": "o1-mini",
    "o3-mini-2025-01-31": "o3-mini",
    # Gemini variants → canonical
    "gemini-2.0-flash-001": "gemini-2.0-flash",
    "gemini-2.0-flash-exp": "gemini-2.0-flash",
    "gemini-1.5-pro-001": "gemini-1.5-pro",
    "gemini-1.5-pro-002": "gemini-1.5-pro",
    "gemini-1.5-flash-001": "gemini-1.5-flash",
    "gemini-1.5-flash-002": "gemini-1.5-flash",
    # Mistral versioned
    "mistral-large-2402": "mistral-large-latest",
    "mistral-large-2407": "mistral-large-latest",
    "mistral-large-2411": "mistral-large-latest",
    "mistral-small-2402": "mistral-small-latest",
    "mistral-small-2409": "mistral-small-latest",
    # Cohere versioned
    "command-r-plus": "command-r-plus-08-2024",
    "command-r": "command-r-08-2024",
}

# Hermes provider slug → the app pricing table's provider key. The app seeds
# (model_pricing.yml): openai / anthropic / gemini / grok / groq / mistral /
# cohere / deepseek / perplexity / minimax / ollama. Note grok (xAI models) is
# distinct from groq (the inference host) — Hermes's ``xai`` maps to ``grok``.
# Unmapped providers pass through unchanged (recorded at $0, pricing_known=false).
_PROVIDER_CANON: Dict[str, str] = {
    "openai": "openai",
    "openai-codex": "openai",   # Codex runtime is OpenAI-billed
    "azure": "openai",
    "azure_openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "google": "gemini",
    "google_genai": "gemini",
    "google_vertexai": "gemini",
    "vertex_ai": "gemini",
    "vertexai": "gemini",
    "groq": "groq",
    "xai": "grok",              # xAI provider → grok pricing rows
    "grok": "grok",
    "mistral": "mistral",
    "mistralai": "mistral",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "perplexity": "perplexity",
    "minimax": "minimax",
    "ollama": "ollama",
}


def canon_provider(raw: Any) -> str:
    """Map a Hermes provider slug onto the app's pricing provider key.
    Unknown slugs pass through lowercased (still recorded, just unpriced)."""
    slug = str(raw or "").strip().lower()
    if not slug:
        return "unknown"
    return _PROVIDER_CANON.get(slug, slug)


def canon_model_id(raw: Any) -> str:
    """Strip a leading ``provider/`` prefix (litellm style) when the prefix is
    a recognized provider, then apply the canonical-pricing aliases. An
    unrecognized prefix is left intact rather than guessed at."""
    mid = str(raw or "").strip()
    if "/" in mid:
        prefix, rest = mid.split("/", 1)
        if prefix.lower() in _PROVIDER_CANON:
            mid = rest.strip()
    return MODEL_ID_ALIASES.get(mid, mid)


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _to_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def extract_usage(usage: Any) -> Optional[Dict[str, int]]:
    """Pull ``{input, output, cached}`` counts from Hermes's ``usage`` payload.

    Hermes's ``post_api_request`` ``usage`` is a ``CanonicalUsage`` dict
    (``input_tokens`` / ``output_tokens`` / ``cache_read_tokens``); an
    OpenAI-shaped ``prompt_tokens`` / ``completion_tokens`` fallback is also
    accepted for tolerance. None when there is no real usage.
    """
    if not usage:
        return None
    input_tokens = _to_int(_field(usage, "input_tokens"))
    output_tokens = _to_int(_field(usage, "output_tokens"))
    if input_tokens == 0 and output_tokens == 0:
        # OpenAI-style fallback keys.
        input_tokens = _to_int(_field(usage, "prompt_tokens"))
        output_tokens = _to_int(_field(usage, "completion_tokens"))
    if input_tokens == 0 and output_tokens == 0:
        return None
    cached = _to_int(_field(usage, "cache_read_tokens"))
    if cached == 0:
        details = _field(usage, "input_token_details") or {}
        cached = _to_int(_field(details, "cache_read") or _field(details, "cached_tokens"))
    return {"input": input_tokens, "output": output_tokens, "cached": cached}


class CostTracker:
    """Extracts usage from a Hermes hook payload and posts it, tagged by agent.

    ``agent_id`` groups records in the app's Cost Tracking dashboard; the
    default is a stable per-runtime id so all Hermes agents roll up together
    unless the user names theirs (``SECUREVECTOR_SDK_AGENT_ID`` / kwarg).

    A short ring of recently-seen ``api_request_id`` values dedupes the case
    where both ``post_api_request`` and ``post_llm_call`` fire for the same
    call on Hermes builds that emit usage on both.
    """

    _DEDUPE_CAP = 256

    def __init__(
        self,
        cfg: Config,
        client: Optional[LocalAppClient] = None,
        agent_id: Optional[str] = None,
    ):
        self.cfg = cfg
        self.client = client or LocalAppClient(cfg)
        self.agent_id = agent_id or cfg.agent_id or f"{RUNTIME_KIND}-agent"
        self._seen: "dict[str, None]" = {}

    def _already_recorded(self, key: str) -> bool:
        if not key:
            return False
        if key in self._seen:
            return True
        self._seen[key] = None
        if len(self._seen) > self._DEDUPE_CAP:
            # Drop the oldest ~half (dicts preserve insertion order).
            for old in list(self._seen)[: self._DEDUPE_CAP // 2]:
                self._seen.pop(old, None)
        return False

    def record_hook(self, **payload: Any) -> bool:
        """Record one ``post_api_request`` / ``post_llm_call`` firing. Returns
        True when a cost record was posted. Never raises."""
        if not self.cfg.enabled:
            return False
        try:
            usage = extract_usage(payload.get("usage"))
            if usage is None:
                return False
            dedupe_key = str(
                payload.get("api_request_id")
                or payload.get("turn_id")
                or ""
            )
            if self._already_recorded(dedupe_key):
                return False
            provider = canon_provider(payload.get("provider"))
            model_id = canon_model_id(
                payload.get("response_model") or payload.get("model")
            )
            if not model_id:
                return False
            return bool(self.client.record_cost(
                agent_id=self.agent_id,
                provider=provider,
                model_id=model_id,
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                input_cached_tokens=usage["cached"],
            ))
        except Exception as exc:  # never let cost tracking break the agent
            log.debug("cost tracking failed: %s", exc)
            return False


def make_cost_hook(tracker: CostTracker):
    """Build the keyword-only callable Hermes invokes for the cost hooks.

    Hermes calls hooks with keyword arguments; accept ``**kwargs`` so new
    Hermes payload fields never break the hook (fail-open contract). Returns
    None (a non-blocking observer; only ``pre_*`` hooks may return a block).
    """

    def _securevector_cost(**kwargs: Any) -> None:
        tracker.record_hook(**kwargs)

    return _securevector_cost
