"""Canonical tool-id normalization — the ONLY framework-specific mapping.

The whole SecureVector fleet keys permissions and audit on a single canonical
``tool_id``. Hermes (NousResearch ``hermes-agent``) dispatches every tool call
through ``model_tools.handle_function_call`` with a flat function name:

* built-in tools keep their registry name (``terminal``, ``write_file``, …);
* MCP tools are registered as ``mcp_<server>_<tool>`` where BOTH components
  are sanitized — hyphens and dots become underscores (a server ``my-api``
  with tool ``list-items.v2`` becomes ``mcp_my_api_list_items_v2``).

The sanitization is lossy, so a single MCP function name cannot be split back
into ``server``/``tool`` unambiguously. ``candidate_tool_ids`` therefore emits
every plausible ``<server>:<tool>`` split (most-specific first) so rules
authored against the cloud ``<server>:<tool>`` form, the bare tool name, or
the raw Hermes function name all match. The local app aliases
``<server>:<tool>`` and the bare tool suffix server-side and matches
case-insensitively; casing is preserved here.

``HERMES_BUILTINS`` is the empirical built-in inventory, extracted from the
``hermes-agent`` 0.18.0 sdist (AST scan of ``tools/*.py`` ``registry.register``
calls, plus the Tool-Search bridge tools and the bundled first-party plugin
tools that ship inside the wheel). Re-verify on every Hermes version bump —
``tests/test_builtins_drift.py`` compares this table against a live
``hermes-agent`` install when one is importable.
"""

from typing import Any, List, Optional

# The audit/Bill-of-Tools/OCSF pipeline groups by this attribution tag.
RUNTIME_KIND = "hermes"

_MCP_PREFIX = "mcp_"

# Built-in tools registered by tools/*.py at import time (hermes-agent 0.18.0).
_CORE_TOOLS = (
    "browser_back", "browser_cdp", "browser_click", "browser_console",
    "browser_dialog", "browser_get_images", "browser_navigate", "browser_press",
    "browser_scroll", "browser_snapshot", "browser_type", "browser_vision",
    "clarify", "close_terminal", "computer_use", "cronjob", "delegate_task",
    "discord", "discord_admin", "execute_code", "feishu_doc_read",
    "feishu_drive_add_comment", "feishu_drive_list_comment_replies",
    "feishu_drive_list_comments", "feishu_drive_reply_comment",
    "ha_call_service", "ha_get_state", "ha_list_entities", "ha_list_services",
    "image_generate", "kanban_block", "kanban_comment", "kanban_complete",
    "kanban_create", "kanban_heartbeat", "kanban_link", "kanban_list",
    "kanban_show", "kanban_unblock", "memory", "patch", "process",
    "project_create", "project_list", "project_switch", "read_file",
    "read_terminal", "search_files", "session_search", "skill_manage",
    "skill_view", "skills_list", "terminal", "text_to_speech", "todo",
    "video_analyze", "video_generate", "vision_analyze", "web_extract",
    "web_search", "write_file", "x_search", "xai_video_edit",
    "xai_video_extend", "yb_query_group_info", "yb_query_group_members",
    "yb_search_sticker", "yb_send_dm", "yb_send_sticker",
)

# The Tool Search bridge (tools/tool_search.py). handle_function_call unwraps
# tool_call to the real tool before the pre_tool_call hook fires, but the
# bridge names themselves are still dispatchable and belong in the inventory.
_BRIDGE_TOOLS = ("tool_search", "tool_describe", "tool_call")

# First-party plugins bundled inside the hermes-agent wheel (plugins/*):
# registered through the same registry when the operator enables them.
_BUNDLED_PLUGIN_TOOLS = (
    "meet_join", "meet_leave", "meet_say", "meet_status", "meet_transcript",
    "spotify_albums", "spotify_devices", "spotify_library", "spotify_playback",
    "spotify_playlists", "spotify_queue", "spotify_search",
)

HERMES_BUILTINS = _CORE_TOOLS + _BRIDGE_TOOLS + _BUNDLED_PLUGIN_TOOLS


def normalize_tool_id(serialized: Any, name: Optional[str] = None) -> str:
    """Resolve the canonical tool id from a Hermes hook payload.

    Hermes hands hooks a flat ``tool_name`` string, so this mostly passes it
    through; the ``serialized`` dict form is accepted for parity with the
    sibling SDKs (and for callers that forward a raw tool_call dict). Falls
    back to ``"unknown"`` so a missing name never crashes the agent.
    """
    raw: Optional[str] = None
    if isinstance(serialized, str):
        raw = serialized
    elif isinstance(serialized, dict):
        raw = serialized.get("tool_name") or serialized.get("name")
    if not raw:
        raw = name
    if not raw:
        return "unknown"
    return str(raw).strip() or "unknown"


def candidate_tool_ids(tool_id: str) -> List[str]:
    """Expand one Hermes function name into every rule key it should match.

    Ordered most-specific first (the caller resolves tier-first, then takes
    the first candidate that matches within a tier):

    * the raw Hermes name itself (``mcp_my_api_list_items`` or ``terminal``);
    * for MCP names, every ``<server>:<tool>`` split of the sanitized
      remainder — the cloud policy form. The split point is ambiguous after
      sanitization, so all splits are emitted; the app also aliases the bare
      tool suffix of each ``<server>:<tool>`` key server-side.
    """
    tid = normalize_tool_id(tool_id)
    candidates = [tid]
    if tid.lower().startswith(_MCP_PREFIX):
        rest = tid[len(_MCP_PREFIX):]
        parts = rest.split("_")
        for i in range(1, len(parts)):
            server = "_".join(parts[:i])
            tool = "_".join(parts[i:])
            if server and tool:
                candidates.append(f"{server}:{tool}")
    return candidates
