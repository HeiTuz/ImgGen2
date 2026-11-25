# Case Learning and Branching Contract

Use this contract whenever Boss supplies a production example, correction, failed result, successful result, visual reference, or new operating rule for HeiTuz.

## 1. Classify before changing

Assign exactly one disposition:

- `core` — broadly reusable across products/workflows; compatible with existing verified behavior.
- `branch` — applies only under explicit product, genre, platform, client, input-shape, or output-type triggers.
- `evidence-only` — useful observation, but evidence is not yet strong enough to change behavior.
- `no change` — already covered, contradicted by stronger evidence, or irrelevant to this skill's boundary.

Boss's explicit instruction can promote a single case immediately. Otherwise, prefer a branch until repeated evidence supports core promotion.

## 2. Core admission gate

Promote to core only when all are true:

1. the trigger and expected behavior are unambiguous;
2. the rule generalizes beyond the supplied asset;
3. it does not silently weaken transport, provenance, approval, no-overwrite, or QC invariants;
4. conflicting verified workflows remain representable;
5. a relevant fixture, test, or actual output/QC result supports it.

## 3. Branch admission gate

Create `references/cases/<slug>.md` when any is true:

- the rule is conditional on a particular product class, visual genre, client, platform, or source-folder shape;
- it conflicts with another valid behavior;
- it is experimental or based on one visual example;
- it introduces a special prompt recipe, reference mapping, QC rubric, or retry strategy;
- activating it globally could regress unrelated production.

A branch file must contain:

```markdown
# <Branch name>

- Status: experimental | verified | promoted | retired
- Trigger:
- Exclusions:
- Input shape:
- Output contract:
- Reference ownership:
- Prompt/series locks:
- QC additions:
- Retry behavior:
- Evidence:
- Last verified:
```

Activate a branch only when its trigger matches. Never infer a branch from a vague resemblance.

## 4. Conflict and precedence

For task behavior, use this order:

1. Boss's current explicit instruction;
2. a matching verified branch;
3. core defaults;
4. an experimental branch only when Boss explicitly selects it.

Global transport/provenance/approval/no-overwrite invariants remain in force unless Boss explicitly changes that canonical contract. Preserve two conflicting valid cases as separate branches; do not average them into a weak generic rule.

## 5. Evidence handling

- Description-only visual claims stay `experimental` or `evidence-only`.
- Actual generated outputs plus QC can mark a branch `verified`.
- Failed examples must record the observed defect and the narrow corrective delta; never rewrite the whole prompt from one failure without evidence.
- Keep private product/client details out of generic core wording. Store only the minimum trigger/evidence needed.

## 6. Change report and verification

For each supplied case, report:

```text
Disposition: core | branch | evidence-only | no change
Trigger: <when it applies>
Changed: <files/rules>
Verified: <test, fixture, or visual evidence>
Conflict: <none or preserved branch>
```

Make the smallest canonical change, update or add the relevant fixture/test, and verify the loaded skill. Do not claim a visual rule verified when no image was inspected.
