"""SecureVector SDK for Hermes (NousResearch ``hermes-agent``).

Zero-config (recommended) — the Hermes plugin manager auto-loads this
package's ``hermes_agent.plugins`` entry point on startup::

    pip install securevector-sdk-hermes
    # then just run `hermes` (or the gateway) as usual.
    # Enforcement: export SECUREVECTOR_SDK_MODE=enforce

Programmatic / library embeddings (no plugin manager)::

    from securevector_sdk_hermes import install
    install(mode="enforce")   # wraps Hermes's tool registry dispatch

Either way, every Hermes tool call — built-ins, MCP tools
(``mcp_<server>_<tool>``), plugin tools — runs the local SecureVector app's
three controls: tool-call permissions, secret/data-leak detection, and threat
detection. Each decision is written to the app's tamper-evident audit chain
with ``runtime_kind="hermes"``. Requires the SecureVector app running locally
(installed automatically as the ``securevector-ai-monitor`` dependency).
"""

import logging

from ._version import __version__
from .config import Config
from .errors import AppUnreachable, SecureVectorError, ToolBlocked
from .plugin import install, register
from .tool_id import HERMES_BUILTINS, RUNTIME_KIND, candidate_tool_ids

log = logging.getLogger("securevector_sdk_hermes")

__all__ = [
    "__version__",
    "install",
    "register",
    "Config",
    "RUNTIME_KIND",
    "HERMES_BUILTINS",
    "candidate_tool_ids",
    "SecureVectorError",
    "ToolBlocked",
    "AppUnreachable",
]
