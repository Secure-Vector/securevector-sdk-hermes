# SecureVector SDK for Hermes

[![PyPI](https://img.shields.io/pypi/v/securevector-sdk-hermes)](https://pypi.org/project/securevector-sdk-hermes/)
[![Downloads](https://img.shields.io/pypi/dm/securevector-sdk-hermes)](https://pypistats.org/packages/securevector-sdk-hermes)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/securevector-sdk-hermes/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

> Bring the SecureVector local threat monitor's three controls — **tool-call
> permissions**, **secret / data-leak detection**, and **threat detection** —
> to every Hermes (NousResearch `hermes-agent`) tool call, with tamper-evident
> audit logging. Zero code changes.

```bash
pip install securevector-sdk-hermes
```

> 📦 **One install — batteries included.** `pip install securevector-sdk-hermes`
> **also installs the local SecureVector app** (`securevector-ai-monitor`): the
> adapter **and** the detection engine + tamper-evident audit chain arrive in a
> single `pip install`. The SDK is a thin interception layer — **the app must be
> running locally** (`securevector-app --web`) for it to do anything.

## Quick start

**Zero-config (recommended).** The package registers a Hermes plugin via the
`hermes_agent.plugins` entry point — the Hermes plugin manager auto-loads it
on startup in **every mode**: the interactive `hermes` CLI, `hermes gateway`
(Telegram / Discord / Slack / …), and the ACP/Zed adapter.

```bash
pip install securevector-sdk-hermes
hermes                       # that's it — observe mode is on

export SECUREVECTOR_SDK_MODE=enforce   # opt into blocking
hermes
```

A denied tool is stopped through Hermes's own `pre_tool_call` block directive —
the model sees a clean `SecureVector Guard: tool '<name>' blocked — <reason>`
result. No exceptions, no crashed runs, no fork of Hermes.

**Programmatic / library embeddings** (driving `AIAgent` from your own Python
process, where the plugin manager never runs):

```python
from securevector_sdk_hermes import install

install(mode="enforce")   # wraps Hermes's tool-registry dispatch
```

> Why two paths? The plugin hooks are Hermes's **documented interception
> surface** and require no code at all. `install()` covers embeddings by
> wrapping `tools.registry.dispatch` — the single choke point every Hermes
> execution path (CLI, gateway, ACP, subagents) funnels through.

## What happens on every tool call

Before a tool runs, the SDK:

1. **(a) Permissions** — resolves an allow/block verdict for the tool, using the
   app's own precedence: cloud-pushed **synced** policy → local **override** →
   **essential** registry → default-allow. Hermes MCP tools
   (`mcp_<server>_<tool>`) are matched against the raw Hermes name **and** the
   cloud `<server>:<tool>` form, so policies authored either way apply.
2. **(b)+(c) Secret & threat scan** — sends the serialized tool input through the
   app's `/analyze` pipeline.

After the tool returns, the result is scanned the same way to catch secrets /
exfiltration in tool output. Every decision is written to the app's audit chain
tagged `runtime_kind="hermes"`, keyed by Hermes's own `session_id` and
`tool_call_id`.

This covers all ~70 Hermes built-in tools (`terminal`, `execute_code`,
`write_file`, `browser_*`, …), every MCP tool, and plugin tools — including in
gateway/headless contexts where Hermes's built-in dangerous-command approval
is known to fail open (upstream `hermes-agent` issue #30882): the guard sits
underneath the approval layer, at the dispatch choke point.

## observe vs enforce

| | local app reachable | local app unreachable |
|---|---|---|
| **observe** (default) | log + advisory verdict; tool always runs | tool runs (fail-open, one-line notice) |
| **enforce** (opt-in) | tool runs only if the verdict ≠ block | **tool denied** (fail-closed) |

Enforce mode prints a one-time disclosure to stderr.

## Configuration

All optional, via env (the plugin path) or `install(...)` kwargs:

| Env var | Default | Meaning |
|---|---|---|
| `SECUREVECTOR_ENGINE_ENDPOINT` | `http://127.0.0.1:8741` | local app / engine base URL (unified variable; legacy `SECUREVECTOR_SDK_APP_URL` also honored) |
| `SECUREVECTOR_SDK_MODE` | `observe` | `observe` or `enforce` |
| `SECUREVECTOR_SDK_TIMEOUT_MS` | `3000` | per-call verdict timeout |
| `SECUREVECTOR_SDK_RISK_THRESHOLD` | `70` | risk score that blocks in enforce mode |
| `SECUREVECTOR_SDK_DISABLED` | _(unset)_ | set truthy to no-op |
| `SECUREVECTOR_API_KEY` | _(unset)_ | bearer credential for remote, token-gated deployments |

## Version pinning

The guard attaches to Hermes internals (the plugin hook bus and
`tools.registry`), so the dependency is pinned to the verified minor:
`hermes-agent>=0.18,<0.19`. Each upstream minor is re-verified against the
attach points before the pin is raised — see [CHANGELOG](CHANGELOG.md).

## Privacy

Everything runs on loopback; the SDK makes no external network calls. See
[PRIVACY.md](PRIVACY.md) for the exact read/send surface.

## Compliance

The tool-call-level, attributed, tamper-evident audit trail this produces is
exactly the **action-layer logging** auditors ask for under **EU AI Act
Art. 12 / 15**. This SDK produces the local evidence; the cloud governance
surface turns it into an auditor-ready pack.

## Trademarks

**SecureVector** is the product name of this SDK. **Hermes** and **Nous
Research** are trademarks of Nous Research. This is an independent, community
SDK that *integrates with* Hermes via its public plugin API. It is **not
affiliated with, sponsored by, or endorsed by Nous Research.** The name uses
"hermes" only descriptively, to identify the framework this package works
with (nominative fair use).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
