"""Cost tracking: usage extraction from Hermes's post_api_request payload,
provider/model normalization onto the app pricing keys, the /api/costs/track
POST, dedupe across post_api_request+post_llm_call, and fail-soft behaviour.

No hermes-agent install required — the hook payload is reproduced as a dict.
"""

import securevector_sdk_hermes.plugin as plugin_mod
from securevector_sdk_hermes.client import LocalAppClient
from securevector_sdk_hermes.config import Config
from securevector_sdk_hermes.costs import (
    CostTracker,
    canon_model_id,
    canon_provider,
    extract_usage,
    make_cost_hook,
)


class CaptureClient:
    def __init__(self):
        self.costs = []

    def record_cost(self, **kwargs):
        self.costs.append(kwargs)
        return True


# Hermes CanonicalUsage dict, as ``post_api_request`` delivers it.
USAGE = {
    "input_tokens": 5300,
    "output_tokens": 870,
    "cache_read_tokens": 4000,
    "cache_write_tokens": 0,
    "prompt_tokens": 9300,
    "total_tokens": 10170,
}


def _payload(**over):
    p = {
        "session_id": "s1",
        "task_id": "t1",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "response_model": "claude-sonnet-4-6",
        "usage": dict(USAGE),
        "api_request_id": "req-1",
    }
    p.update(over)
    return p


class FakeCtx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, cb):
        self.hooks[name] = cb


# --------------------------------------------------------------------- #
# client.record_cost                                                    #
# --------------------------------------------------------------------- #
def test_record_cost_posts_contract_payload():
    c = LocalAppClient(Config())
    seen = {}

    def fake_post(path, body):
        seen["path"], seen["body"] = path, body
        return {"status": "recorded"}

    c._post = fake_post
    c.record_cost(
        agent_id="my-agent",
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        input_tokens=5300,
        output_tokens=870,
        input_cached_tokens=4000,
    )
    assert seen["path"] == "/api/costs/track"
    assert seen["body"] == {
        "agent_id": "my-agent",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "input_tokens": 5300,
        "output_tokens": 870,
        "input_cached_tokens": 4000,
    }


def test_record_cost_defaults_agent_id_and_clamps_negatives():
    c = LocalAppClient(Config())
    seen = {}
    c._post = lambda path, body: seen.update(body)
    c.record_cost(
        agent_id=None, provider="openai", model_id="gpt-4o",
        input_tokens=-5, output_tokens=10,
    )
    assert seen["agent_id"] == "hermes-agent"
    assert seen["input_tokens"] == 0
    assert seen["input_cached_tokens"] == 0


def test_record_cost_fail_soft_when_app_unreachable():
    c = LocalAppClient(Config(base_url="http://127.0.0.1:1"))

    def boom(path, body):
        raise OSError("connection refused")

    c._post = boom
    # Must not raise and reports failure — cost tracking never breaks the agent.
    assert c.record_cost(agent_id="a", provider="openai", model_id="gpt-4o",
                         input_tokens=1, output_tokens=1) is False


# --------------------------------------------------------------------- #
# extraction + normalization                                            #
# --------------------------------------------------------------------- #
def test_extract_usage_reads_canonical_buckets():
    assert extract_usage(USAGE) == {"input": 5300, "output": 870, "cached": 4000}


def test_extract_usage_openai_style_fallback():
    usage = {"prompt_tokens": 100, "completion_tokens": 20,
             "input_token_details": {"cached_tokens": 40}}
    assert extract_usage(usage) == {"input": 100, "output": 20, "cached": 40}


def test_extract_usage_none_without_usage_or_tokens():
    assert extract_usage(None) is None
    assert extract_usage({}) is None
    assert extract_usage({"input_tokens": 0, "output_tokens": 0}) is None


def test_canon_provider_maps_hermes_slugs():
    assert canon_provider("anthropic") == "anthropic"
    assert canon_provider("openai-codex") == "openai"
    assert canon_provider("google_genai") == "gemini"
    assert canon_provider("xai") == "grok"        # xAI models priced under 'grok'
    assert canon_provider("groq") == "groq"       # distinct from grok
    assert canon_provider("totally-unknown") == "totally-unknown"  # passthrough
    assert canon_provider("") == "unknown"


