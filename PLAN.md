# Daemon hardening plan

VERSION: daemon-hardening-v2.2
BASELINE: c78ee6165270bbc4b465fa1b4f4f7570b4250038
STATUS: approved v2 with final-review ownership corrections tracked below

## Outcome

Make the global meight daemon private to the owning macOS user, recover it after
an abnormal exit through launchd, and automatically remove expired terminal
session artifacts without touching active or replyable sessions.

## Hard boundaries

- Preserve hidden ephemeral worker behavior and the same-daemon `QUESTION -> reply`
  contract.
- Never delete `starting`, `running`, or `needs_input` session artifacts.
- Do not attempt active-turn recovery after daemon death; current hidden SDK
  threads are not resumable.
- Do not force-shutdown a daemon with active sessions during installation or
  verification.
- Use only Python's standard library and launchd; no watchdog or cleanup service.

## Implementation

1. Harden the daemon trust boundary in `meight.py`.
   - Create/repair the daemon home and `repos/` as owner-only directories and
     bind `meight.sock` with owner-only permissions before accepting requests.
   - Validate worker names at both CLI and daemon boundaries.
   - Derive and verify repository keys/homes inside the daemon instead of
     trusting client-supplied path fields.
   - Bound one JSON socket request so an accidental or hostile local client
     cannot grow a connection buffer without limit.

2. Make launchd the resilient owner of managed daemon starts.
   - Generate a LaunchAgent with `RunAtLoad=true` and crash-only
     `KeepAlive={SuccessfulExit=false}` so abnormal exits restart while an
     intentional clean shutdown stays stopped.
   - Make intentional shutdown the only zero-exit accept-loop path. An
     unexpected accept/socket ownership failure must propagate to a non-zero
     process exit so crash-only restart actually fires.
   - When the LaunchAgent is loaded, route daemon auto-start through
     `launchctl kickstart`; retain the detached-process path only when no job is
     definitively installed. Treat every ambiguous `launchctl print` failure as
     unknown and fail closed.
   - Continuously verify that the published socket pathname still names the
     daemon's bound socket; deletion or replacement is an abnormal nonzero exit
     so launchd can recover it.
   - Use one ownership-transfer state machine for first load and reload:
     detect a live daemon and whether the job is loaded; request non-force
     shutdown and refuse if any `starting`, `running`, or `needs_input` worker
     exists; then wait with a bounded timeout for the acknowledged old PID and
     socket to disappear. Only after that drain completes, use bounded
     `launchctl bootout --wait` for an already-loaded service, install the new
     plist, bootstrap it, and require a fresh ping/PID. Never use
     `kickstart -k` or bootout before the drain finishes. When PID evidence is
     missing or corrupt, require a free singleton lock before treating socket
     state as stale. After bootstrap, require a new socket identity and require
     the ping PID to match the running PID reported by launchd so a concurrent
     detached starter cannot be mistaken for the managed job.

3. Extend existing daemon maintenance with bounded disk retention.
   - Default terminal-session retention to 30 days, configurable with
     `MEIGHT_SESSION_RETENTION_SEC`; `0` disables disk pruning.
   - Schedule cleanup off the accept loop and no more than once per hour.
   - Prune only real, non-symlink worker directories whose valid `status.json`
     says `completed`, `failed`, or `interrupted` and whose retention timestamp
     is expired.
   - Persist immutable `terminal_at` on new terminal transitions and prefer it
     for expiry; use `updated_at` only as a legacy fallback. On daemon startup,
     mark orphaned prior `starting`, `running`, and `needs_input` rows failed
     with `runtime_lost_detail` before accepting new work.
   - Recheck registry ownership and atomically rename a candidate while holding
     `reg_lock`, then recursively delete outside the lock. Recover leftover
     cleanup tombstones on later passes only after revalidating terminal state,
     expiry, and registry non-ownership; the reserved prefix alone is not proof
     because legacy versions allowed such worker names.
   - Expose the live retention value through `ping` for operator verification.

4. Add regression coverage and align operator documentation.
   - Unit-test permissions, path/name rejection, request bounds, launchd
     payload/start routing, active-session-safe reload, and retention race/safety
     cases.
   - Update `README.md`, `docs/README.ko.md`, `SPEC.md`, `ARCHITECTURE.md`, and
     `skills/meight/SKILL.md` with the exact security, restart, retention, and
     residual recovery contract.

5. Add same-thread turn setting overrides requested after the hardening review.
   - Keep `mode` and `report` inherited on `follow`/`reply`.
   - Omitted `--model`, `--effort`, and Fast flags inherit the worker's current
     settings; explicit values apply only when opening the next turn and become
     that worker's defaults for later turns.
   - Validate raw overrides before resetting worker state. Persist selected
     settings only after `Thread.turn()` succeeds; an already-running turn is
     never mutated.
   - Cover model aliases, effort, `--fast`/`--no-fast`, omission, persistence,
     invalid raw requests, and failed turn creation in regression tests.

## Verification

1. `python -m py_compile meight.py` and the full unittest suite pass.
2. A temporary daemon proves home `0700`, socket `0600`, valid ping fields,
   rejection of forged repo context/name, and synthetic terminal-only pruning.
3. After all meight sessions are terminal, non-force reload the installed
   LaunchAgent and verify its loaded plist plus the live daemon values. Inject
   the shutdown-ack race and first-install-with-detached-daemon cases and prove
   bootstrap cannot begin before the old PID/socket are gone.
4. With no active sessions, kill the daemon abnormally and verify launchd
   supplies a new pid and `meight ping` recovers. Then verify clean shutdown does
   not restart until `launchctl kickstart`. Unit-test an unexpected accept
   failure as non-zero and intentional shutdown as zero.
5. Run a throwaway read-only worker after restart and recheck `mode=review`,
   `thread_source=subagent`, and `thread_ephemeral=true`.
6. Run `git diff --check`, inspect the full diff, and obtain an independent
   `sol` adversarial review against this exact plan version.

## Deliberate non-goals

- Resuming active hidden workers after daemon process death.
- Count/size-based artifact eviction or deleting malformed/unknown session data.
- Remote access, multi-user sharing, or a second watchdog/cleanup daemon.
