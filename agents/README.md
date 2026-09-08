# agents/ — per-host distribution overlays

This folder holds the **per-host install overlays** for ImgGen2. The repository root (SKILL.md + references/ + scripts/ + contracts/ + examples/) is the single canonical source; each host folder carries only the minimal migrated entry/instruction surface for that host — never a full repository fork.

## Install model

```
installed payload = canonical allowlisted tree + agents/<host>/ overlay (same-named files replaced by the overlay)
```

- The installed tree never contains the `agents/` folder itself — only the chosen host's overlay is applied, so every install has exactly one skill entry point: `SKILL.md`.
- An overlay may only change the **host-integration surface**: frontmatter, invocation notes, tool-name mapping, entry framing. The skill's actual rules and behavior stay identical to the canonical source.
- All relative references (`references/`, `scripts/`, `contracts/`, `examples/`) must remain valid after install.

## Host folders

| folder | contents |
|---|---|
| `hermes/` | Thin note only. **The canonical root payload is the Hermes-native surface**, so no migration is needed. |
| `claude/` | Claude Code entry surface (`SKILL.md`): description-match invocation, Bash/Read tool mapping, host-default Vision = Claude's native image understanding, Grok route explicitly fails closed on this host. |
| `codex/` | GPT/Codex entry surface (`SKILL.md`): skills-directory discovery, shell tool mapping, host-default Vision = Codex native image input, Grok route explicitly fails closed on this host. |

## Why `agents/<host>/` — convention survey evidence (2026-07)

A survey of five comparable public multi-agent skill/installer repositories (oh-my-hermes, tw93/Waza, higgsfield-skills, god-tibo-imagen, master-prompt-writer) found **no stronger public convention** for distributing per-host payload variants: all of them ship a single canonical payload, at most adding root-level instruction files (`AGENTS.md`, `CLAUDE.md`, `INSTALL_FOR_AGENTS.md`). Since the `AGENTS.md` standard makes "agents" the de-facto name for agent instruction surfaces, `agents/<host>/` is the most self-describing umbrella that does not collide with existing roots. MPW uses the identical convention.

## Local installation and public release

Installed trees are generated artifacts. Edit the canonical source, synchronize host overlays, run `npm test`, regenerate the intended installations, and verify their payloads. Leave the required handoff and state whether changes are uncommitted. Local installation verification can complete without a public release.

Version bumps, pushes, and release publication need separate authorization under the root AGENTS.md. An upstream `imggen update` can replace unpublished local changes; preserve the canonical diff and handoff. When a release is authorized, verify the published version, installer, CI, and advertised live route before claiming release completion.

## Sync rule (drift prevention)

The rule body of `agents/*/SKILL.md` tracks the canonical `SKILL.md`. When the canonical file changes, update each host SKILL.md body to match; host differences stay confined to frontmatter (`host_surface`, `canonical_source`) and the leading "Host integration" block. Host files must not be byte-identical to the canonical file (the migration must be real) and must not diverge in rules (behavior must stay identical).
