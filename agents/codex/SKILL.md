---
name: ImgGen2
description: "Generate and edit images through the default official Codex CLI subscription route, with provenance-safe single-image transport, resumable exact-N batches, independent QC, and an optional dynamic apparel full-set workflow. GPT/Codex host surface: the host and the generation transport coincide; the optional Grok route requires Hermes-native tooling and stays disabled on this host."
version: 1.13.0
author: HeiTuz
license: MIT
platforms: [linux, macos, windows]
metadata:
  host_surface: codex
  canonical_source: "HeiTuz/ImgGen2 SKILL.md v1.13.0"
  tags: [image-generation, image-editing, chatgpt]
  category: creative
---

# ImgGen2 (GPT/Codex surface)

> **Host integration — GPT/Codex.** This file is the entry surface for Codex installs (`~/.codex/skills/ImgGen2`). The rules below are identical to the canonical SKILL.md; only the host-integration surface (frontmatter, invocation notes, tool naming) is migrated.
> - **Invocation**: Codex discovers this skill from its skills directory. `scripts/*.py` commands run through the Codex shell. The generation backend is the same official Codex CLI subscription transport the canonical skill defines — host and transport coincide here, which changes nothing about the dry-run-first contract.
> - **Vision QC tool**: the "host's default Vision tool" on this host is Codex's native image input — attach the artifact to a review turn and apply the QC rubric below. No separate reviewer model is pinned.
> - **Grok route**: the explicit-only Grok route requires the Hermes-native xAI `image_generate` tool plus `xai-oauth`. Neither exists on Codex, so an explicit Grok request always fails closed as `grok_route: disabled` — never substitute the default route for it.

Generate, inspect, and deliver the requested images. Codex remains the default image route; provider-specific requests follow the routing table below. Complete the authorized workflow through generation, required QC, targeted recovery, and actual file delivery. A plan, dry-run, task specification, process ID, or successful transport alone is not a completed image request.

## Work with the active orchestrator

This skill is tuned for GPT-6 Astra's instruction following and sustained tool use, and works with other hosts. The active model coordinates the work; its name does not identify the image generator. Keep the user's configured model and reasoning settings. Do not pin Astra into the image transport or change global settings to use this skill.

Start from the user's intent and inspect available references. Form one compact production brief: subject, intended use, exact count, composition/canvas, visual direction, immutable details, permitted variation, required text, and destination. Fill low-risk omissions with coherent defaults and proceed. Ask only when missing information materially affects identity, rights, cost, destructive changes, or a required deliverable. Do not make the user approve a prompt merely because it was expanded.

The explicit generation request authorizes its bounded execution, including the pilot and justified failed-cut retries, without a second confirmation. A dry-run checks paths, ownership, and capabilities; it is not a permission checkpoint. Additional authorization applies only to actions outside the already authorized scope. Researching or improving this skill alone does not authorize a paid or subscription image-generation test.

Respect steering during execution. Preserve accepted cuts, source locks, and count when the user changes one requirement. Use subagents only when permitted by the host and when independent work benefits; never create user-visible tasks for internal fan-out. Simple one-image work stays local. Keep all long-running calls attached to their returned session IDs until terminal state.

## Choose one workflow

| Request | Executor and required reading |
| --- | --- |
| One new image or edit | `scripts/codex_subscription_transport.py`; [execution contract](references/execution-contract.md) |
| Exact-N independent images, reference series, or product set | `scripts/codex_subscription_batch.py`; [batch contract](references/batch-production-contract.md) and the matching section of [production workflows](references/production-workflows.md) |
| Text-only ideation/reference-board | `scripts/creative_batch.py`; production workflows, “Production batch” |
| Portable MPW handoff | `scripts/consume_image_handoff.py`; production workflows, “Portable compiled handoff” |
| Identity grid or full-body series | Production workflows, portrait grids, full-body variation, and Vision QC sections |
| Product references or apparel folder | Production workflows, product-photo dispatcher and apparel sections; [folder case](references/cases/apparel-ghost-cut-folder-batch.md) |
| Explicit Grok / 그록 / xAI | [OAuth routing](references/grok-oauth-explicit-routing.md); requires `xai-oauth` and Hermes-native xAI `image_generate` |
| Explicit Wan / Alibaba image | `scripts/alibaba_token_plan_transport.py`; production workflows, “Direct-native media routing” |
| Explicit HappyHorse video | Configured Hermes Alibaba adapter; production workflows provider contract |
| Explicit browser workflow | [browser-backed editing](references/browser-backed-image-editing.md) |
| Explicit Higgsfield / Midjourney | The provider's own skill |

Do not load unrelated provider or apparel instructions into ordinary image requests. MPW is optional for direct prompts; the creative-batch helper uses its variation compiler. A nine-panel grid is one artifact when requested as a grid; N separate images require exactly N independent jobs.

## Build prompts that survive a batch

