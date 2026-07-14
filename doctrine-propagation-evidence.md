# Doctrine propagation evidence

Date: 2026-07-14 (Asia/Seoul)

## Goal and scope

Propagate the adopted v3 operating model plus amendment from
`decisions/2026-07-14-consensus-pipeline-luna-promotion.md` across the six
contract surfaces named by the brief, and answer whether the pinned SDK and
current meight path support `luna xhigh` with Fast.

Changed doctrine surfaces:

- `skills/meight/SKILL.md`
- `skills/meight-worker/SKILL.md`
- `README.md`
- `ARCHITECTURE.md`
- `AGENTS.md`
- `CLAUDE.md`

The approved decision file was committed byte-for-byte before doctrine edits.
Its pre-commit SHA-256 was
`c07e71ab2e0f54a5b1783f6e41e78726ee0784cc69b212e517e1c5cb09ab43d9`.

## Runtime findings

### Fast is a service tier, not a model slug

Pinned package evidence:

- `openai-codex==0.1.0b3` from
  `.venv/lib/python3.13/site-packages/openai_codex`.
- SDK `api.py:574-603`: `Thread.turn()` accepts `service_tier: str | None` and
  constructs `TurnStartParams(service_tier=service_tier)`.
- SDK `generated/v2_all.py:6981-6985`: the generated wire field is
  `serviceTier` and the description says it overrides the tier for the turn and
  subsequent turns.
- `meight.py:1758-1768`: `--fast` maps to `service_tier="priority"`; omitted or
  `--no-fast` maps to `"default"`.
- `meight.py:1381-1385` and `1465-1469`: start and follow turns pass the stored
  service tier into `Thread.turn()`.
- `meight.py:2148-2151`: the CLI already exposes `--fast|--no-fast`.

Conclusion: no separate Fast model slug or new CLI flag is needed. The current
`--model luna --effort xhigh --fast` path normalizes the model to
`gpt-5.6-luna` and sends `serviceTier=priority`.

### Luna xhigh survives the effort-echo workaround

- SDK `generated/v2_all.py:2719-2725`: the pinned `ReasoningEffort` enum
  natively includes `xhigh`.
- `meight.py:63-78`: dynamic mutation is only needed for later values `ultra`
  and `max`; it does not alter xhigh.
- `meight.py:81-96`: `relax_sdk_effort_echo()` only relaxes
  `reasoning_effort` on `ThreadStartResponse`, `ThreadForkResponse`, and
  `ThreadResumeResponse`. It does not rewrite turn request effort.
- `~/.meight/notes/lessons.md:39`: the workaround exists because the account
  default (for example `ultra`) was echoed into those lifecycle response
  models and rejected by the SDK's stale closed enum.

The non-daemon probe produced the same payload before and after calling the
echo workaround:

```text
{'effort': 'xhigh', 'input': [], 'model': 'gpt-5.6-luna',
 'serviceTier': 'priority', 'threadId': 'probe'}
```

Conclusion: xhigh survives for luna. The workaround addresses response parsing
and does not strip or downgrade the requested xhigh turn effort.

## Contradiction sweep

Command (restricted to the six contract surfaces):

```bash
rg -n -i \
  'sol.*(default for code|default implement|implementation, fixes, verification)|terra.*(computer use|browser qa|runtime automation|step-heavy|exploration/recon)|luna.*(trivial|one-shot trivial|simple reads|low.medium)|when in doubt.*sol|sol medium.*terra high' \
  skills/meight/SKILL.md skills/meight-worker/SKILL.md README.md \
  ARCHITECTURE.md AGENTS.md CLAUDE.md
```

Result: zero matches (the expected `rg` exit status is 1).

Positive coverage was also checked for `PLAN.md`, `new-risks`,
`resolved-risks`, failure-cost/hard-gate language, `luna→sol`, `luna→terra`,
report deviations, deliberately omitted work, and false-approve windows.

## Verification

```text
.venv/bin/python -m unittest discover -s tests -v
Ran 4 tests in 0.240s — OK

python3 .../skill-creator/scripts/quick_validate.py skills/meight
Skill is valid!

python3 .../skill-creator/scripts/quick_validate.py skills/meight-worker
Skill is valid!

git diff --check
PASS (no output)
```

The first quick-validator attempt used the repo venv and could not import its
validator-only PyYAML dependency. Re-running the same validator with system
Python, where PyYAML is installed, validated both skills. No dependency was
installed or changed.

## Judgment calls

- The English dispatcher skill includes the Korean hard-gate sentence verbatim
  because the brief explicitly required the contract wording rather than a
  translated approximation. Other surfaces carry faithful English summaries.
- `--fast` is documented as "when available" because meight can request the
  priority tier but cannot promise account/service eligibility.
- The ordinary two-turn guidance remains for normal follow/reply and code
  review. The plan-review loop is explicitly documented as a separate
  three-round exception.
- Luna implementation rationale is mapped onto existing decision fields:
  deviations and rationale in `summary`, plan evidence in `verification`,
  deliberate non-work and rationale in `risks`, and exact review scope in
  `changed_files`/`commits`.

## Deliberately not done

- `meight.py` was not changed: the required model alias, xhigh value, Fast CLI
  flag, service-tier mapping, and per-turn passthrough already exist.
- Tests were not edited. Existing tests passed, and a read-only SDK/request
  serialization probe covered the runtime question without starting a worker.
- The daemon was not restarted, as required by the brief. No runtime code
  changed, so there is no deferred code load.
- No push was performed.
- Files outside the explicitly enumerated six-document doctrine scope were not
  edited; the approved decision file itself remains unchanged.

## Remaining risk

No live Fast worker was started because that would consume runtime/account
capacity and the brief asked for SDK/plumbing verification without restarting
the daemon. The local evidence proves the request shape and preservation of
xhigh, but provider-side Fast eligibility remains account/service dependent.
