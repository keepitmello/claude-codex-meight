# claude-codex-meight Repository Guide

## What this repository is

`claude-codex-meight` is an orchestration harness for running Codex sessions as
thinking partners (`mate`) or implementers (`worker`). The `meight` CLI and
daemon manage their lifecycle, state, steering, and result handoff through the
official `openai-codex` SDK.

This file guides work on this repository. The distributable global Codex policy
lives at [`bindings/codex/AGENTS.md`](./bindings/codex/AGENTS.md).

## Ownership map

- `meight.py`: CLI, daemon, protocol, persistence, and SDK lifecycle.
- `skills/meight/`: dispatcher-facing workflow.
- `skills/meight-mate/` and `skills/meight-worker/`: session contracts.
- `skills/meight-common/`: shared protocol.
- `bindings/`: runtime-specific installation sources.
- `README.md`, `ARCHITECTURE.md`, and `SPEC.md`: usage, design, and contract
  documentation.

Keep each rule at its owning source. Update bindings or documentation only when
their direct contract changes; do not create duplicate policy sources.

## Working rules

- Prefer the smallest change that fixes the owning cause.
- Preserve user changes and avoid unrelated or destructive edits.
- Keep authentication, secrets, and machine-specific configuration out of the
  repository.
- Treat protocol compatibility, persistent state, permissions, and daemon
  ownership as hard boundaries.
- Do not add abstractions, fallbacks, tests, or review stages without a current
  requirement or concrete failure they protect.

## Verification

Run one existing, targeted check for the affected contract. Add more only for an
explicit repository gate or a distinct high-risk boundary. Documentation-only
changes need direct reference and diff inspection, not new tests.

Changes to daemon-loaded behavior require a fresh daemon before runtime proof.
For protocol epoch migration, drain live sessions, use non-force shutdown,
restart through the configured owner, and confirm a new PID, socket, capability,
and one mate/worker smoke. Never force-shutdown the migration.
