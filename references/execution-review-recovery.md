# Execution, review, and recovery

Read this when you are about to run a helper, after every `batch-summary.json`, and before any retry. The entry `SKILL.md` holds the invariants (dry-run first, exact N, immutable originals, risk-based QC); this file carries the command shapes, state table, and recovery rules.

## Run the helper

Run the selected helper with `--help` if its arguments are uncertain. Commands are relative to the installed skill root. For example:

```bash
python scripts/codex_subscription_transport.py --prompt "A blue ceramic cup on natural linen" --output /absolute/path/cup.png
python scripts/codex_subscription_transport.py --prompt "A blue ceramic cup on natural linen" --output /absolute/path/cup.png --execute
```

For edits add `--image /absolute/path/original.png`. Dry-run first, then execute within the existing request. For batches prepare JSONL, dry-run `--manifest` and `--output-root`, then execute with the same ownership and worker bounds. The first record is a sequential transport pilot.

## Read `batch-summary.json` after every run

| `completion_state` | Next action |
| --- | --- |
| `awaiting_pilot_qc` | Review the exact pilot, write QC JSONL, apply `--qc-results` without `--execute`, then resume with `--execute` |
| `running` | Wait for the active invocation using its session handle |
| `awaiting_qc` | Review the listed IDs and apply QC |
| `incomplete` | Read per-cut categories, `unknown_outcomes`, and `dispatch_stopped_reason`; reconcile uncertain attempts before creating any retry manifest |
| `pending` | Resume the existing batch within its recorded bounds |
| `complete` | Verify ledger-owned files and destination, then deliver |

Use `next_action` with the evidence in `items`, including `output_sha256` and PNG dimensions. Include `output_sha256` in each QC record to bind the review to the actual artifact; mismatches are rejected. Older records without a hash remain compatible but lack that explicit review binding. Parallel workers own disjoint outputs and ledgers. Successful outputs are hash-verified on resume and never regenerated just to restart a batch.

## Vision QC

`auto` is risk-based, not always-on: review when at least one reference/input image exists, an edit/product/promotion is requested, or the user asks for review. For simple text-only work skip Vision analysis and regeneration; mark `simple_text_only`. The user's saved `off` setting disables visual review; still validate artifacts and report that visual acceptance was not checked. Follow the [QC rubric](production-workflows.md#post-generation-vision-qc) for required axes and thresholds. Inspect contact sheets for series consistency, then full-resolution originals for uncertain identity, text, labels, seams, and fine details. Never invent QC scores.

## Recover the smallest failed unit

Repair the smallest failed visual requirement and regenerate only the failed independent cut from its immutable original; a cumulative edit retry uses the last accepted base, never the failed candidate. Fix rendered text by regeneration, not text overlays. Keep passing cuts. A shared lane failure stops new dispatch; do not hammer a rate-limited or unauthenticated provider. For moderation rejection, use a policy-compliant prompt revision only where the intent permits; do not disguise disallowed intent or switch providers to evade a refusal.
