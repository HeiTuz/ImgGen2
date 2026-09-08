# Astra orchestration design

Reviewed 2026-09-08. Astra is the orchestrator, not an attested image-generation model. This upgrade keeps the configured host model and the existing Codex subscription lane.

## Reference decisions

- [OpenAI GPT-6 Astra guidance](https://developers.openai.com/api/docs/guides/latest-model) describes stronger instruction following, sustained tool use, and the need to calibrate initiative and clarification. The entry skill therefore states completion conditions, low-risk defaults, steering, and proportional delegation directly. It routes specialist procedures to a manual rather than loading all modes for every request.
- [OpenAI skills guidance](https://learn.chatgpt.com/docs/build-skills) informs the small entry surface and progressive disclosure. Host overlays share one rule body; only invocation and Vision-tool framing differ.
- The original base is [gongnyang/codex-fleet, pinned dc4d724](https://github.com/gongnyang/codex-fleet/blob/dc4d724d3c978077e406b4b3f0811bb0157094ad/runners/codex_imagegen_runner.py). Retained: bounded RAM-aware concurrency, ramping, explicit records, stdin isolation, and rate-limit handling. Replaced: newest global artifact claiming and file-exists-only resume with current-session ownership, ledger hashes, and ambiguous-artifact rejection. These are design adaptations, not upstream feature claims.
- Further GitHub comparisons and pinned sources are in [reliability and scaling](reliability-and-scaling.md). No upstream API size list or retry policy is treated as proof of subscription transport capability.

## Execution evidence

The batch summary adds `completion_state` and `next_action` without changing portable handoff schemas. Per-item artifact metadata includes PNG width, height, byte size, and SHA-256. A successful transport and a passing visual review remain distinct states. QC rows can include `output_sha256`; a supplied mismatch fails before acceptance. Legacy rows remain compatible.

PNG inspection streams chunk payloads, checks CRC and structure, rejects unsafe leaf paths, and verifies that the file did not change while read. This is container validation, not full pixel decoding. Vision still establishes source fidelity, text accuracy, and semantic shot intent. Exact dimensions are enforced by the portable handoff when requested.

Creative publication accepts only manifest/ledger-owned completed files and rechecks copied bytes. Its staging directory is uniquely reserved. Product selection resume checks current contract/report identity and exact inventory. Folder publication checks every source-derived output and finite family scores. MPW compilation uses isolated temporary files and only replaces the caller's manifest after complete validation.

## Maintenance boundaries

Installer dry-runs and updater status are read-only. Saved per-host QC preferences survive implicit upgrades; an explicit `--vision-qc` changes or repairs the setting. Local source/install parity is independently verifiable and does not require a release push.

Network-free tests and installation checks do not demonstrate live image quality or current subscription entitlement. A maintenance request does not silently trigger image generation. Report any absent live pilot explicitly. Process-tree cancellation and generic non-PNG provider decoding are not added by this change.