def test_canon_model_id_strips_prefix_and_aliases():
    assert canon_model_id("gpt-4o-2024-08-06") == "gpt-4o"
    assert canon_model_id("openai/gpt-4o-2024-11-20") == "gpt-4o"
    assert canon_model_id("mistralai/mistral-large-2411") == "mistral-large-latest"
    assert canon_model_id("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"
    # an unrecognized prefix is left intact (not guessed at)
    assert canon_model_id("openrouter/foo-model") == "openrouter/foo-model"
    assert canon_model_id(None) == ""


# --------------------------------------------------------------------- #
# CostTracker.record_hook                                               #
# --------------------------------------------------------------------- #
def test_tracker_records_from_post_api_request_payload():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    assert tracker.record_hook(**_payload()) is True
    assert client.costs == [{
        "agent_id": "hermes-agent",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "input_tokens": 5300,
        "output_tokens": 870,
        "input_cached_tokens": 4000,
    }]


def test_tracker_prefers_response_model_and_normalizes_provider():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    tracker.record_hook(**_payload(
        provider="xai", model="grok-4", response_model="grok-4-2025-01-01",
    ))
    assert client.costs[0]["provider"] == "grok"
    assert client.costs[0]["model_id"] == "grok-4-2025-01-01"


def test_tracker_dedupes_across_both_hooks():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    # post_api_request then post_llm_call for the same API call.
    assert tracker.record_hook(**_payload(api_request_id="req-9")) is True
    assert tracker.record_hook(**_payload(api_request_id="req-9")) is False
    assert len(client.costs) == 1
    # a different call still records.
    assert tracker.record_hook(**_payload(api_request_id="req-10")) is True
    assert len(client.costs) == 2


def test_tracker_no_dedupe_key_records_each():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    tracker.record_hook(**_payload(api_request_id="", turn_id=""))
    tracker.record_hook(**_payload(api_request_id="", turn_id=""))
    assert len(client.costs) == 2


def test_tracker_skips_without_usage_or_model():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    assert tracker.record_hook(**_payload(usage=None)) is False
    assert tracker.record_hook(**_payload(model="", response_model="")) is False
    assert client.costs == []


def test_tracker_disabled_config_posts_nothing():
    client = CaptureClient()
    tracker = CostTracker(Config(enabled=False), client=client)
    assert tracker.record_hook(**_payload()) is False
    assert client.costs == []


def test_tracker_agent_id_precedence():
    client = CaptureClient()
    CostTracker(Config(agent_id="from-config"), client=client).record_hook(**_payload())
    CostTracker(Config(agent_id="from-config"), client=client,
                agent_id="explicit").record_hook(**_payload())
    assert [c["agent_id"] for c in client.costs] == ["from-config", "explicit"]


def test_tracker_never_raises_on_client_failure():
    class BoomClient:
        def record_cost(self, **kwargs):
            raise RuntimeError("boom")

    tracker = CostTracker(Config(), client=BoomClient())
    assert tracker.record_hook(**_payload()) is False


def test_env_agent_id(monkeypatch):
    monkeypatch.setenv("SECUREVECTOR_SDK_AGENT_ID", "env-agent")
    cfg = Config.from_env()
    client = CaptureClient()
    CostTracker(cfg, client=client).record_hook(**_payload())
    assert client.costs[0]["agent_id"] == "env-agent"


# --------------------------------------------------------------------- #
# make_cost_hook + register wiring                                      #
# --------------------------------------------------------------------- #
def test_cost_hook_records_and_returns_none():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    hook = make_cost_hook(tracker)
    assert hook(**_payload()) is None  # observer — never blocks
    assert len(client.costs) == 1


def test_register_wires_cost_hooks(monkeypatch):
    # Config with app disabled? No — enabled default; use a capturing client by
    # patching LocalAppClient so no real network call happens on construction.
    ctx = FakeCtx()
    plugin_mod.register(ctx)
    assert "post_api_request" in ctx.hooks
    assert "post_llm_call" in ctx.hooks
    assert "pre_tool_call" in ctx.hooks
    assert "post_tool_call" in ctx.hooks
    # both cost hook names share one callable
    assert ctx.hooks["post_api_request"] is ctx.hooks["post_llm_call"]
