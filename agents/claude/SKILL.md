---
name: ImgGen2
description: "Generate and edit images through the default official Codex CLI subscription route, with provenance-safe single-image transport, resumable exact-N batches, independent QC, and an optional dynamic apparel full-set workflow. Claude Code host surface: the optional Grok route requires Hermes-native tooling and stays disabled on this host."
version: 1.11.0
author: HeiTuz
license: MIT
platforms: [linux, macos, windows]
metadata:
  host_surface: claude
  canonical_source: "HeiTuz/ImgGen2 SKILL.md v1.11.0"
  tags: [image-generation, image-editing, chatgpt]
  category: creative
---

# ImgGen2 (Claude Code surface)

> **Host integration — Claude Code.** This file is the entry surface for Claude Code installs (`~/.claude/skills/ImgGen2`). The rules below are identical to the canonical SKILL.md; only the host-integration surface (frontmatter, invocation notes, tool naming) is migrated.
> - **Invocation**: Claude Code loads this skill by frontmatter `description` match. `scripts/*.py` commands run through the Bash tool.
> - **Vision QC tool**: the "host's default Vision tool" on this host is Claude's native image understanding — read the artifact with the Read tool and apply the QC rubric below. No separate reviewer model is pinned.
> - **Grok route**: the explicit-only Grok route requires the Hermes-native xAI `image_generate` tool plus `xai-oauth`. Neither exists on Claude Code, so an explicit Grok request always fails closed as `grok_route: disabled` — never substitute Codex or another provider for it.

Generate and materialize direct/native media. Codex remains the default ordinary image route. Explicit `Grok`/`xAI` requests use the existing OAuth-gated native lane; explicit `Wan`/`Alibaba` requests use a configured Hermes-native Alibaba adapter (Wan for images, HappyHorse for video). Higgsfield and Midjourney belong to Renderline, not this skill. ImgGen2 proves transport and emits artifacts; Renderline owns final visual QC, comparison, selection, and repair decisions. MPW may help write prompts, but is never a required pipeline gate.

## Capabilities

- text-to-image, edits, and two-to-four reference compositions;
- dry-run-first transport with exclusive output creation and session-scoped artifact provenance;
- resumable JSONL batches with a sequential pilot, bounded fan-out, ledger ownership, selective retry, and independent QC reconciliation;
- explicit-only Grok image generation through Hermes native `image_generate`, gated on `xai-oauth`, with exact-N queueing that starts at 3 active jobs and never exceeds 5;
- risk-based post-generation QC through the host's default Vision tool in `auto` mode for reference/edit/product/promo work, with simple text-only generation skipping the visual loop;
- optional apparel full-set preparation: colors stay product metadata while `candidate_attempt_count` independently defaults to three complete candidate attempts, followed by default mixed per-cut selection across attempts at a minimum 80% family-similarity gate; an explicit `selection_mode: whole-set` keeps one coherent candidate set.

Never use private endpoints, DOM automation, cookie extraction, silent provider fallback, or a model claim not supported by returned evidence. **API-key billing is prohibited except for an explicit, user-approved Alibaba Token Plan quota/billing lane.** Reuse only the credential already owned by the configured Hermes provider; never print, copy, move, or create a key. An `XAI_API_KEY` alone never enables the HeiTuz Grok route. ImgGen2 verifies transport and materialization; Renderline owns final visual QC and selection. Never turn a requested label into an attestation: `observed_model` and `model_identity_attested` stay unset unless supported evidence exists. For delivery, use a supported file attachment; printing the path is not delivery evidence.
Never fall back to a different generation provider when the selected route fails.

## Boundaries

