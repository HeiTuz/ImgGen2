---
name: ImgGen2
description: "Generate or edit image files; not for writing prompts alone. Use the Codex subscription route or an explicitly named provider for single images and exact-N batches. Claude Code host surface."
version: 1.14.2
author: HeiTuz
license: MIT
platforms: [linux, macos, windows]
metadata:
  host_surface: claude
  canonical_source: "HeiTuz/ImgGen2 SKILL.md v1.14.2"
  tags: [image-generation, image-editing, chatgpt]
  category: creative
---

# ImgGen2 (Claude Code surface)

> **Host integration — Claude Code.** This file is the entry surface for Claude Code installs (`~/.claude/skills/ImgGen2`). The rules below are identical to the canonical SKILL.md; only the host-integration surface (frontmatter, invocation notes, tool naming) is migrated.
> - **Invocation**: Claude Code loads this skill by frontmatter `description` match. `scripts/*.py` commands run through the Bash tool.
> - **Vision QC tool**: the "host's default Vision tool" on this host is Claude's native image understanding — read the artifact with the Read tool and apply the QC rubric linked from the execution reference. No separate reviewer model is pinned.
> - **Grok route**: explicit Grok requests use `scripts/grok_cli_transport.py` with the official Grok CLI native `image_gen` / `image_edit` tools. Require an existing working CLI login. Read the routing contract; never substitute another provider or extract credentials.

Generate, inspect, and deliver the requested images. Codex remains the default image route; provider-specific requests follow the workflow table below. Complete the authorized workflow through generation, required QC, targeted recovery, and actual file delivery. A plan, dry-run, task specification, process ID, or successful transport alone is not a completed image request.

## Invariants for every request

- The explicit generation request authorizes its bounded execution, including the pilot and justified failed-cut retries, without a second confirmation. A dry-run checks paths, ownership, and capabilities; it is not a permission checkpoint. Ask only when missing information materially affects identity, rights, cost, destructive changes, or a required deliverable. Researching or improving this skill alone does not authorize a paid or subscription image-generation test.
- N separate images require exactly N independent jobs; a grid requested as a grid is one artifact. Preserve accepted cuts, source locks, and count when the user changes one requirement.
- Inspect references before describing them and lock only observed identity/product details, bound into every cut; a filename or prompt claim is not visual evidence. Independent cuts, retries, and batch items start from the immutable original reference; a cumulative edit retry uses the last accepted base, never the failed candidate.
- For human proportions use the user's numbers first, then an available `references/full-body-calibration.local.md`, otherwise natural proportions from the reference.
- Dry-run first, then execute within the same request. Repair the smallest failed visual requirement and regenerate only the failed unit; keep passing cuts; a shared lane failure stops new dispatch.
- `auto` is risk-based, not always-on: review when at least one reference/input image exists, an edit/product/promotion is requested, or the user asks for review. For simple text-only work skip Vision analysis and regeneration; mark `simple_text_only`. Never invent QC scores.
- Keep `observed_model` and `model_identity_attested` unset without returned evidence; never turn a requested label into an attestation. Deliver the actual supported file attachment or native image preview; printing the path is not delivery evidence.
- Never use private endpoints, DOM automation outside an explicitly selected supported browser workflow, cookie extraction, or silent provider fallback. API-key billing is prohibited except an explicitly approved Alibaba Token Plan lane. Never fall back to another provider after failure. Keep the user's configured model and settings; the active model's name does not identify the image generator.

## Choose one workflow

| Request | Executor and required reading |
| --- | --- |
| One new image or edit | `scripts/codex_subscription_transport.py`; [execution contract](references/execution-contract.md) |
| Exact-N independent images, reference series, or product set | `scripts/codex_subscription_batch.py`; [batch contract](references/batch-production-contract.md) and the matching section of [production workflows](references/production-workflows.md) |
| Text-only ideation/reference-board | `scripts/creative_batch.py`; production workflows, “Production batch” |
| Portable MPW handoff | `scripts/consume_image_handoff.py`; production workflows, “Portable compiled handoff” |
| Identity grid or full-body series | Production workflows, portrait grids, full-body variation, and Vision QC sections |
| Product references or apparel folder | Production workflows, product-photo dispatcher and apparel sections; [folder case](references/cases/apparel-ghost-cut-folder-batch.md) |
| Explicit Grok / 그록 / xAI | [Grok routing](references/grok-oauth-explicit-routing.md); official `grok` CLI on Codex/Claude, native OAuth tool on Hermes |
| Explicit Wan / Alibaba image | `scripts/alibaba_token_plan_transport.py`; production workflows, “Direct-native media routing” |
| Explicit HappyHorse video | Configured Hermes Alibaba adapter; production workflows provider contract |
| Explicit browser workflow | [browser-backed editing](references/browser-backed-image-editing.md) |
| Explicit Higgsfield / Midjourney | The provider's own skill |

Do not load unrelated provider or apparel instructions into ordinary image requests.

## Read by stage

Load the row for the current stage together with the workflow row above; skip the rest.

| Stage | Read |
| --- | --- |
| Before the first call: brief, model selection, steering, prompt and reference locks, dimensions | [orchestration and prompting](references/orchestration-and-prompting.md) |
| Running a helper, reading `batch-summary.json`, Vision QC, retry | [execution, review, and recovery](references/execution-review-recovery.md) |
| Before claiming completion: artifact eligibility, reporting, closed routes | [evidence and delivery](references/evidence-and-delivery.md) |
| Maintenance and limitations | [reliability and scaling](references/reliability-and-scaling.md); run `npm test` and regenerate installed host overlays after canonical changes; public release is a separate authorized action |
