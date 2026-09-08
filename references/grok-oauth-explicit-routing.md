# Explicit Grok Routes

## Activation

The Grok route is opt-in. Select it only when the user's current request explicitly asks to generate or edit an image with `Grok`, `그록`, or `xAI`. A bare image request, an exact-count request, or the mere presence of xAI credentials never selects Grok; those requests stay on the default Codex subscription route.

## Official Grok CLI lane (Codex / Claude)

On Codex and Claude, use `scripts/grok_cli_transport.py` with an existing working official `grok` CLI login. Bare image and exact-count requests stay on Codex. Do not use the Hermes-only gate to disable this distinct CLI lane.

```bash
python3 scripts/grok_cli_transport.py --prompt "A blue ceramic cup on white" --output /absolute/path/cup.jpg
python3 scripts/grok_cli_transport.py --prompt "A blue ceramic cup on white" --output /absolute/path/cup.jpg --execute
python3 scripts/grok_cli_transport.py --prompt "Change only the cup to red" --image /absolute/path/cup.jpg --output /absolute/path/red-cup.jpg --execute
```

Dry-run first for both generation and editing. The explicit image request authorizes bounded execution. The helper permits one native `image_gen` or `image_edit` call and no provider fallback. It uses the CLI's own existing authentication without reading credentials. API-key environment overrides are not passed through. CLI login success does not attest subscription billing: record `auth_mode: cli-managed-unattested` and `billing_mode: unattested` unless independent evidence establishes them. Do not describe CLI usage estimates as actual charges or promise that a subscription covers the call.

The CLI writes images to its own session folder. The helper binds a fresh UUID and working directory, reads only that session's native tool result, copies the single owned artifact without overwrite, and writes `.grok-runs/<session-id>/provenance.json` next to the output. Assistant prose alone is not artifact provenance. Nonzero or malformed CLI responses do not automatically deliver; inspect the run before explicit recovery. A session identity mismatch blocks recovery. Recorded output hashes cannot be replaced by changed session artifacts, and a valid delivered output remains resumable after session cleanup. JPEG output was observed with Grok CLI 1.0.13; request `.jpg` by default. PNG is accepted only when the returned bytes are actually PNG. No resizing or format conversion is performed. JPEG framing/dimensions and PNG container checks do not decode pixels; apply the normal host visual review when required. Never attest the image model from the CLI's chat model name.

On timeout or incomplete delivery, inspect the recorded session and use `--recover-run /absolute/path/.grok-runs/<session-id>` to recover without a new generation call. Do not automatically retry a generation whose outcome is unknown. Execution and recovery use an exclusive run lock; a still-running CLI must reach terminal state before recovery. Output extension mismatches remain incomplete with the original artifact preserved. Recover to its actual format with `--recover-run /absolute/path/.grok-runs/<session-id> --output /absolute/path/correct.jpg`; this makes no generation call, refuses occupied destinations, and never relabels or converts bytes.

For N CLI images, execute exactly N independent jobs with unique output paths and record per-cut results. Run the pilot and QC first, then continue sequentially. The Codex batch executor is not a Grok dispatcher; the Hermes concurrency limits below do not imply a CLI batch implementation. Keep completed outputs, and resume only pending jobs after resolving any shared failure.

## Hermes native OAuth lane

On Hermes, before every native Grok execution, require both:

1. at least one configured Hermes `xai-oauth` credential; and
2. the Hermes-native xAI `image_generate` tool to be available in the current session.

An `XAI_API_KEY` by itself does not enable this HeiTuz route. Never inspect or print token files, initiate login, use `hermes chat` subprocesses, start `progrok`, reuse browser cookies, or call a private endpoint. If either gate is missing, return `grok_route: disabled` with the missing capability and stop. Never fall back to Codex, Higgsfield, an API key, or another model/provider.

Tool availability is session-scoped. After enabling or configuring Hermes image generation, start a fresh Hermes session before treating `image_generate` as available.

## Hermes single image

1. Optionally compile the final IMAGE prompt through the MPW boundary when installed; MPW is never a required gate, and a direct prompt is equally valid.
2. Record `requested_provider: grok`, `auth_mode: xai-oauth`, and the requested geometry. Never record credential values.
3. Invoke the native `image_generate` tool once with the xAI-backed model selected by Hermes configuration.
4. Materialize the returned image locally immediately; remote result URLs are not durable delivery evidence.
5. Record the local path, byte size, SHA-256, provider/model provenance returned by the tool, request/job identifier when present, and `qc_status: not_evaluated`.
6. Run the same independent visual QC used by the Codex lane. Transport success is not visual acceptance.

## Hermes exact-N batch

An explicit request for N Grok images creates exactly N independent jobs. Never reduce N to the worker limit and never submit all N simultaneously.

- Build an immutable manifest with stable job IDs and one complete prompt per job.
- Submit the first job as a transport-and-quality pilot. Do not fan out until its artifact is locally materialized, hash-verified, and independently approved.
- Bounded fan-out starts at 3 active jobs. After healthy completions, grow to at most 5. The remaining jobs stay queued.
- Every job owns an independent output path and ledger record: `queued`, `running`, `succeeded`, or `failed`; attempt count; prompt/manifest digest; output size/hash; non-secret error class; provider/model provenance; and QC state.
- On rate limiting, freeze growth, honor `Retry-After` when present, and reduce active concurrency. Retry only failed jobs under a fresh attempt record; never restart successful jobs or overwrite their artifacts.
- Retry transient timeout/429/5xx failures only within the bounded retry budget. Authentication, entitlement, malformed-request, or unavailable-tool failures stop without provider fallback.
- Completion means all requested jobs are terminal and every success is hash-verified. Partial success remains partial; it is not rounded up to N.

## Hermes routing examples

| Request | Route |
| --- | --- |
| “이미지 한 장 만들어줘” | Codex subscription default |
| “20장 만들어줘” | Codex exact-N default |
| “Grok으로 한 장 만들어줘” | Grok OAuth, if both gates pass |
| “그록으로 20장 생성해줘” | Grok OAuth exact-N queue, if both gates pass |
| “xAI 느낌으로 만들어줘” where xAI is only an aesthetic phrase | Codex; provider intent is not explicit |
| Explicit Grok request without `xai-oauth` | Disabled; no fallback |
| Explicit Grok request with only `XAI_API_KEY` | Disabled; API-key-only does not enable this route |

## Secret-safe evidence

Allowed durable facts: credential type (`xai-oauth`), credential availability boolean, provider/model names returned by the tool, request/job IDs, usage facts, output metadata, hashes, and classified errors.

Forbidden durable data: access/refresh tokens, API keys, cookies, authorization headers, raw auth files, or raw exception bodies that may contain them.
