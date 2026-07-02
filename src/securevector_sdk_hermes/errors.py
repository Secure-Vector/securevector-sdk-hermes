"""Exceptions raised by the SecureVector Hermes adapter.

``ToolBlocked`` is available for callers using ``Interceptor.guard_input``
directly; the shipped Hermes attach paths never raise into the agent loop —
the plugin hook blocks via Hermes's own block directive and the ``install()``
dispatch wrap returns a registry-style error string. In ``observe`` mode
nothing is ever blocked — every call is logged and allowed through.
"""


class SecureVectorError(Exception):
    """Base class for all adapter errors."""


class ToolBlocked(SecureVectorError):
    """Raised in enforce mode to abort a tool call (policy block, input threat,
    or fail-closed when the local app is unreachable)."""

    def __init__(self, tool_id: str, reason: str):
        self.tool_id = tool_id
        self.reason = reason
        super().__init__(f"SecureVector blocked tool '{tool_id}': {reason}")


class AppUnreachable(SecureVectorError):
    """The local SecureVector app could not be reached. Mode decides the
    consequence: observe → allow (fail-open); enforce → deny (fail-closed)."""
