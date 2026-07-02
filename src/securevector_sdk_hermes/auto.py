"""``import securevector_sdk_hermes.auto`` — one-line programmatic attach.

Under the Hermes CLI / gateway this module is unnecessary: the package's
``hermes_agent.plugins`` entry point attaches the guard automatically at
startup. ``auto`` exists for library embeddings (driving ``AIAgent`` from your
own Python process) where the plugin manager never runs::

    import securevector_sdk_hermes.auto  # noqa: F401

Mode comes from ``SECUREVECTOR_SDK_MODE`` (default ``observe``). Best-effort:
when hermes-agent is not importable this logs a warning instead of raising, so
a stray import never breaks a process.
"""

import logging
import os

from .plugin import install

log = logging.getLogger("securevector_sdk_hermes")

try:
    install(mode=os.environ.get("SECUREVECTOR_SDK_MODE", "observe").strip().lower())
except ImportError as exc:  # pragma: no cover - depends on hermes install
    log.warning(
        "SecureVector auto-attach skipped (%s). Under the hermes CLI the "
        "entry-point plugin attaches automatically; for library use, call "
        "securevector_sdk_hermes.install() after hermes-agent is importable.",
        exc,
    )