- A successful transport proves only that an artifact was obtained; it does not prove visual acceptance or a particular model identity.
- An explicit user request to create images authorizes the bounded generation scope. `--execute` runs it without a second confirmation or approval-marker ceremony. Fresh approval is required only for scope/count expansion, provider or paid-route changes, overwriting originals, or external publication/delivery.
- The presence of xAI credentials never changes routing. Bare image and exact-count requests stay on Codex. Grok activates only on explicit provider intent and fails closed as `grok_route: disabled` when `xai-oauth` or the native xAI `image_generate` tool is unavailable.
- Product-photo candidate tasks use the standard ImgGen2 generation backend. Every attempt receives the same complete source inventory, product specification, QC contract, and output inventory while keeping output roots and ledgers disjoint.
- A path from another operating system is not a local file. Never guess `/Users/...` as `C:\\Users\\...` or map a foreign home directory by username. Require file transfer/re-attachment or a real local/UNC path. Only deterministic WSL mount mappings such as `/mnt/c/...` may be converted automatically.
- On Windows, accept drive-letter paths, UNC shares, spaces, Unicode, and local `file://` URIs. Reject reserved device names, trailing dots/spaces, credential-bearing file URIs, and symlink/junction/reparse traversal. Use the standard extended-length prefix for long absolute paths instead of silently relocating them.

## Core procedures

When the user explicitly asks for an in-app or authenticated browser workflow, follow [references/browser-backed-image-editing.md](references/browser-backed-image-editing.md). The browser lane must verify both protected-source materialization and the actual composer attachment before any generation prompt is submitted; successful clicks, paste events, or a visible send button are not sufficient evidence.

### Single image or edit

```bash
python scripts/codex_subscription_transport.py \
  --prompt "A blue ceramic cup on natural linen"

python scripts/codex_subscription_transport.py \
  --prompt "Keep the subject; change only the background to warm gray" \
  --image "$PWD/input.png" \
  --output "$PWD/output/edited.png"
```

Both commands remain dry-runs unless `--execute` is supplied. The user's explicit generation request authorizes that bounded invocation; no additional marker is required. See [references/execution-contract.md](references/execution-contract.md).

### Multi-panel portrait grids and aspect-ratio recovery

For a reference-backed identity turntable/contact sheet, treat the grid as **one generated artifact**, not nine separate calls. Bind the reference image and state the exact panel order in reading order; lock immutable identity cues (facial geometry, asymmetries/marks, hairline, hair length/style, garment) separately from the deliberately varying rotation angle.

When the user requests a non-square overall canvas for a 3×3 grid, say both parts explicitly: `the final canvas is a vertical 3:4 rectangle, not a square image` and `the canvas is fully filled by a 3-column × 3-row grid of equal vertical portrait panels`. A bare trailing `AR 3:4` can be underweighted by image generation. Post-generation verification must inspect actual pixel dimensions, not prompt intent. If a reference-backed grid comes back square despite a requested 3:4 canvas, regenerate with the stronger whole-canvas and panel-geometry wording; do not fake compliance by padding or cropping a square result.

For a 9-angle beauty turntable, a reliable reading order is: front, left 3/4, full left profile, left rear 3/4, full back, right rear 3/4, full right profile, right 3/4, front. QC verifies each requested angle is visibly distinct and that rear views preserve the front-view hair part, length, texture, neckline, and garment continuity.

### Explicit Grok OAuth route

Use Grok only when the current request explicitly says to generate or edit the image with `Grok`, `그록`, or `xAI`. Require a configured Hermes `xai-oauth` credential and the Hermes-native xAI `image_generate` tool in the current session. API-key-only environments do not qualify. If either gate is absent, stop without login, token inspection, or fallback.

Do not invoke Grok through `hermes chat`, `progrok`, browser cookies, or a new private API client. A single request calls native `image_generate` once. An exact-N request creates N independent jobs, runs one pilot through local materialization, hash verification, and QC, then fans out from 3 active jobs to a maximum of 5 while queueing the remainder. Failed-job-only retries never overwrite or repeat verified successes. Full contract: [references/grok-oauth-explicit-routing.md](references/grok-oauth-explicit-routing.md).

### Portable compiled handoff

Direct prompt invocation remains fully supported and does not require another skill. An installed `MPW` compiler may instead emit `image-production-handoff/v2` JSON. Consume it without host-specific routing:

```bash
python scripts/consume_image_handoff.py request.json \
  --output-root "$PWD/generated"
```

