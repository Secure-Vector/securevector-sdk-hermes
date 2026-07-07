"""Adapter configuration — explicit kwargs override environment overrides
defaults.

Environment variables (all optional):
    SECUREVECTOR_ENGINE_ENDPOINT    local app / engine base URL — the unified
                                    variable shared with the native-hook
                                    plugins (default http://127.0.0.1:8741)
    SECUREVECTOR_SDK_APP_URL        legacy alias for the base URL, kept for
                                    parity with the sibling framework SDKs;
                                    SECUREVECTOR_ENGINE_ENDPOINT wins when
                                    both are set
    SECUREVECTOR_SDK_MODE           observe | enforce          (default observe)
    SECUREVECTOR_SDK_TIMEOUT_MS     per-call verdict timeout   (default 3000)
    SECUREVECTOR_SDK_RISK_THRESHOLD enforce-block risk cutoff  (default 70)
    SECUREVECTOR_SDK_AGENT_ID        agent id for Cost Tracking attribution
                                    (default "hermes-agent")
    SECUREVECTOR_SDK_DISABLED       set truthy to no-op entirely
    SECUREVECTOR_API_KEY            credential forwarded to the app as
                                    Authorization: Bearer — required when the
                                    app is a remote, token-gated deployment
                                    (e.g. the Terraform self-host modules);
                                    unused for the default loopback app

Note: we deliberately do not read the existing SECUREVECTOR_URL — that points
at the *cloud* API in the rest of the ecosystem, whereas the SDK talks to the
*local* app.
"""

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://127.0.0.1:8741"


def _truthy(val: str) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _base_url_from_env() -> str:
    return (
        os.environ.get("SECUREVECTOR_ENGINE_ENDPOINT")
        or os.environ.get("SECUREVECTOR_SDK_APP_URL")
        or DEFAULT_BASE_URL
    )


@dataclass
class Config:
    base_url: str = DEFAULT_BASE_URL
    mode: str = "observe"            # observe (fail-open) | enforce (fail-closed)
    timeout_ms: int = 3000
    threat_risk_threshold: int = 70  # risk_score >= this blocks in enforce mode
    agent_id: str = ""               # Cost Tracking attribution ("" → "hermes-agent")
    enabled: bool = True
    api_key: str = ""                # forwarded as Authorization: Bearer to the app

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls(
            base_url=_base_url_from_env(),
            mode=os.environ.get("SECUREVECTOR_SDK_MODE", "observe").strip().lower(),
            timeout_ms=int(os.environ.get("SECUREVECTOR_SDK_TIMEOUT_MS", "3000")),
            threat_risk_threshold=int(
                os.environ.get("SECUREVECTOR_SDK_RISK_THRESHOLD", "70")
            ),
            agent_id=os.environ.get("SECUREVECTOR_SDK_AGENT_ID", ""),
            enabled=not _truthy(os.environ.get("SECUREVECTOR_SDK_DISABLED", "")),
            api_key=os.environ.get("SECUREVECTOR_API_KEY", ""),
        )
        # Explicit kwargs win over env, but only when actually provided.
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        if cfg.mode not in ("observe", "enforce"):
            cfg.mode = "observe"
        return cfg
