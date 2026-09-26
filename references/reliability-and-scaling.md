# Batch reliability and scaling review

## 2026-09-10: single-image reference integrity

The Codex single-image transport now fingerprints reference bytes and file identity before execution and checks them again when the CLI returns. A changed, replaced, deleted, or unreadable reference is rejected with `reference_changed` before artifact selection or delivery. Dry-run and success summaries include `reference_sha256`; no image format restriction or provider call is added by fingerprinting. Existing batch admission control already stops on this category. This detects changes visible at the checks, not a complete history of every concurrent write. Live image quality was not benchmarked.

## Batch runner design decisions

| Area | ImgGen2 behavior and reason |
| --- | --- |
| Workers and concurrency | Each image runs in its own CLI invocation, and concurrency grows through a success-driven ramp. An explicit hard cap and a conservative resource fallback bound the pool, and a bounded future window limits outstanding work. |
| Shared-lane failures and child isolation | A bare 429 is classified as a rate limit. Child processes run with `stdin=DEVNULL`, and the generation instruction tells the worker to end after generation without shell work or moving artifacts. Regression tests cover these. |
| Artifact collection | A session-ID filter and exclusive copy bind each image to the worker that requested it. A global claim lock would prevent duplicate collection but would not establish that binding. |
| Resume | The ledger owns outputs, records hashes, gates on pilot QC, and retries only failed or pending jobs. Existing files alone do not prove a successful prior job. |
| Aspect ratio and size | Per-record ratio and size are compiler metadata; the constraints must be present in the compiled prompt. Dedicated native size options are not added or claimed. The portable handoff checks requested dimensions after transport. |

Fixed model-size lists, fixed account rates and latency estimates are not treated as current capability evidence. The three ImgGen2 skill surfaces make no fixed-size or nearest-ratio assertion; they follow the actual helper and its dimension-verification contract. Global process-kill recipes and unrestricted sandbox flags are not part of runtime behavior.

## GitHub sources and decisions

Reviewed on 2026-09-08. These are implementation references, not additional generation providers or dependencies.

| Primary source | Observed pattern | ImgGen2 decision |
| --- | --- | --- |
| [OpenAI imagegen sample](https://github.com/openai/codex/blob/4b0f44d3046f5212e618d0b5fb5225a2f1988989/codex-rs/skills/src/assets/samples/imagegen/scripts/image_gen.py#L600-L725) | Dry-run precedes client creation; semaphore limits concurrent image calls; per-job failure and fail-fast paths are distinct. | Keep planning isolated from live state and distinguish shared-lane failures from per-cut failures. Do not import the sample's API-key route or size controls into the subscription transport. |
| [CPython bounded queue](https://github.com/python/cpython/blob/23180c50082fe98784c78511b335d7274ed87fb7/Lib/asyncio/queues.py#L125-L154) | A full bounded queue holds back producers rather than admitting all work. | Keep at most the worker target in outstanding futures and replenish as calls finish, using the existing synchronous executor. |
| [OpenAI Python retry policy](https://github.com/openai/openai-python/blob/be928151372e4b62adb4a1571cda52ad759b38be/src/openai/_base_client.py#L791-L813) | Retry delays are bounded and account for server instructions and jitter. | Keep failure categories explicit, but do not transplant HTTP retries into CLI image generation: a timeout is not proof that generation never occurred. No automatic transport retry was added. |
| [Codex cancellation and task draining](https://github.com/openai/codex/blob/4b0f44d3046f5212e618d0b5fb5225a2f1988989/codex-rs/code-mode-runtime/src/cell_actor/callbacks.rs#L44-L92) | Cancellation is propagated and outstanding work is drained. | Stop batch admission on a shared-lane failure, let active calls settle, and retain pending jobs. Cross-platform subprocess-tree cancellation remains a separate future change. |

## Implemented behavior

- Creative dry-runs copy an existing compiled manifest into temporary scratch. They never delete or mutate a retained live workspace, including on preflight failure. A nonempty final destination is rejected before live compilation or generation.
- JSONL is read line by line and the canonical manifest digest is updated incrementally. Jobs remain materialized for ordered ledger ownership; memory is not constant in job count.
- A manifest-local reference cache hashes each unchanged shared file once. It checks device, inode, size, mtime and ctime around hashing, on reuse and at load completion. There is no cache across invocations. This conservatively rejects even metadata changes during loading and preserves resume drift detection.
- Outstanding futures are bounded by the worker target. This is additional to the existing semaphore ramp; it avoids allocating a future per pending image.
- Rate limits, authentication, entitlement, unavailable model/tool and CLI argument failures stop new dispatch. Already active calls settle; jobs not started remain pending with zero attempts. `dispatch_stopped_reason` is included in JSON summaries. Moderation failures remain local to the affected cut.
- Existing retry manifests include failed and unstarted jobs while excluding verified successes. No provider fallback, new dependency, generation-model selection, or public schema/version change is introduced.

## MPW integration

The installed MPW 2.28.0 declares `name: mpw`; the old resolver looked for the literal uppercase text `name: MPW`, making valid installs invisible. The resolver now validates an exact top-level frontmatter name case-insensitively (including quoted names), rejects body-only mentions or duplicate names, and reports invalid overrides through `MpwPromptError`. A real local MPW compilation and Codex CLI version preflight verifies this path without generating images. Previously skipped MPW contract-mirror checks also run again.

## Local evidence

The focused tests cover scratch preservation on success/error, destination preflight, digest reuse and mid-load mutation, identical canonical hashes, bounded futures, all six stop categories, successful-image preservation through retry, and continued processing after per-cut moderation failure. Existing pilot/QC and resume tests remain in place.

A synthetic local manifest-load measurement used 1,000 jobs, one shared 4 MiB reference and roughly 4.6 KiB of prompt text per job, with Python tracemalloc enabled:

| Metric | Before | After |
| --- | ---: | ---: |
| Shared reference file reads | 1,000 | 1 |
| Manifest load | 1.7245 s | 0.3114 s |
| Traced peak allocations | 22.750 MiB | 12.592 MiB |

Both implementations produced the identical canonical manifest hash. These figures measure one local preparation run, not image-generation speed, process RSS, or a cross-platform performance guarantee. No live image-generation call was used for validation.
