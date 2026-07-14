# Research-Absorption Evidence

## Contract

- Worked against `decisions/2026-07-14-consensus-pipeline-luna-promotion.md` (v3, `STATUS: adopted`), preserving its blind-consult boundary, bounded three-round anchored plan-review loop, separate risk ledgers, frozen versioned `PLAN.md`, and dispatcher sign-off chain.
- Doctrine scope was limited to `skills/meight/SKILL.md` and `skills/meight-worker/SKILL.md`. `absorb-research-evidence.md` is the worker evidence artifact explicitly required by the brief; no runtime, README, ARCHITECTURE, or decision-record changes were made.
- Deviations: none.

## Refinement evidence

1. Reviewer noise suppression is present in both plan-review surfaces:

   > Reviewers must not flag:
   > - naming/style preferences in the plan document itself;
   > - theoretical edge cases that cannot occur with real inputs;
   > - out-of-scope “what about” hypotheticals; or
   > - findings the plan text or a prior round already resolved.

   Source: `skills/meight/SKILL.md:272-276` and `skills/meight-worker/SKILL.md:274-278`.

2. Incremental re-review is tied to the existing risk ledger:

   > From round 2 onward, before raising new findings, the reviewer first dispositions every prior finding as `addressed`, `partially addressed`, or `not addressed`, citing the plan text/evidence that resolved it or explains why it remains open. Record that disposition with the `resolved-risks` half of the round ledger, while `new-risks` contains only new findings; keep the two separate.

   Source: `skills/meight/SKILL.md:277-282` and `skills/meight-worker/SKILL.md:279-284`.

3. Reviewed-input identity and stale-verdict handling are present on the dispatcher side and worker side:

   > Every review verdict must name the exact input reviewed: the `PLAN.md` version for plan reviews, or a commit hash/diff identity for code reviews. Before acting on a verdict, the dispatcher compares that identity with the current artifact and discards the verdict as stale if they no longer match.

   > Name the exact input reviewed in every verdict: the `PLAN.md` version for a plan review, or a commit hash/diff identity for a code review. If the named input no longer matches the current artifact, the dispatcher discards the verdict as stale instead of acting on it.

   Sources: `skills/meight/SKILL.md:374-377` and `skills/meight-worker/SKILL.md:286-289`.

4. The dispatcher plan-review section recommends schema-validated decision reports while preserving exploratory text mode:

   > Run this bounded loop with `--mode delegate --report decision` so `APPROVE`/`REVISE` verdicts arrive as schema-validated decisions; `--report text` remains acceptable for collab-style exploratory reviews.

   Source: `skills/meight/SKILL.md:265-268`.

## Verification

- PASS — `python3 /Users/wy/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/meight` → `Skill is valid!`.
- PASS — `python3 /Users/wy/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/meight-worker` → `Skill is valid!`.
- PASS — `git diff --check` completed with no output.
- FAIL (environmental, non-doctrine) — `python3 -m unittest tests/test_meight.py` ran 4 tests but one errored because the installed environment lacks `openai_codex.generated.v2_all`; the two requested skill validators passed.

## Deliberately not done / residual risks

- Did not change the adopted decision record or propagate this loop-mechanics refinement into README/ARCHITECTURE; those were outside the requested doctrine scope.
- Did not apply the plan-review noise-suppression list to explicit code/diff reviews, because the brief scoped that contract to plan-review roles.
- Did not push the local commit.
