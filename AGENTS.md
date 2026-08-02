# AGENTS.md — repository operating rules

This repository is the canonical editable source for ImgGen2. Codex owns edits and local commits in `~/HeiTuz/ImgGen2`; Claude Code and Hermes consume installed payloads and must not edit or commit in their install paths. The Codex install at `~/.codex/skills/ImgGen2` is a copied `agents/codex/` overlay artifact, not a second source of truth.

After a canonical change, regenerate the relevant host payloads and verify overlay parity. Version bumps and release pushes are separate release actions; do not push without explicit release approval. Do not edit `~/src/MPW-release`, remove skills, or change contracts/schema/mirrors without the approval boundary in the task brief.

The repository root (`SKILL.md`, `references/`, `scripts/`, `contracts/`, and `examples/`) is the behavioral source. `agents/<host>/` changes only host integration framing and must not fork the rules. Run the repository's documented verification commands after changes.
