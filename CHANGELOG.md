# Changelog

All notable changes to `securevector-sdk-hermes` are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0]

### Added
- Initial Hermes (NousResearch `hermes-agent`) adapter — release unit δ of the
  `active-guard-plugin` bundle, story #183.
- **Zero-config Hermes plugin** via the `hermes_agent.plugins` entry point:
  the Hermes plugin manager auto-loads the guard in every mode (interactive
  CLI, gateway, ACP). `pre_tool_call` enforces via Hermes's documented block
  directive (`{"action": "block", "message": ...}`) with the
  `SecureVector Guard:` branded reason; `post_tool_call` scans tool results.
  Runs the three controls on every tool call:
  - **(a)** tool-call permission resolution (synced → override → essential → default-allow),
  - **(b)** secret / data-leak detection on tool input and output,
  - **(c)** threat detection on tool input and output.
- `install(mode=...)` for programmatic embeddings — wraps
  `tools.registry.dispatch`, the choke point all Hermes execution paths funnel
  through (deliberately NOT `model_tools.handle_function_call`, which
  `run_agent` re-imports by reference). `import securevector_sdk_hermes.auto`
  calls it with env-derived mode.
- **MCP-aware tool-id candidates**: Hermes registers MCP tools as
  `mcp_<server>_<tool>` (hyphens/dots sanitized to underscores — lossy), so
  permission resolution matches the raw Hermes name plus every
  `<server>:<tool>` split, tier precedence first.
- `HERMES_BUILTINS` — empirical built-in inventory extracted from the
  hermes-agent 0.18.0 sdist (69 registry tools + 3 Tool-Search bridge tools +
  bundled plugin tools), with a drift test that compares against a live
  hermes-agent install when importable.
- `observe` (fail-open, default) and `enforce` (fail-closed) modes; one-line
  cold-install notice when the app is unreachable in observe mode.
- Audit forwarding to the local app's tamper-evident chain with
  `runtime_kind="hermes"` attribution, keyed by Hermes `session_id` /
  `tool_call_id`.
- `/analyze` requests send the correct `direction` field (`outgoing` for tool
  input, `incoming` for tool output) — fixes the `mode`-field drift present in
  the sibling SDKs, so tool-output scans actually run the IDPI rule pack.
- Base URL honors the unified `SECUREVECTOR_ENGINE_ENDPOINT` (with legacy
  `SECUREVECTOR_SDK_APP_URL` fallback) and forwards an optional
  `SECUREVECTOR_API_KEY` as `Authorization: Bearer` for remote, token-gated
  deployments.
- Version pin `hermes-agent>=0.18,<0.19` — the attach points are re-verified
  before every pin raise.
- Harness-tailored [PRIVACY.md](PRIVACY.md); Apache-2.0 LICENSE + NOTICE with
  Nous Research trademark disclaimer.
- CI + Test PyPI (develop) / PyPI (main release) publishing via OIDC trusted
  publishing, mirroring the sibling framework SDKs.
