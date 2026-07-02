"""RUNTIME_KIND, normalize fallbacks, and the MCP candidate expansion."""

from securevector_sdk_hermes.tool_id import (
    HERMES_BUILTINS,
    RUNTIME_KIND,
    candidate_tool_ids,
    normalize_tool_id,
)


def test_runtime_kind():
    assert RUNTIME_KIND == "hermes"


def test_flat_name_passthrough_preserves_casing():
    assert normalize_tool_id("Terminal") == "Terminal"


def test_dict_payload_tool_name_key():
    assert normalize_tool_id({"tool_name": "web_search"}) == "web_search"


def test_dict_payload_name_key():
    assert normalize_tool_id({"name": "write_file"}) == "write_file"


def test_flat_kwarg_fallback():
    assert normalize_tool_id(None, name="terminal") == "terminal"


def test_all_missing_is_unknown():
    assert normalize_tool_id(None) == "unknown"
    assert normalize_tool_id({}) == "unknown"
    assert normalize_tool_id("   ") == "unknown"


def test_builtin_candidates_are_just_the_name():
    assert candidate_tool_ids("terminal") == ["terminal"]


def test_mcp_candidates_emit_every_server_tool_split():
    cands = candidate_tool_ids("mcp_my_api_list_items")
    assert cands[0] == "mcp_my_api_list_items"  # raw name is most specific
    assert "my:api_list_items" in cands
    assert "my_api:list_items" in cands
    assert "my_api_list:items" in cands
    assert len(cands) == 4


def test_mcp_single_segment_has_no_split():
    assert candidate_tool_ids("mcp_solo") == ["mcp_solo"]


def test_builtins_table_covers_the_dispatch_surface():
    # Spot-check the empirical 0.18.0 inventory (full drift check lives in
    # test_builtins_drift.py against a live hermes install).
    for tool in ("terminal", "execute_code", "write_file", "web_search",
                 "browser_navigate", "delegate_task", "tool_call",
                 "computer_use", "memory"):
        assert tool in HERMES_BUILTINS
    assert len(HERMES_BUILTINS) == len(set(HERMES_BUILTINS))  # no dupes
    assert len(HERMES_BUILTINS) >= 70
