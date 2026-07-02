# Privacy Policy — SecureVector SDK for Hermes

**Last updated:** 2026-07-01
**Applies to:** securevector-sdk-hermes v1.0.x

The SecureVector SDK for Hermes runs entirely on your machine, inside the same
Python process as NousResearch's `hermes-agent`. It observes Hermes tool calls
through Hermes's public plugin hooks (`pre_tool_call` / `post_tool_call`) — or,
for library embeddings, a wrap of Hermes's tool-registry dispatch — and posts a
small payload over **loopback HTTP** to a companion app you installed locally.
The SDK itself makes no network calls to SecureVector, to Nous Research, or to
any third party.

What happens to the data *after* it reaches the companion app — local storage,
optional cloud sync, retention, deletion — is governed by the **companion
app's** own privacy policy, not this one.

## What the SDK reads

| Surface | What it reads | Where it sends it |
|---|---|---|
| `pre_tool_call` hook (or dispatch wrap, pre-execution) | Tool name, serialized tool arguments, Hermes `session_id` / `tool_call_id` / `api_request_id` | Local app: GET `/api/tool-permissions/{essential,overrides,synced-overrides}` (no user data in the GETs), POST `/analyze` (arguments text, capped at 100 KB), POST `/api/tool-permissions/call-audit` (tool id, decision, an args preview truncated to 500 chars) |
| `post_tool_call` hook (or dispatch wrap, post-execution) | Tool name and the tool's result text | Local app POST `/analyze` (result text, capped at 100 KB); POST `/api/tool-permissions/call-audit` only when a finding is detected |

The SDK never reads Hermes state files, `~/.hermes/` contents, prompts, or
model responses — only what Hermes passes to the tool-call hooks.

## Where the data goes

Every network-bound surface talks to **loopback HTTP** at
`http://127.0.0.1:8741` (overridable via `SECUREVECTOR_ENGINE_ENDPOINT`, or
the legacy `SECUREVECTOR_SDK_APP_URL`). Traffic never leaves your machine
unless you deliberately point that variable at a remote SecureVector
deployment you operate (in which case `SECUREVECTOR_API_KEY` is forwarded as
a bearer credential to that host and nothing else).

The SDK writes no files to disk.

For anything the companion app does with payloads after they arrive (local
SQLite persistence, optional Cloud Connect, SIEM forwarding, retention
windows, deletion), see the companion app's privacy documentation:
<https://github.com/Secure-Vector/securevector-ai-threat-monitor>.

## Client-side redaction before any POST

Before sending an `args_preview` to the audit endpoint, the SDK masks common
secret shapes (AWS access key IDs, GitHub `ghp_` tokens, `sk-…` API keys,
labelled `password=` pairs) and truncates to 500 characters. Redaction is
**best-effort pattern matching, not a cryptographic guarantee** — the
canonical pattern set lives in `src/securevector_sdk_hermes/core.py`. The
full argument/result text sent to `/analyze` is redacted and persisted by the
companion app according to its own policy.

## What the SDK never collects

- **No external telemetry, analytics, or crash reports.**
- **No data to Nous Research.**
- **No data to SecureVector's cloud.** The SDK makes no outbound network calls.
- **No OS identifiers, IP addresses, or third-party account identifiers.**
  The SDK forwards the Hermes-generated `session_id` / `tool_call_id` to the
  **local** endpoints for correlation; these identifiers never leave the
  loopback POSTs.

## Failing open

If the local companion app is unreachable, `observe` mode (the default) lets
every tool call proceed — the event is dropped, not queued, buffered, or
retried, and never reaches network. A one-line notice is printed once per
process. In `enforce` mode an unreachable app blocks tool calls (fail-closed)
by design; no data is transmitted in either case.

## Disabling the SDK

- `pip uninstall securevector-sdk-hermes`, or
- set `SECUREVECTOR_SDK_DISABLED=1` to no-op without uninstalling.

Once disabled, no hooks are registered and no POSTs are made.

## Source code & licence

The SDK is **Apache-2.0 licensed** and published at
<https://github.com/Secure-Vector/securevector-sdk-hermes>. The whole
interception surface is auditable — `plugin.py` (hooks + dispatch wrap),
`client.py` (every HTTP call), and `core.py` (decision logic + redactor) — we
encourage reviewing them before installation.

## Changes to this policy

We may update this policy from time to time. Material changes will bump the
**Last updated** date and be noted in the [CHANGELOG](./CHANGELOG.md).

## Contact

For privacy questions about the SDK, email **privacy@securevector.io**, or
open an issue at
<https://github.com/Secure-Vector/securevector-sdk-hermes/issues>.
