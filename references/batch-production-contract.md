# Production Batch Contract

## What counts as batch generation

`codex_subscription_transport.py --batch-dir DIR` still performs **one** image call; it only chooses a dated destination folder. Real production batch generation is `scripts/codex_subscription_batch.py`, which consumes a JSONL manifest and owns pilot, fan-out, ledger, resume, partial failure, QC reconciliation, and retry-manifest creation.

## Manifest

One JSON object per line:

```json
{"id":"red-front","prompt":"Final compiled IMAGE prompt","output_path":"red/front.png","images":["refs/red-front.png","refs/main-back.png","refs/main-fabric.png"],"promotional":false,"rendered_text_exists":false,"series_locks":{"construction":"approved-main-pilot","material":"main-fabric-authority"}}
```

Required native fields: `id`, `prompt`, `output_path`. Optional: `images` (0–4), `promotional`, `rendered_text_exists`, `qc_required`, `metadata`, `series_locks`, `retry_of`. `qc_required: true` forces visual review for a job that would otherwise be a simple text-only generation; `false` never disables review triggered by references, product-photo metadata, or promotional layout while the installed QC mode is `auto`. An explicitly saved `vision-qc.json` mode of `off` disables visual gates and records `qc_skip_reason: disabled_by_user`; file validation remains required. The setting is part of effective manifest identity, so changing it mid-batch causes drift rather than silently changing acceptance rules.

A validated `MPW` production JSONL record is accepted directly: `full_prompt` aliases `prompt`; category/format/tier/lane/palette/AR/size/quality/promo fields are retained as compile metadata; `cut_type: promo_poster` and text fields infer QC branches. Because the Codex transport returns PNG only, compiled `.webp`/other output suffixes are deterministically normalized to `.png`, while the original compiled path remains in metadata. Run the MPW JSONL validator before this transport preflight; this runner validates execution ownership, not prompt doctrine.

The loader rejects duplicate IDs, duplicate normalized output ownership, absolute/traversing paths, symlink escapes, unknown fields, missing/symlink references, and more than four references. Native manifest output paths are PNG; MPW production suffixes are normalized to PNG as described above. `output_path` is always relative to the output root.

## Dry-run and approval

Dry-run is the default. It probes the resolved Codex executable with `--version`, but makes no image-generation call:

```bash
python scripts/codex_subscription_batch.py \
  --manifest jobs.jsonl \
  --output-root ./outputs \
  --workers auto
```

It prints `manifest_sha256` and `approval_sha256` as provenance. The canonical manifest digest includes normalized records, resolved reference paths, and each reference file's SHA-256/size. JSONL parsing and digest serialization are incremental. Within one load, unchanged references share a cached digest; device, inode, size, modification time, and change time are checked before reuse and again at the end. A new load always rehashes the files, so resumed runs still detect changed reference content. Mutation during hashing or loading fails closed. Reference hashes are rechecked immediately before and after each generation; a changed reference stops admission and cannot be accepted as the original-bound result. `approval_sha256` additionally binds `workers`, start, hard cap, ramp interval, and RAM estimate. An explicit user batch request authorizes this bounded scope; live execution uses `--execute` without copying the digest into an environment variable.

```bash
python scripts/codex_subscription_batch.py \
  --manifest jobs.jsonl \
  --output-root ./outputs \
  --workers auto \
  --execute
```

Digests still detect drift. Confirmed failed or QC-failed items may be retried inside the unchanged user-requested scope. A timeout or interrupted running entry has an unknown outcome and is not eligible for automatic regeneration. Scope/count expansion, provider or paid-route changes, original overwrite, and external publication require a fresh user decision.

For `creative_batch.py`, dry-run planning uses an isolated temporary directory. If a prior live workspace exists, its exact compiled manifest is copied into scratch for planning; existing images, ledger, and manifest remain untouched even when preflight fails. `workspace_retained` reports whether that prior workspace exists.

