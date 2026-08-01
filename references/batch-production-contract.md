# Production Batch Contract

## What counts as batch generation

`codex_subscription_transport.py --batch-dir DIR` still performs **one** image call; it only chooses a dated destination folder. Real production batch generation is `scripts/codex_subscription_batch.py`, which consumes a JSONL manifest and owns pilot, fan-out, ledger, resume, partial failure, QC reconciliation, and retry-manifest creation.

## Manifest

One JSON object per line:

```json
{"id":"red-front","prompt":"Final compiled IMAGE prompt","output_path":"red/front.png","images":["refs/red-front.png","refs/main-back.png","refs/main-fabric.png"],"promotional":false,"rendered_text_exists":false,"series_locks":{"construction":"approved-main-pilot","material":"main-fabric-authority"}}
```

Required native fields: `id`, `prompt`, `output_path`. Optional: `images` (0–4), `promotional`, `rendered_text_exists`, `qc_required`, `metadata`, `series_locks`, `retry_of`. `qc_required: true` forces visual review for a job that would otherwise be a simple text-only generation; `false` never disables review triggered by references, product-photo metadata, or promotional layout.

A validated `MPW` production JSONL record is accepted directly: `full_prompt` aliases `prompt`; category/format/tier/lane/palette/AR/size/quality/promo fields are retained as compile metadata; `cut_type: promo_poster` and text fields infer QC branches. Because the Codex transport returns PNG only, compiled `.webp`/other output suffixes are deterministically normalized to `.png`, while the original compiled path remains in metadata. Run the MPW JSONL validator before this transport preflight; this runner validates execution ownership, not prompt doctrine.

The loader rejects duplicate IDs, duplicate normalized output ownership, absolute/traversing paths, symlink escapes, unknown fields, missing/symlink references, and more than four references. Native manifest output paths are PNG; MPW production suffixes are normalized to PNG as described above. `output_path` is always relative to the output root.

## Dry-run and approval

Dry-run is the default and calls no subprocess:

```bash
python scripts/codex_subscription_batch.py \
  --manifest jobs.jsonl \
  --output-root ./outputs \
  --workers auto
```

It prints `manifest_sha256` and `approval_sha256` as provenance. The canonical manifest digest includes normalized records, resolved reference paths, and each reference file's SHA-256/size. `approval_sha256` additionally binds `workers`, start, hard cap, ramp interval, and RAM estimate. An explicit user batch request authorizes this bounded scope; live execution uses `--execute` without copying the digest into an environment variable.

```bash
python scripts/codex_subscription_batch.py \
  --manifest jobs.jsonl \
  --output-root ./outputs \
  --workers auto \
  --execute
```

Digests still detect drift. Failed or QC-failed items may be retried automatically inside the unchanged user-requested scope. Scope/count expansion, provider or paid-route changes, original overwrite, and external publication require a fresh user decision.

## Pilot and fan-out

The first manifest record is always the transport pilot and runs alone. A pilot with references, product-photo metadata, promotional layout, or `qc_required: true` stops with `awaiting_pilot_qc: true`; independent four-axis QC must pass before a later invocation opens fan-out. A simple text-only pilot records `qc_status: skipped` and opens bounded fan-out in the same invocation. Transport failure still leaves remaining jobs pending and stops the pass.

After the pilot:

- `--workers N` uses a bounded explicit target;
- `--workers auto` uses available RAM, `--ram-per-worker-gb`, and `--hard-cap`;
- concurrency starts at `--start` and grows by one after every `--ramp-every` healthy completions;
- a `rate_limited` failure freezes further growth;
- each job still invokes the existing session-provenance transport independently;
- completion order never changes manifest-order summaries.

There is no global-newest-PNG or claimed-pool fallback. Upstream `claimed` locking prevents duplicate claims but can still assign worker B's PNG to worker A. Session/thread identity remains authoritative here.

## Ledger and resume

The output root owns:

- `.imggenimggen2-batch.json` — atomic ledger;
- `.imggenimggen2-batch.lock` — exclusive live runner lock;
- `batch-summary.json` and `batch-summary.md` — deterministic final summaries.

The ledger records manifest hash, config, manifest order, per-job status, attempts, source artifact, destination SHA-256/size, failure category, QC report, and timestamps. Writes use temp file + fsync + replace.

Resume skips only a ledger-owned `succeeded`, `skipped`, or `qc_failed` output whose regular-file SHA-256 and size still match. A merely existing path is a conflict. Tampered/missing outputs, corrupt ledger, changed manifest, duplicate runner, and interrupted ownership fail closed. Interrupted `running` jobs recover to `pending`.

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

## Parallel worker orchestration

Parallel workers are useful above the runner rather than as an excuse to omit batch support:

1. **Compiler/planner lanes** can independently classify folders and compile disjoint JSONL records through `MPW`.
2. **Executor lanes** may own disjoint manifest shards only when each shard has a separate output root and ledger inside the authorized scope. Two agents must never share one live ledger/output root.
3. **Critic lanes** can inspect disjoint output sets and return QC JSONL; they do not mutate PNGs or mark their own work accepted.
4. **Prime/aggregator** validates unique IDs/output ownership, runs or supervises the authoritative pilot, reconciles ledgers and QC, generates retry manifests, and verifies final artifacts.

For ordinary batches, one authoritative runner already performs bounded parallel Codex calls and is simpler than assigning every image to a worker. Use additional workers when manifest compilation or independent visual QC is the bottleneck, or when very large batches are partitioned into explicitly disjoint shards.

## Runtime hygiene

- **Moderation-rejected cuts** land in the ledger as `failure_category: moderation_rejected` and flow into the standard retry manifest. Before retrying, rework each rejected prompt into neutral campaign/editorial language with the same subject, layout, and copy intent — never escalate explicitness or switch providers to route around a refusal.
- **Disk preflight**: `~/.codex/generated_images/` accumulates session PNGs that were never recovered (refusals, interrupted runs). Verify at least 2 GB free before a large batch and periodically clean session folders whose artifacts are already ledger-verified at their destinations.
- **Long runs** belong in the background with progress read from the ledger/summary files, not from a foreground terminal.
- **Stray worker cleanup**: after aborting a batch, terminate leftover CLI workers with a process-qualified pattern such as `pkill -9 -f "codex exec"`. Never `pkill -f <runner-script-name>` from an interactive shell — the pattern matches the invoking shell's own command line and kills it.

## Non-negotiable invariants

- no API key/private endpoint/browser/cookie/provider fallback;
- no model-identity attestation without supported evidence;
- at most four existing references;
- no overwrite, symlink source, traversal, or global artifact pool;
- nonzero Codex exit rejects every artifact from that invocation;
- raw subprocess output is never written to the ledger or summary;
- no live generation, Vision, or external delivery call during tests;
- no text-overlay repair; failed text cuts are regenerated.
