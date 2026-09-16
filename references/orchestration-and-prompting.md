# Orchestration and prompting

Read this before the first generation call of a request. It carries the working detail behind the entry `SKILL.md` invariants: model selection on the current transport, the production brief, steering, and prompt/reference construction.

## Work with the active orchestrator

This skill is tuned for sustained instruction following and tool use and works with any host model. The active model coordinates the work; its name does not identify the image generator. Keep the user's configured model and reasoning settings. Do not pin a model into the image transport or change global settings to use this skill.

When the active image tool exposes GPT Image 2.5 model selection, preserve the user's explicit model request; otherwise use `gpt-image-2.5-flare` for fast, high-quality everyday generation and `gpt-image-2.5-sunburst` when precise edits or demanding quality are the priority. The current Codex subscription helper exposes no model, quality, or size selector: do not invent CLI flags, API requests, or a model identity claim. If the tool does not expose this choice, let it select the supported route and leave model attestation unset. The API's newer model, quality, size, format, and compression parameters are API capabilities, not evidence of CLI support. See the [official image generation](https://developers.openai.com/api/docs/guides/image-generation) and [image prompting](https://developers.openai.com/api/docs/guides/image-prompting) guides.

Start from the user's intent and inspect available references. Form one compact production brief: subject, intended use, exact count, composition/canvas, visual direction, immutable details, permitted variation, required text, and destination. Fill low-risk omissions with coherent defaults and proceed. Ask only when missing information materially affects identity, rights, cost, destructive changes, or a required deliverable. Do not make the user approve a prompt merely because it was expanded.

The explicit generation request authorizes its bounded execution, including the pilot and justified failed-cut retries, without a second confirmation. A dry-run checks paths, ownership, and capabilities; it is not a permission checkpoint. Additional authorization applies only to actions outside the already authorized scope. Researching or improving this skill alone does not authorize a paid or subscription image-generation test.

Respect steering during execution. Preserve accepted cuts, source locks, and count when the user changes one requirement. Use subagents only when permitted by the host and when independent work benefits; never create user-visible tasks for internal fan-out. Simple one-image work stays local. Keep all long-running calls attached to their returned session IDs until terminal state.

MPW is optional for direct prompts; the creative-batch helper uses its variation compiler. A nine-panel grid is one artifact when requested as a grid; N separate images require exactly N independent jobs.

## Build prompts that survive a batch

Use short, self-contained prompts with the concrete visual result first. Bind source-observed identity/product facts separately from the changing scene or shot. State one composition, one lighting treatment, relevant material/texture cues, and the required framing. Quote rendered copy exactly, with its role and position. Avoid stacks of generic quality adjectives and contradictory aesthetic instructions.

For references, inspect the images before describing them. Lock only observed details: face geometry and marks, hair, product silhouette, construction, material, component count, logo placement, and valid colourways. Preserve unknown or occluded details as unknown. Store those locks in the manifest metadata and bind them into every cut; a filename or prompt claim is not visual evidence. Product sets require the immutable ProductSpec, exact cut plan, per-cut binding, and semantic QC in [production workflows](production-workflows.md).

Keep edit lineage explicit. In a cumulative conversational edit, use the latest accepted or user-selected image as the next input; a cumulative retry uses that last accepted base, never the failed candidate. Independent cuts, retries, and batch items always start from the immutable original reference. See the [execution contract](execution-contract.md) for the lineage boundary.

For human proportions use the user's numbers first, then an available `references/full-body-calibration.local.md`, otherwise natural proportions from the reference. Avoid compulsory measurement questions. For details, name the source-supported feature and intended crop so the model cannot satisfy a detail request with another generic front view.

The Codex subscription helper has no size/quality flags. Express the requested dimensions and ratio in the prompt and verify actual PNG dimensions. Use the portable handoff dimension check for exact requirements. Never silently substitute a nearby ratio, stretch anatomy, pad/crop away a mismatch, or claim compliance from prompt tokens.
