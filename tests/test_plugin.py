"""The Hermes attach points, driven with fakes (no hermes-agent install):

* register(ctx) wires pre_tool_call / post_tool_call;
* pre_tool_call returns Hermes's block directive only on an enforce-mode deny,
  with the branded reason;
* the guard fails open when the interceptor explodes;
* the dispatch wrap short-circuits with the registry error shape and is
  idempotent.
"""

import json

import securevector_sdk_hermes.plugin as plugin_mod
from securevector_sdk_hermes.core import Decision
from securevector_sdk_hermes.plugin import _HermesGuard, _wrap_dispatch


class FakeInterceptor:
    def __init__(self, decision=None, raises=False):
        self.decision = decision or Decision(False, "allow", "ok", "low")
        self.raises = raises
        self.eval_calls = []
        self.scan_calls = []

    def evaluate_input(self, tool_id, args_text, *, session_id=None, request_id=None):
        if self.raises:
            raise RuntimeError("boom")
        self.eval_calls.append((tool_id, args_text, session_id, request_id))
        return self.decision

    def scan_output(self, tool_id, output_text, *, session_id=None, request_id=None):
        if self.raises:
            raise RuntimeError("boom")
        self.scan_calls.append((tool_id, output_text, session_id, request_id))


class FakeCtx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, cb):
        self.hooks[name] = cb


# --------------------------- hook behaviour ----------------------------- #

def test_allow_returns_none_and_audited_via_interceptor():
    guard = _HermesGuard(FakeInterceptor())
    out = guard.pre_tool_call(
        tool_name="terminal", args={"cmd": "ls"},
        session_id="s1", tool_call_id="c1",
    )
    assert out is None
    (tool_id, args_text, session, req) = guard.interceptor.eval_calls[0]
    assert tool_id == "terminal"
    assert "ls" in args_text
    assert session == "s1"
    assert req == "c1"


def test_block_returns_hermes_directive_with_branded_reason():
    guard = _HermesGuard(FakeInterceptor(Decision(True, "block", "Synced policy 'corp': block", "synced")))
    out = guard.pre_tool_call(tool_name="terminal", args={})
    assert out == {
        "action": "block",
        "message": "SecureVector Guard: tool 'terminal' blocked — Synced policy 'corp': block",
    }


def test_observe_deny_does_not_block():
    # Decision.blocked already encodes mode; observe mode never sets it.
    guard = _HermesGuard(FakeInterceptor(Decision(False, "block", "policy", "high")))
    assert guard.pre_tool_call(tool_name="terminal", args={}) is None


def test_guard_fails_open_on_internal_error():
    guard = _HermesGuard(FakeInterceptor(raises=True))
    assert guard.pre_tool_call(tool_name="terminal", args={}) is None
    guard.post_tool_call(tool_name="terminal", result="x")  # must not raise


def test_post_tool_call_scans_result():
    guard = _HermesGuard(FakeInterceptor())
    guard.post_tool_call(tool_name="web_search", result={"data": "AKIA..."}, session_id="s1")
    (tool_id, text, session, _req) = guard.interceptor.scan_calls[0]
    assert tool_id == "web_search"
    assert "AKIA" in text
    assert session == "s1"


def test_unknown_future_kwargs_are_tolerated():
    guard = _HermesGuard(FakeInterceptor())
    assert guard.pre_tool_call(tool_name="terminal", args={}, some_future_field=1) is None
    guard.post_tool_call(tool_name="terminal", result="", some_future_field=1)


def test_register_wires_both_hooks(monkeypatch):
    monkeypatch.delenv("SECUREVECTOR_SDK_DISABLED", raising=False)
    ctx = FakeCtx()
    plugin_mod.register(ctx)
    # tool-guard hooks plus the cost-tracking hooks (post_api_request per API
    # call, post_llm_call per turn — same callable, tracker dedupes).
    assert set(ctx.hooks) == {
        "pre_tool_call", "post_tool_call", "post_api_request", "post_llm_call",
    }


def test_register_respects_disabled(monkeypatch):
    monkeypatch.setenv("SECUREVECTOR_SDK_DISABLED", "1")
    ctx = FakeCtx()
    plugin_mod.register(ctx)
    assert ctx.hooks == {}


# --------------------------- dispatch wrap ------------------------------ #

class FakeRegistry:
    def __init__(self):
        self.calls = []

        def dispatch(name, args, **kwargs):
            self.calls.append((name, args, kwargs))
            return json.dumps({"ok": True})

        self.dispatch = dispatch


def test_wrap_dispatch_blocks_with_registry_error_shape():
    reg = FakeRegistry()
    _wrap_dispatch(reg, FakeInterceptor(Decision(True, "block", "denied", "synced")))
    out = reg.dispatch("terminal", {"cmd": "rm"}, session_id="s1")
    assert reg.calls == []  # inner tool never ran
    assert json.loads(out)["error"].startswith("SecureVector Guard: tool 'terminal' blocked")


def test_wrap_dispatch_allows_and_scans_output():
    reg = FakeRegistry()
    fake = FakeInterceptor()
    _wrap_dispatch(reg, fake)
    out = reg.dispatch("web_search", {"q": "x"}, session_id="s2")
    assert json.loads(out) == {"ok": True}
    assert fake.eval_calls[0][0] == "web_search"
    assert fake.scan_calls[0][0] == "web_search"
    assert fake.eval_calls[0][2] == "s2"


def test_wrap_dispatch_fails_open_on_guard_error():
    reg = FakeRegistry()
    _wrap_dispatch(reg, FakeInterceptor(raises=True))
    out = reg.dispatch("terminal", {"cmd": "ls"})
    assert json.loads(out) == {"ok": True}  # tool still ran


def test_wrap_dispatch_is_idempotent():
    reg = FakeRegistry()
    fake = FakeInterceptor()
    _wrap_dispatch(reg, fake)
    once = reg.dispatch
    _wrap_dispatch(reg, fake)
    assert reg.dispatch is once
    reg.dispatch("terminal", {})
    assert len(fake.eval_calls) == 1  # evaluated once, not twice
