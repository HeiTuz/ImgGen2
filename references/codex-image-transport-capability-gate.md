# Codex subscription image transport: capability and release gate

Use this when maintaining or operating the Codex-CLI subscription image route.

## Durable lesson

A CLI version string, a successful ordinary `codex exec`, a listed `image_generation` feature flag, unit tests, and a dry-run command are only component checks. None proves that the current account + CLI mode + agent surface can invoke image generation and leave a PNG artifact.

Do not hard-code a permanent negative conclusion from one host/version failure. Treat capability as runtime-dependent and re-probe after CLI/account/surface changes.

## Capability ladder

1. Confirm the canonical Codex executable and version without reading auth files.
2. Run the network-free unit suite and a dry-run request.
3. Within an already authorized image-generation request, run one minimal live pilot that requests exactly one PNG and uses at most one small reference image.
4. Require all of the following before claiming the route works:
   - CLI terminal state is successful; any nonzero exit rejects artifacts from that invocation;
   - a newly created non-empty PNG is scoped to the current session;
   - the PNG is copied to the requested output and can be opened;
   - no fallback provider, API key, browser automation, or private endpoint was used.
5. Only after that capability pilot passes, proceed to multi-reference or production batch work. The production runner repeats transport proof on the first manifest record, then stops for independent pilot QC; bounded fan-out opens only after QC pass.
6. A batch dry-run must expose `manifest_sha256`, reference evidence, `approval_sha256`, pilot ID, output ownership, and worker bounds. These hashes are audit and resume evidence, not an extra approval ceremony. A maintenance-only request does not authorize live generation.

## Safe diagnostics

- General `codex exec` success proves only the base inference path.
- Feature listings prove registration/configuration, not tool availability inside the selected execution mode.
- For image edits, probe the smallest discriminating ladder: zero-reference generation → one reference → two references → the intended reference count. This separates base image capability, attachment parsing, and multi-reference behavior without blaming unrelated configuration prematurely.
- Codex CLI defines `--image <FILE>...` as variadic. A programmatic command builder must insert `--` before the positional prompt after the final `--image`; otherwise the prompt can be consumed as another image path and Codex reports that stdin supplied no prompt. Keep a regression test that asserts `command[-2] == "--"` and the real prompt is `command[-1]`.
- If the same request succeeds sequentially but fails only under fan-out, treat concurrency as the changed variable: plan a lower worker cap in a fresh retry ledger and dry-run again within the same authorized count. Do not mutate unrelated model/provider settings or silently switch routes.
- Parse structured JSON event types and stable error codes when available. Do not print or persist raw stdout/stderr because it may contain account/session data.
- If the failure classifier returns `unknown`, improve secret-safe classification from documented/stable codes rather than exposing raw output.
- After a failed live call, diagnose and change only one justified variable. Retry automatically only inside the unchanged requested scope; provider, cost, count, or overwrite changes require a fresh decision.

## Public-release gate

Do not publish README or skill metadata claiming working image generation based only on unit tests, dry-run output, feature flags, or installer smoke. Public release requires a real end-to-end PNG generated through the advertised route on the release candidate, plus tag-pointed installer smoke. If the real pilot is unavailable, describe the transport as experimental and do not promise successful generation.

## Product-folder pilot pattern

For apparel folders organized as color-fronts + main-color back + main-color fabric detail:

1. Classify filenames visually; do not infer roles from sequence alone.
2. Use main-color front as garment authority, back as silhouette/construction authority, and fabric close-up as texture/color authority.
3. Start with one main-color 3:4 wearing shot. Gate typography, neckline, sleeves, hem, color, texture, hands, and pose.
4. Expand to other colors only after the main-color pilot passes; otherwise the same garment error multiplies across variants.