This adapter validates [contracts/v1/image-production-handoff.schema.json](contracts/v1/image-production-handoff.schema.json), resolves relative input paths from the handoff file, keeps the output under `--output-root`, and delegates to the same dry-run-first transport. HTTPS input references must first be materialized as relative local files. The handoff must never contain credentials, approval state, session identifiers, or machine/worker routing.

### Production batch

Compile a self-contained prompt per cut, prepare a JSONL manifest, then dry-run:

```bash
python scripts/codex_subscription_batch.py \
  --manifest "$PWD/jobs.jsonl" \
  --output-root "$PWD/product-batch" \
  --workers auto
```

The first cut is always a sequential transport pilot. If that job requires visual QC, bounded fan-out begins only after its independent QC passes. A simple text-only pilot with no references, product-photo correction, promotional layout, or explicit review request skips Vision QC and continues in the same pass. The batch owns an atomic ledger; resume is hash-verified against ledger-owned outputs, and failures become a fresh retry manifest. Parallel workers may only own disjoint output roots and ledgers. `--batch-dir` on the single-image helper is still one image call. Read [references/batch-production-contract.md](references/batch-production-contract.md) before batch work.

For bulk ideation/reference-board requests, use `scripts/creative_batch.py`. It invokes MPW once to compile distinct prompt variations, keeps Vision QC off even for 100+ text-only ideas, stages manifests/ledgers/summaries in a hidden resumable workspace, and publishes only final PNGs. Successful runs delete the workspace; failed or interrupted runs retain it for resume. `examples/batch_100_variations.py` is the reusable cross-platform entrypoint, and the packaged presets in `examples/` (including the ecommerce set: hero, thumbnail, detail close-up, color variants, lifestyle, seasonal banner, bundle, beauty, food, home/living, apparel catalog) are thin text-only wrappers over `examples/preset_runner.py`. These presets never accept reference images and must not be presented as product-photo fidelity work.

### Moderation refusals and rejected-cut recovery

A moderation refusal exits the CLI cleanly with no artifact; the transport classifies it as `category=moderation_rejected` instead of a generic missing-PNG failure, and batch ledgers record that category per attempt. Recovery is prompt rework, never bypass: rewrite the rejected cut in neutral campaign/editorial language (for example, wet-look or gravure phrasing becomes a clean campaign description; lingerie becomes loungewear framing) while keeping the same subject, layout, and copy intent. Never escalate explicitness, obfuscate intent, or switch providers to route around a refusal. Rejected cuts flow into the standard retry manifest with a fresh ledger; verified successes are never regenerated.

### Text rendering and gpt-image-2 output constraints

Wrong or missing rendered text is fixed **inside the image**, never by post-processing: overlaying corrected text with PIL, ImageMagick, SVG, or any compositor is prohibited because the font, kerning, and tone never match the generated render. Instead, re-render only the failed cut with the copy strings quoted verbatim with role and position, noncritical copy removed, and — for dense text, comics, or fine linework — high quality at `2048x2048`.

The Codex image tool accepts a fixed size set only: `1024x1024`, `1536x1024`, `1024x1536`, `1792x1024`, `1024x1792`, `2048x2048`. Map other aspect ratios to the nearest supported size (16:9 → `1792x1024`, 9:16 → `1024x1792`, 2:3 → `1024x1536`) and verify the delivered PNG's actual pixel dimensions rather than trusting the prompt token. Avoid negative "no …" phrasing — state the desired appearance positively.

### Reference-locked full-body variation series

**Full-body proportion and height targets:** use, in priority order, (a) the current request's own numbers; (b) an optional machine-local calibration overlay at `references/full-body-calibration.local.md` when present (read-if-present; never packaged or installed by the unified installer; personal defaults such as preferred height/head-count live there); or (c) otherwise ask the user once. Bind the numbers to visible controls—long but realistic inseam, natural shoulder/hip/joint proportions, full head-to-toe framing, shoes fully visible, restrained medium-telephoto perspective, and a light contact shadow. Do not fake height by stretching limbs or unnaturally narrowing joints.