Use short, self-contained prompts with the concrete visual result first. Bind source-observed identity/product facts separately from the changing scene or shot. State one composition, one lighting treatment, relevant material/texture cues, and the required framing. Quote rendered copy exactly, with its role and position. Avoid stacks of generic quality adjectives and contradictory aesthetic instructions.

For references, inspect the images before describing them. Lock only observed details: face geometry and marks, hair, product silhouette, construction, material, component count, logo placement, and valid colourways. Preserve unknown or occluded details as unknown. Store those locks in the manifest metadata and bind them into every cut; a filename or prompt claim is not visual evidence. Product sets require the immutable ProductSpec, exact cut plan, per-cut binding, and semantic QC in the workflow manual.

For human proportions use the user's numbers first, then an available `references/full-body-calibration.local.md`, otherwise natural proportions from the reference. Avoid compulsory measurement questions. For details, name the source-supported feature and intended crop so the model cannot satisfy a detail request with another generic front view.

The subscription helper has no size/quality flags. Express the requested dimensions and ratio in the prompt and verify actual PNG dimensions. Use the portable handoff dimension check for exact requirements. Never silently substitute a nearby ratio, stretch anatomy, pad/crop away a mismatch, or claim compliance from prompt tokens.

## Execute, review, recover

Run the selected helper with `--help` if its arguments are uncertain. Commands are relative to the installed skill root. For example:

```bash
python scripts/codex_subscription_transport.py --prompt "A blue ceramic cup on natural linen" --output /absolute/path/cup.png
python scripts/codex_subscription_transport.py --prompt "A blue ceramic cup on natural linen" --output /absolute/path/cup.png --execute
```

For edits add `--image /absolute/path/original.png`. Dry-run first, then execute within the existing request. For batches prepare JSONL, dry-run `--manifest` and `--output-root`, then execute with the same ownership and worker bounds. The first record is a sequential transport pilot. Read `batch-summary.json` after every run:

| `completion_state` | Next action |
| --- | --- |
| `awaiting_pilot_qc` | Review the exact pilot, write QC JSONL, apply `--qc-results` without `--execute`, then resume with `--execute` |
| `running` | Wait for the active invocation using its session handle |
| `awaiting_qc` | Review the listed IDs and apply QC |
| `incomplete` | Read per-cut categories and `dispatch_stopped_reason`; fix the cause, create/use the failed-or-pending retry manifest |
| `pending` | Resume the existing batch within its recorded bounds |
| `complete` | Verify ledger-owned files and destination, then deliver |

Use `next_action` with the evidence in `items`, including `output_sha256` and PNG dimensions. Include `output_sha256` in each QC record to bind the review to the actual artifact; mismatches are rejected. Older records without a hash remain compatible but lack that explicit review binding. Parallel workers own disjoint outputs and ledgers. Successful outputs are hash-verified on resume and never regenerated just to restart a batch.

`auto` is risk-based, not always-on: review when at least one reference/input image exists, an edit/product/promotion is requested, or the user asks for review. For simple text-only work skip Vision analysis and regeneration; mark `simple_text_only`. The user's saved `off` setting disables visual review; still validate artifacts and report that visual acceptance was not checked. Follow the [QC rubric](references/production-workflows.md#post-generation-vision-qc) for required axes and thresholds. Inspect contact sheets for series consistency, then full-resolution originals for uncertain identity, text, labels, seams, and fine details. Never invent QC scores.

Repair the smallest failed visual requirement and regenerate only the failed cut from immutable originals. Fix rendered text by regeneration, not text overlays. Keep passing cuts. A shared lane failure stops new dispatch; do not hammer a rate-limited or unauthenticated provider. For moderation rejection, use a policy-compliant prompt revision only where the intent permits; do not disguise disallowed intent or switch providers to evade a refusal.

## Evidence and delivery

Only the current successful session's unambiguous artifact is eligible for transport. PNG validation checks its signature, chunks, CRC, dimensions, and stable byte identity; it does not decode pixels or establish visual quality. Creative publication uses the manifest and verified ledger, ignoring unrelated PNGs. Apparel selection must match the current source contract and Vision report; publication must include the complete expected inventory. Preparation JSON, `awaiting_pilot_qc`, and pending ledgers are intermediate states.

Keep `observed_model` and `model_identity_attested` unset without returned evidence; never turn a requested label into an attestation. Deliver the actual supported file attachment or native image preview; printing the path is not delivery evidence. State the delivered count/location, required QC result, and any measured deviation briefly. If blocked, name the exact unfinished stage and keep verified outputs available for resume.

Never use private endpoints, DOM automation outside an explicitly selected supported browser workflow, cookie extraction, or silent provider fallback. API-key billing is prohibited except an explicitly approved Alibaba Token Plan lane. Never fall back to another provider after failure. Follow the host's available tools and permissions; do not invent capabilities from a reference repository.

For maintenance and limitations read [reliability and scaling](references/reliability-and-scaling.md) and [Astra design notes](references/astra-orchestration.md). Run `npm test` and regenerate installed host overlays after canonical changes. Public release remains a separate authorized action.
