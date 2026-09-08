# ImgGen2 — Hermes install

This directory is the Hermes install payload of ImgGen2. **The canonical root payload is the Hermes-native surface**, so this overlay consists of this note alone — there are no migrated files.

- Skill entry point: `SKILL.md`
- Install location: `~/.hermes/skills/ImgGen2` (companion MPW: `~/.hermes/skills/prompt-writing/MPW`)
- Hermes-native tooling referenced by the skill: `vision_analyze` (follows `auxiliary.vision`), the explicit-only Grok route gated on `xai-oauth` + native xAI `image_generate`
- Canonical source and docs: https://github.com/HeiTuz/ImgGen2

This tree is an install artifact. Make changes in the canonical repository and reinstall via the unified installer (`imggen update`).