When the user asks for N full-body variants of one person from an attached portrait or rotation sheet, this is **not** text-only ideation: use `codex_subscription_batch.py` with the reference in every manifest record and run the pilot-QC gate. A 3×3 face/side/back contact sheet is a valid single identity reference; bind observable locks into every prompt: face geometry and distinctive marks, the hairline, part, length/style, and distinctive loose strands actually observed in the supplied reference, realistic body geometry, requested height/proportion, full head-to-toe framing, and no hand/foot crop. Keep the identity lock invariant while varying only scene, wardrobe, pose, and lighting. Store the same locks in `metadata`/`series_locks` so retry records cannot silently drift. Generate one neutral studio full-body pilot first; after Vision confirms identity, scale, and framing, open fan-out. For final series QC, inspect contact sheets for cross-series drift and use full-resolution single-image review only for ambiguous candidates; then reconcile every accepted ID through the batch QC JSONL before delivery. Do not claim a requested aspect ratio solely from a prompt token—verify PNG dimensions after transport.

### Reference-backed product-photo dispatcher

When the request contains one or more product references and asks for multiple product photos, sets, colourways, detail cuts, or a product batch, **do not compile raw references directly into image calls.** The product-photo lane has four mandatory stages:

1. **Vision intake → immutable `ProductSpec`.** Analyze every reference first and retain only observed evidence: product family, component count, silhouette, relative dimensions, construction, hardware, material/texture, pattern, logo placement, and validated colourways. Unknown or occluded details stay unknown; never invent them. A colourway is product metadata, not new product geometry.
2. **Cut plan + manifest.** Build an exact-N per-cut manifest from `ProductSpec`. Let the product type and buyer-decision evidence determine the mix of hero, angle, functional/context, and detail cuts; one manifest record means one image call, never a collage. Each recognized colourway must appear at least once before repeats when N permits, every cut carries exactly one validated colourway, and no novel/mixed colourway is allowed. User-specified shot order, aspect ratio, lighting, or background overrides the planner.
3. **Per-cut prompt binding.** Every prompt receives the same immutable `ProductSpec` plus only its cut intent and selected colourway. Product geometry—component count, silhouette, proportions, construction, and scale—must stay invariant across all cuts and colourways. Detail-cut intents must name the actual source-supported feature and require a purchase-decision crop, rather than allowing a generic front-product regression.
4. **Vision QC + targeted recovery.** Verify every candidate against both `ProductSpec` and its semantic cut intent: geometry, component count, relative size, exact colourway, material, shot purpose, and requested lighting/background. Preserve passing cuts; regenerate only the failed record using the smallest delta. The final deliverable is one image per cut, labeled only with cut number, colourway, and scene name.

`ProductSpec` is a production handoff, not decorative analysis. It must be attached to every manifest record and retained in the batch ledger/provenance with source evidence. A generic product-photo prompt without this intake/manifest/QC chain is not a reference-fidelity batch.

### Post-generation Vision QC

`auto` is risk-based, not always-on. Invoke the host's default Vision analysis tool when at least one reference/input image exists, the request edits or corrects an existing image, the work is a product-photo correction or product set, the layout is promotional, or the user explicitly asks for review/comparison. On Hermes this uses `vision_analyze`, which follows the live `auxiliary.vision` configuration instead of pinning a reviewer inside ImgGen2. The full original remains the delivery artifact and is never modified.

This lane is execution-time safety validation, not final acceptance: it exists to catch transport, fidelity, and regression defects before fan-out or delivery. Renderline retains final visual QC, comparison, and selection authority for all engines, including artifacts generated here.

For a text-only creation with no reference, edit, product-photo correction, promotional layout, or explicit QC request, skip Vision analysis and regeneration. Still verify the output locally: expected file exists, is non-empty, has the expected image format, and does not overwrite another artifact. Mark this path as `qc_status: skipped` with reason `simple_text_only`.

The installed `vision-qc.json` contains `{version: 2, requested_mode: "auto", qc_mode: "auto", reviewer: "host-default-vision"}` and no credentials. `auto` is the default in interactive and non-interactive installs. `off` is the only alternative and disables visual review even for high-risk cases; local artifact validation still applies.

