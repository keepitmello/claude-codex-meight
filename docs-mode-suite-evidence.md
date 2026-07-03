# docs-mode-suite Evidence

## Goal And Scope

Update the dispatcher skill, worker skill, and docs to the fixed mode/report/
question-routing contract without touching runtime Python files.

Allowed source/docs files changed:

- `skills/meight/SKILL.md`
- `skills/meight-worker/SKILL.md`
- `CLAUDE.md`
- `AGENTS.md`
- `README.md`
- `SPEC.md`
- `ARCHITECTURE.md`
- `docs/README.ko.md`

Additional requested artifact:

- `docs-mode-suite-evidence.md`

## Per-File Summary

- `skills/meight/SKILL.md`: rebuilt as dispatcher-facing SSOT for required
  modes, supervised dispatch, decision reports, structured questions, blind
  consults, review workflow, worker capabilities, and daemon caveats.
- `skills/meight-worker/SKILL.md`: rebuilt as worker-facing SSOT where the
  harness preamble declares mode; added structured QUESTION and decision report
  rules.
- `CLAUDE.md`: slimmed to role split, routing, safety rules, quick reference,
  question routing, consult doctrine, and pointer to the dispatcher skill.
- `AGENTS.md`: rewritten for Codex-as-orchestrator use with same-model
  fresh-context review language and lowercase global config path.
- `README.md`: updated product overview, quick start, consult section, command
  reference, mode/report/raw options, and state files.
- `docs/README.ko.md`: updated as faithful Korean translation of the README.
- `SPEC.md`: added required mode/report CLI contract, decision state files,
  status schema fields, structured question parsing, and decision schema.
- `ARCHITECTURE.md`: added design rationale for enforced mode, decision reports,
  structured routing, blind consults, and independent fresh-context review.

## Judgment Calls

- Kept `skills/meight/SKILL.md` as the full dispatcher-facing SSOT and made
  `CLAUDE.md`/`AGENTS.md` thin drop-in prompts to reduce future drift.
- Treated existing root-level evidence markdown files as out of scope. They
  make a broad cwd-wide banned-string scan noisy, so verification was also run
  against the requested source/docs files only.
- Did not read or edit runtime Python files. A parallel worker already had a
  runtime diff in the worktree.

## Verification

- PASS - Scoped banned-string scan returned zero matches for the requested
  source/docs files.
- PASS - Start/dispatch example scan showed every command example in README,
  Korean README, dispatcher skill, CLAUDE prompt, AGENTS prompt, and SPEC uses
  `--mode`.
- PASS - Structured QUESTION format appears identically in SPEC, dispatcher
  skill, and worker skill.
- PASS - Decision schema fields appear in SPEC, dispatcher skill, and worker
  skill.
- PASS - `git diff --check` passed for all changed docs/skill files.
- NOT_RUN - Runtime/daemon checks were intentionally skipped because this
  docs-only brief forbids running meight against the live daemon.

## Open Risks

- Broad root-level scans that include unrelated historical evidence markdown
  files still find old absolute paths and names. Those files were outside the
  requested edit scope.
- Runtime behavior depends on the parallel implementation worker's Python
  changes matching this documented contract.