## Pilot and fan-out

The first manifest record is always the transport pilot and runs alone. A pilot with references, product-photo metadata, promotional layout, or `qc_required: true` stops with `awaiting_pilot_qc: true`; independent four-axis QC must pass before a later invocation opens fan-out. A simple text-only pilot records `qc_status: skipped` and opens bounded fan-out in the same invocation. Transport failure still leaves remaining jobs pending and stops the pass.

After the pilot:

- `--workers N` uses a bounded explicit target;
- `--workers auto` uses available RAM, `--ram-per-worker-gb`, and `--hard-cap`;
- concurrency starts at `--start` and grows by one after every `--ramp-every` healthy completions;
- outstanding futures are bounded by the worker target, rather than the manifest length;
- `rate_limited`, `authentication_required`, `entitlement_denied`, `model_unavailable`, `image_tool_unavailable`, `cli_argument_error`, `reference_changed`, and `outcome_unknown`/legacy `timeout` stop new dispatch; active calls finish and unstarted jobs remain `pending` with no attempt recorded;
- `dispatch_stopped_reason` in JSON summaries identifies the shared-lane failure;
- per-cut failures, including moderation rejection, leave unrelated cuts eligible;
- each job still invokes the existing session-provenance transport independently;
- completion order never changes manifest-order summaries.

There is no global-newest-PNG or claimed-pool fallback. Upstream `claimed` locking prevents duplicate claims but can still assign worker B's PNG to worker A. Session/thread identity remains authoritative here.

## Ledger and resume

The output root owns:

- `.imggenimggen2-batch.json` — atomic ledger;
- `.imggenimggen2-batch.lock` — exclusive live runner lock;
- `batch-summary.json` and `batch-summary.md` — deterministic final summaries.

The ledger records manifest hash, config, manifest order, per-job status, attempts, source artifact, destination SHA-256/size, failure category, QC report, and timestamps. Writes use temp file + fsync + replace.

Resume skips only a ledger-owned `succeeded`, `skipped`, or `qc_failed` output whose regular-file SHA-256 and size still match. A merely existing path is a conflict. Tampered/missing outputs, corrupt ledger, changed manifest, duplicate runner, and interrupted ownership fail closed. Interrupted `running` jobs become failed unknown outcomes and require reconciliation before retry.

One pass makes one attempt per pending job. It never loops retries inside the approval. Operational failures are recorded and can be exported to a retry manifest. If any unresolved failure coexists with unstarted/recovered pending jobs, the original ledger cannot fan out on a later invocation; its retry manifest includes the failed jobs plus every pending job so the new approved pass cannot strand interrupted work. This includes capability-pilot failure, where the failed pilot remains first.

## QC reconciliation and selective retry

This reconciliation is an execution-time safety gate for pilot admission, fan-out, and failed-cut-only retries. It is not final acceptance: final visual QC, comparison, and selection for delivered work belongs to the active review workflow.

The helper does not inspect pixels. Independent human/Vision review supplies QC JSONL keyed by `id`:

```json
{"id":"red-front","axis_scores":{"goal_fit":5,"text_accuracy":5,"material_realism":4,"layout":4},"rendered_text_exists":false}
```

Promotional jobs also require:

```json
{"physical_type_subject_interaction":true,"generic_card_regression":false,"printed_meta_ui_not_literal":true,"color_count":3,"finishing_device_count":2,"korean_glyph_mask_safe":true}
```

Apply and emit failed-cut-only retries:

```bash
python scripts/codex_subscription_batch.py \
  --manifest jobs.jsonl \
  --output-root ./outputs \
  --qc-results qc.jsonl \
  --retry-manifest retry.jsonl
```

Only failed axes and failed promo checks are appended as retry deltas. Passing cuts are excluded. QC retries receive a new non-overwriting output under `retries/`; `metadata` and `series_locks` remain intact. Because the retry JSONL has a new manifest hash, run it with a separate ledger inside the same output root:

```bash
python scripts/codex_subscription_batch.py \
  --manifest retry.jsonl \
  --output-root ./outputs \
  --ledger ./outputs/.imggenimggen2-retry.json
# repeat with --execute inside the unchanged authorized scope
```

The shared output-root lock prevents original/retry runners from overlapping, while separate ledgers preserve each manifest's identity. A custom ledger also receives custom `<ledger-stem>-summary.json/.md` files, so retry summaries do not overwrite the original batch summary.

## Interrupted or uncertain attempts

An interrupted `running` entry becomes `failed` with `failure_category: interrupted_outcome_unknown`. CLI timeouts are `outcome_unknown`; summaries list affected IDs in `unknown_outcomes` and request `reconcile_unknown_outcomes_before_retry`. Rerunning the same manifest does not call those jobs or admit remaining jobs. Any existing output is preserved as unaccepted evidence.

Inspect the prior CLI session and its artifacts first. Retain and review a completed image instead of generating it again. The Codex batch helper does not automatically adopt artifacts from a failed/unknown CLI invocation. If no usable result exists and a fresh generation is needed, explicitly assert that reconciliation when writing the retry manifest:

```bash
python scripts/codex_subscription_batch.py --manifest jobs.jsonl --output-root ./outputs --execute --retry-manifest retry.jsonl --unknown-outcomes-reconciled
```

For an existing unknown-outcome ledger this invocation only writes retry planning; it does not rerun the uncertain jobs. Then dry-run and execute the retry manifest with a separate ledger as above. Do not use the assertion merely to bypass an error. Preserve the prior evidence and never delete an occupied output to make a retry succeed; reconciled unknown-outcome retry records receive fresh paths under `retries/`.

## Parallel worker orchestration

Parallel workers are useful above the runner rather than as an excuse to omit batch support:

1. **Compiler/planner lanes** can independently classify folders and compile disjoint JSONL records through `MPW`.
2. **Executor lanes** may own disjoint manifest shards only when each shard has a separate output root and ledger inside the authorized scope. Two agents must never share one live ledger/output root.
3. **Critic lanes** can inspect disjoint output sets and return QC JSONL; they do not mutate PNGs or mark their own work accepted.
4. **Prime/aggregator** validates unique IDs/output ownership, runs or supervises the authoritative pilot, reconciles ledgers and QC, generates retry manifests, and verifies final artifacts.

For ordinary batches, one authoritative runner already performs bounded parallel Codex calls and is simpler than assigning every image to a worker. Use additional workers when manifest compilation or independent visual QC is the bottleneck, or when very large batches are partitioned into explicitly disjoint shards.

## Runtime hygiene

- **Moderation-rejected cuts** land in the ledger as `failure_category: moderation_rejected` and flow into the standard retry manifest. Before retrying, rework each rejected prompt into neutral campaign/editorial language with the same subject, layout, and copy intent — never escalate explicitness or switch providers to route around a refusal.
- **Disk preflight**: inspect free space against the requested count and expected artifact size. Retain unresolved session artifacts. Cleanup is separate from generation and requires a verified delivered copy and authorization for the selected files.
- **Long runs** stay attached to the tool session handle. Read ledger/summary progress and wait for terminal state before claiming completion.
- **Interrupted workers**: identify processes owned by this invocation before any termination. Never use a broad name-pattern kill across Codex sessions. Reconcile uncertain generation outcomes before retrying.

## Non-negotiable invariants

- no API key/private endpoint/browser/cookie/provider fallback;
- no model-identity attestation without supported evidence;
- at most four existing references;
- no overwrite, symlink source, traversal, or global artifact pool;
- nonzero Codex exit rejects every artifact from that invocation;
- raw subprocess output is never written to the ledger or summary;
- no live generation, Vision, or external delivery call during tests;
- no text-overlay repair; failed text cuts are regenerated.