When QC is required, review the image against the requested brief, source fidelity, text accuracy when applicable, material realism, layout, and cross-image consistency. **For a reference-backed human portrait or identity grid, explicitly inspect identity-bearing anchors across every panel: face geometry, eyes/nose/mouth relationship, hairline and distinctive loose strands, visible marks or natural asymmetry, skin tone, and the requested framing/alignment.** Report panel coordinates for any drift; do not accept a merely attractive grid when it fails same-person recognition. Require a structured result containing the four axis scores, pass/fail, observed defects, and the smallest regeneration delta. Portrait-grid QC may add `identity_consistency` as an optional fifth axis; when supplied it must meet the same 4.0 floor to pass, while the canonical average remains the four required axes. Regenerate only failed required cases and only with the smallest failed-axis delta. The review report records the image hash and dimensions; requested model names are not model-identity evidence.

### Direct-native media routing

| Request | ImgGen2 route |
| --- | --- |
| Ordinary single image or exact-N image batch | Codex subscription default |
| Explicit `Grok` / `그록` / `xAI` image request with `xai-oauth` and native tool available | Grok OAuth; no API-key-only fallback |
| Explicit `Wan` / `Alibaba` image request | Configured Hermes-native Alibaba adapter; `wan2.7-image` default or explicit `wan2.7-image-pro` |
| Explicit `HappyHorse` / `Alibaba` video request | Configured Hermes-native Alibaba adapter; explicit `happyhorse-1.1-t2v`, `happyhorse-1.1-i2v`, or `happyhorse-1.1-r2v` |
| Explicit Higgsfield or Midjourney request | Renderline; never emulate or replace it here |

For an Alibaba lane, prove the installed provider is registered before a paid call; make that one selected route active only for the call/run, then restore the prior default provider exactly. Do not permanently change `image_gen.provider` or `video_gen.provider` without explicit direction. Local source paths are rejected for Wan/HappyHorse whenever the native Bailian endpoint accepts only public HTTP(S) references; never fabricate a URL or upload through an unverified side channel. Return the provider-materialized Hermes cache file and hand it to Renderline whenever QC, comparison, or selection is required.

### Provider routing quick reference

The routing table above is the authority. No selected lane may silently fall back to another engine.

### Apparel full-set preparation

Vision role records may provide explicit `color_identity` values for `color_front` records. Ordinary product folders may instead omit the role map and use the public naming contract: `f1` front, `b1` back, `cN` alternate/color fronts, `dN` details, and `sN` composite-only sources. Colors and candidate attempts are independent: `candidate_attempt_count` defaults to three complete attempts whether the product has one color or many.

Do not infer visual color names from filenames; auto-mapped `cN` values are stable opaque identities. Back/detail evidence does not add attempts. Every candidate task receives the complete source and output inventory. Default selection is mixed: each output cut independently takes the highest-fidelity candidate across attempts that passes support removal, pure white/no shadow, and no invented detail, with fidelity ties resolving deterministically to the lowest attempt index; the final mixed family must still have every pairwise similarity scored and at or above the 80% gate or selection fails closed. An explicit `selection_mode: whole-set` (contract field, Vision-report field, or `--selection-mode whole-set`) keeps one coherent candidate set; unknown or conflicting modes fail closed. Product originals remain outside the run root and are read-only. After verified selection, disposable `candidate-set-*` work directories are deleted automatically and only `selected/` plus minimal provenance remains; this cleanup requires no extra approval. Provenance records the selection mode, the source task/set, hashes, fidelity, and rejected alternatives per cut. Use the observed delegation ceiling as `--runtime-limit`; any over-cap folder is blocked rather than reduced. See [references/cases/apparel-ghost-cut-folder-batch.md](references/cases/apparel-ghost-cut-folder-batch.md).

