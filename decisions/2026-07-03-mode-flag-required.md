# Should `--mode collab|delegate` be required, defaulted, or inferred?

DATE: 2026-07-03 · MODE: consensus

READ A (dispatcher): Required. The consumer is an LLM agent; optional flags with
defaults are never revisited ("policy can't be forgotten" is an existing design
principle — the preamble is harness-injected for the same reason). A teaching
error message doubles as just-in-time documentation of the mode split.

READ B (worker, blind): `--mode auto|collaborative|delegated` with default
`auto` (legacy brief inference), explicit mode urged in docs. Rationale:
required breaks existing CLI habits and automation; harness-side semantic
inference is unreliable, so keep inference as a compatibility path only.

DISAGREEMENT: enforcement vs compatibility — whether mode selection may be left
optional.

RESOLUTION: value-judgment, settled by an asymmetry argument plus user call:
relaxing required→optional later is non-breaking, while tightening
optional→required later breaks callers. Starting strict is the reversible
choice. User (risk owner) chose required.

DECISION: `--mode` is required on `start`/`dispatch` with a teaching error;
`follow`/`reply` inherit the worker's recorded mode. No `auto`.

STATUS: adopted