A folder-path-only request (local or Windows/UNC shared folder) uses the packaged entry point `scripts/folder_batch_prepare.py`. It inventories top-level source images (ignoring ordinary artifacts such as `Thumbs.db` and `desktop.ini`, and excluding `AI_RESULT_*` result subfolders from source inventory), applies the public naming contract including `fN`/`bN` numbered variants and `dN` detail names with descriptors such as `d1_원단`, and fails closed on unknown or conflicting names, symlink/junction/reparse entries, and hidden image files. It writes the validated folder contract, Vision handoff, default apparel-correction prompts/QC contract, and output plan into a private work root outside the source folder and plans a deterministic non-overwriting `AI_RESULT_<timestamp>` result subfolder; `--dry-run` plans without materializing runner task specs, and `--publish-from` publishes a verified `selected/` family into the result subfolder with per-file hash re-verification, staged atomic rename, and a machine-readable `batch-summary.json`. Originals stay byte-identical.

`folder_batch_prepare.py` is preparation only: successful JSON and `task-*.json` creation do **not** mean any image was generated. After preparation, execute the authoritative generation runner, complete the reference-image pilot gate, perform independent Vision QC, apply the pilot QC JSONL, rerun to open fan-out, monitor every bounded process to terminal state, QC/select the complete candidate family, and only then publish with `--publish-from`. A background process ID, `delivered: true`, `awaiting_pilot_qc`, or pending ledger is never a completion result. Do not send a completion-style report while generation, QC, selection, or publication remains pending; label it explicitly as in progress and continue monitoring in the same session whenever possible.

For reference-backed `codex_subscription_batch.py` runs, use this exact gate sequence:

1. dry-run and verify manifest/output ownership;
2. run `--execute` once to generate the sequential pilot;
3. inspect `batch-summary.json` for `awaiting_pilot_qc: true`;
4. Vision-review the pilot and write QC JSONL keyed by the exact pilot `id`;
5. apply `--qc-results` without `--execute` and verify `qc_status: passed`;
6. rerun with `--execute` to generate the remaining records;
7. wait for terminal completion and verify ledger-owned hashes/files before family QC and selection.

### Apparel semantic-cut QC and targeted recovery

Candidate transport success is not semantic cut success. In apparel folders, a `dN` detail job can silently regress into another generic full-front product image even when the file is valid, clean, and visually attractive. QC must therefore verify each output's **shot intent**, not only product identity and background quality:

- `fN` must remain a front cut and `bN` a back cut;
- pocket/waistband details must actually be tight detail crops with the requested source-supported hardware, stitching, and construction visible;
- lining/inner-shorts/underside details must visibly expose the requested internal construction rather than returning a normal exterior front;
- descriptor obligations such as `상품택제거` must be checked per candidate; a sewn-in brand label is not automatically the same thing as a temporary merchandise tag.

If every candidate for one required cut shares the same semantic regression, do not pick the least-bad full view and do not fail the whole family. Preserve passing cuts, then regenerate only the failed cut from originals with a narrow prompt that states both the required view and the forbidden regression (for example, “tight pocket detail, not a full garment front” or “underside inner-shorts construction, not a normal exterior view”). Re-QC that retry against the relevant detail source before selection. Record it in provenance as a targeted retry, and keep final publication atomic through `folder_batch_prepare.py --publish-from`.

For large candidate families, a labeled contact sheet is an efficient first-pass comparison surface, but use individual full-resolution inspection for ambiguous construction, text/labels, edge cleanup, and final targeted retries. Never invent numerical fidelity or family-similarity scores merely to satisfy provenance; scores in `provenance.json` must come from the actual QC/selector report.

See [examples/dint-shared-folder-apparel-batch.md](examples/dint-shared-folder-apparel-batch.md).

## Verification

All verification is network-free:

```bash
python -m unittest discover -s scripts -p 'test_*.py' -v
python -m py_compile scripts/*.py
```

The test suite covers output collision handling, dry-run safety, session provenance, batch resume/retry/QC behavior, explicit-only Grok OAuth routing, API-key-only rejection, exact-N queueing without shrinking, dynamic apparel task count, complete inventory, immutable source hashes, disjoint task paths, missing candidates, mixed per-cut and explicit whole-set 80% selection with deterministic ties, and delegation-cap packing.
