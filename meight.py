#!/usr/bin/env python3
"""claude-codex-meight: Harness for running multiple Codex workers in parallel. See SPEC.md for the contract.

Run: .venv/bin/python meight.py <cmd>
Observe by pulling disk digests, steer mid-turn, and push only through wait.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEBUG_EVENTS = os.environ.get("MEIGHT_DEBUG") == "1"
TERMINAL_STATES = {"completed", "failed", "interrupted"}
ACTIVE_STATES = {"starting", "running", "needs_input"}
SOCKET_TIMEOUT_SEC = 60.0  # start/follow may take several seconds for thread_start+turn RPCs
STATUS_THROTTLE_SEC = 2.0
EVENT_LINE_MAX = 300
DEFAULT_IDLE_TIMEOUT_SEC = 30 * 60
DEFAULT_WORKER_GC_TTL_SEC = 60 * 60
LAUNCHD_LABEL = "com.keepitmello.meight"
MANAGED_DAEMON_IDLE_TIMEOUT_SEC = "0"

# Worker-side skill path resolves relative to this file so any clone location works.
WORKER_SKILL_PATH = Path(__file__).resolve().parent / "skills" / "meight-worker" / "SKILL.md"

# Every worker runs in an explicit mode; the CLI requires it so the choice cannot be skipped.
MODE_MAP = {
    "collab": "collaborative",
    "collaborative": "collaborative",
    "delegate": "delegated",
    "delegated": "delegated",
}

# Single source of the teaching error shown wherever --mode is missing (validated before any side effect).
MODE_TEACHING_ERROR = """error: --mode is required. Pick one:
  --mode collab    think together: consult, design, diagnosis, alternatives — worker exposes options and reasoning
  --mode delegate  own the technical loop: bounded implementation, fix, review — worker reports a decision surface"""

_MODE_BLOCKS = {
    "collaborative": (
        "- Mode: COLLABORATIVE — think with the dispatcher. Expose options, tradeoffs, risks, and your "
        "reasoning; challenge assumptions; give a clear recommendation. A useful report shape: "
        "CONCLUSION / OPTIONS / RECOMMENDATION / EVIDENCE / ASK."
    ),
    "delegated": (
        "- Mode: DELEGATED — own the technical loop end-to-end. Keep implementation ping-pong, logs, and "
        "low-level detail out of the report; put them in a worker-unique evidence artifact and report a "
        "decision surface: verdict, verification PASS/FAIL/NOT RUN with one-line evidence, decisions "
        "needed (or none), changed files, commit status, evidence artifact path."
    ),
}

# Bidirectional workers: automatically prepend this before start briefs (disable with --no-preamble)
_PREAMBLE_TEMPLATE = """[Harness protocol — mode: {mode} — applies on top of the task below]
- First read and follow the meight-worker skill at `{skill_path}`. That skill is the worker-side SSOT for role split, modes, reporting, evidence, review, and QUESTION boundaries.
- If the skill is inaccessible, continue from this compact fallback and record `SKILL NOT READ: <reason>` in your report or evidence artifact.
- You are a Codex technical teammate. The dispatcher owns WHAT/WHY, priority, scope, UX, user-visible behavior, risk appetite, acceptance criteria, and final approval. You own HOW, technical judgment, technical design, implementation, verification, and review-loop handling.
{mode_block}
- Work evidence-first, root-cause-first, and scope-aware. Challenge wrong assumptions or materially better directions early; decide local technical details yourself.
- You may run `git commit` and `git push` to commit and push your completed, verified work.
- If you leave non-code artifact documents such as reports, analyses, evidence, or handoffs in the working directory (cwd), do not use fixed generic names like `result.md`; parallel workers in the same cwd can overwrite each other and pollute the repo. Use a worker-unique name such as `<worker-name>-evidence.md` or `<worker-name>-<short-topic>.md`, and keep that worker-name prefix for every cwd artifact document you create. The isolated worker report at `~/.meight/repos/.../workers/<name>/result.md` is the final message record, not a separate hidden detail channel. Code changes should be made directly in their source paths and are not part of this artifact-document naming rule.
{question_block}
"""

# Escalation channel depends on the report mode: text workers end with a QUESTION: paragraph;
# decision workers cannot (their final message is schema-forced JSON), so they escalate via
# outcome=needs_decision + decisions[]. The preamble must teach the channel that actually works.
_QUESTION_BLOCKS = {
    "text": """- Use `QUESTION:` only as the final paragraph when you are truly blocked or when a decision outside your ownership could change scope, UX, user-visible behavior, priority, risk appetite, irreversible action, or acceptance criteria. Resolve technical uncertainty with evidence first; if it does not change dispatcher-owned direction, decide locally and report the judgment call. Structure the paragraph so it can be routed without parsing prose:
  QUESTION:
  TARGET: dispatcher | user   (dispatcher = the orchestrating agent; user = the human it reports to — scope, UX, priority, risk appetite, and irreversible actions usually belong to the user)
  KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
  <the question itself, with options and your recommendation>""",
    "decision": """- Your final message MUST be JSON matching the decision-report schema the harness supplies (strict mode: every field is required — use empty arrays or "N/A" where inapplicable; keep detail in evidence artifacts, not the report). Do not end with a text `QUESTION:` paragraph — it cannot be emitted under the schema. To escalate a decision outside your ownership (scope, UX, user-visible behavior, priority, risk appetite, irreversible action, acceptance criteria) or a true block, set `outcome: "needs_decision"` and add a `decisions[]` entry with `target` ("dispatcher" = the orchestrating agent, "user" = the human it reports to), `kind`, `question`, and `recommendation`. Resolve technical uncertainty with evidence first; if it does not change dispatcher-owned direction, decide locally and record the judgment call.""",
}


def build_preamble(mode: str, report: str = "text") -> str:
    question_block = _QUESTION_BLOCKS["decision" if report == "decision" else "text"]
    return _PREAMBLE_TEMPLATE.format(
        mode=mode, skill_path=WORKER_SKILL_PATH, mode_block=_MODE_BLOCKS[mode],
        question_block=question_block,
    )


def build_follow_reminder(mode: str, report: str = "text") -> str:
    """Follow/reply turns get a one-line reminder instead of re-injecting the full preamble."""
    if report == "decision":
        tail = ('final message is schema-forced JSON (all fields required); escalate via '
                'outcome: "needs_decision" + decisions[] (target/kind), only for '
                "dispatcher/user-owned decisions or true blocks.]\n")
    else:
        tail = ("QUESTION: as the final paragraph with TARGET:/KIND: lines, only for "
                "dispatcher/user-owned decisions or true blocks.]\n")
    return (
        f"[Harness reminder — mode: {mode} — same protocol as the initial brief: evidence-first; "
        f"commit/push allowed for verified work; {tail}"
    )


# Structured decision-surface report (--report decision): the SDK forces the final agent message
# to match this schema; the daemon renders decision.md and routes outcome=needs_decision to
# needs_input so the dispatcher reads a decision surface instead of a technical log.
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "blocked", "needs_decision", "failed"]},
        "verdict": {"type": "string", "enum": ["GO", "NO-GO", "PARTIAL", "N/A"]},
        "summary": {"type": "string"},
        "verification": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "check": {"type": "string"},
                    "status": {"type": "string", "enum": ["PASS", "FAIL", "NOT_RUN"]},
                    "evidence": {"type": "string"},
                },
                "required": ["check", "status", "evidence"],
            },
        },
        "remaining_p1": {"type": "array", "items": {"type": "string"}},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "target": {"type": "string", "enum": ["dispatcher", "user"]},
                    "kind": {"type": "string"},
                    "question": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
                "required": ["target", "kind", "question", "recommendation"],
            },
        },
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "commits": {"type": "array", "items": {"type": "string"}},
        "evidence_artifacts": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "outcome",
        "verdict",
        "summary",
        "verification",
        "remaining_p1",
        "decisions",
        "changed_files",
        "commits",
        "evidence_artifacts",
        "risks",
    ],
}


def render_decision(d: dict) -> str:
    """Render decision.json into the short decision.md the dispatcher actually reads."""
    head = f"OUTCOME: {d.get('outcome', '?')}"
    if d.get("verdict"):
        head += f" · VERDICT: {d['verdict']}"
    lines = [head, f"SUMMARY: {d.get('summary', '')}"]
    for v in d.get("verification") or []:
        line = f"VERIFICATION: {v.get('status', '?')} - {v.get('check', '')}"
        if v.get("evidence"):
            line += f" ({v['evidence']})"
        lines.append(line)
    if d.get("remaining_p1"):
        lines.append("P1 REMAINING: " + "; ".join(str(x) for x in d["remaining_p1"]))
    decisions = d.get("decisions") or []
    if decisions:
        lines.append("DECISIONS NEEDED:")
        for q in decisions:
            rec = f" → recommend: {q['recommendation']}" if q.get("recommendation") else ""
            lines.append(f"  [{q.get('target', 'dispatcher')}/{q.get('kind', '?')}] {q.get('question', '')}{rec}")
    else:
        lines.append("DECISIONS NEEDED: none")
    if d.get("changed_files"):
        lines.append("FILES: " + ", ".join(str(x) for x in d["changed_files"]))
    if d.get("commits"):
        lines.append("COMMITS: " + ", ".join(str(x) for x in d["commits"]))
    if d.get("evidence_artifacts"):
        lines.append("EVIDENCE: " + ", ".join(str(x) for x in d["evidence_artifacts"]))
    if d.get("risks"):
        lines.append("RISKS: " + "; ".join(str(x) for x in d["risks"]))
    return "\n".join(lines) + "\n"


def parse_question_metadata(question: str) -> tuple[str, str | None]:
    """Lenient TARGET:/KIND: extraction from a QUESTION paragraph. Missing target routes to dispatcher."""
    target, kind = "dispatcher", None
    for line in question.splitlines():
        m = re.match(r"^\s*TARGET:\s*([A-Za-z_-]+)", line, re.IGNORECASE)
        if m:
            target = "user" if m.group(1).lower().startswith("user") else "dispatcher"
            continue
        m = re.match(r"^\s*KIND:\s*([A-Za-z_-]+)", line, re.IGNORECASE)
        if m:
            kind = m.group(1).lower()
    return target, kind

SANDBOX_MAP = {
    "ws": "workspace_write",
    "workspace_write": "workspace_write",
    "workspace-write": "workspace_write",
    "ro": "read_only",
    "read_only": "read_only",
    "read-only": "read_only",
    "full": "full_access",
    "full_access": "full_access",
    "full-access": "full_access",
}


# ── Common Utilities ───────────────────────────────────────────────────────

def now_kst() -> datetime:
    return datetime.now(KST)


def now_iso() -> str:
    return now_kst().isoformat(timespec="seconds")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _clamp_nonnegative_float(value: float | str) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_TIMEOUT_SEC


def default_daemon_idle_timeout_sec() -> float:
    """LaunchAgent jobs are managed daemons even if an old loaded job lacks the env override."""
    if os.environ.get("MEIGHT_IDLE_TIMEOUT_SEC") is not None:
        return _env_float("MEIGHT_IDLE_TIMEOUT_SEC", DEFAULT_IDLE_TIMEOUT_SEC)
    if os.environ.get("XPC_SERVICE_NAME") == LAUNCHD_LABEL:
        return _clamp_nonnegative_float(MANAGED_DAEMON_IDLE_TIMEOUT_SEC)
    return DEFAULT_IDLE_TIMEOUT_SEC


def managed_daemon_env(home: Path) -> dict[str, str]:
    """Environment for CLI/launchd-managed daemons that must keep live channels open."""
    env = dict(os.environ)
    env["MEIGHT_HOME"] = str(home)
    env["MEIGHT_IDLE_TIMEOUT_SEC"] = MANAGED_DAEMON_IDLE_TIMEOUT_SEC
    return env


def state_home() -> Path:
    """Global daemon state home.

    Worker digests are still scoped per repository under this directory. MEIGHT_HOME
    now controls the global daemon home instead of a single repo's worker home.
    """
    env = os.environ.get("MEIGHT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return (Path(xdg_state).expanduser() / "meight").resolve()
    return (Path.home() / ".meight").resolve()


def repo_root_for(cwd: str | Path | None = None) -> Path:
    base = Path(cwd or os.getcwd()).expanduser().resolve()
    try:
        root = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if root:
            return Path(root).resolve()
    except Exception:
        pass
    return base


def repo_key_for(repo_root: Path) -> str:
    raw = str(repo_root)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo_root.name).strip("-._")
    return f"{slug or 'root'}-{digest}"


def repo_context(home: Path, cwd: str | Path | None = None) -> dict:
    root = repo_root_for(cwd)
    key = repo_key_for(root)
    repo_home = home / "repos" / key
    return {"repo_root": str(root), "repo_key": key, "repo_home": str(repo_home)}


def registry_key(repo_key: str, name: str) -> str:
    return f"{repo_key}\0{name}"


def atomic_write_json(path: Path, obj: dict) -> None:
    # Include pid+thread id in tmp names so concurrent writers cannot steal each other's tmp files.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, ValueError):
        return False
    except OSError:
        return False


def read_daemon_pid(home: Path) -> int | None:
    try:
        return int((home / "daemon.pid").read_text().strip())
    except (OSError, ValueError):
        return None


def probe_daemon_socket(sock_path: Path, timeout: float = 3.0) -> bool:
    """Ping meight.sock to confirm the daemon is alive and avoid false positives from pid reuse."""
    if not sock_path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
        s.sendall(b'{"cmd":"ping"}\n')
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                return False
            buf += chunk
        return json.loads(buf.split(b"\n", 1)[0]).get("ok") is True
    except (OSError, json.JSONDecodeError):
        return False
    finally:
        s.close()


def truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def dig(d: object, *keys: str, default=None):
    """Chained dict.get helper for missing beta SDK payload fields."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


# ── Worker (Inside Daemon) ─────────────────────────────────────────────────

def describe_item(item: dict) -> str:
    itype = item.get("type", "unknown")
    if itype == "commandExecution":
        return f"commandExecution: {truncate(item.get('command', ''), 120)}"
    if itype == "agentMessage":
        return "agentMessage"
    if itype == "reasoning":
        return "reasoning"
    if itype == "fileChange":
        paths = [dig(c, "path", default="?") for c in item.get("changes") or []]
        return f"fileChange: {truncate(', '.join(str(p) for p in paths), 150)}"
    if itype == "mcpToolCall":
        return f"mcpToolCall: {item.get('server', '?')}/{item.get('tool', '?')}"
    if itype == "webSearch":
        return f"webSearch: {truncate(item.get('query', ''), 100)}"
    return itype


def files_from_diff(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if m:
            files.append(m.group(2).strip())
            continue
        m = re.match(r"^\+\+\+ (?:b/)?(.+)$", line)
        if m and m.group(1).strip() != "/dev/null":
            files.append(m.group(1).strip())
    seen: dict[str, None] = {}
    for f in files:
        seen.setdefault(f, None)
    return list(seen.keys())


class Worker:
    """One worker = one Codex Thread plus a digest file set."""

    def __init__(self, name: str, repo_home: Path, repo_root: str, repo_key: str, cwd: str, sandbox: str,
                 model: str | None, effort: str, service_tier: str | None = None,
                 thread_source: str = "subagent", thread_ephemeral: bool = True,
                 mode: str = "delegated", report: str = "text"):
        self.name = name
        self.repo_home = repo_home
        self.repo_root = repo_root
        self.repo_key = repo_key
        self.dir = repo_home / "workers" / name
        self.cwd = cwd
        self.sandbox = sandbox  # normalized key such as "workspace_write"
        self.model = model
        self.effort = effort
        self.service_tier = service_tier  # "default" unless --fast maps the worker to "priority"
        self.thread_source = thread_source
        self.thread_ephemeral = thread_ephemeral
        self.mode = mode          # "collaborative" | "delegated"; follow/reply turns inherit it
        self.report = report      # "text" | "decision" (decision = output_schema-forced final report)
        self.thread = None       # openai_codex.Thread (kept while daemon lives -> reused for follow)
        self.handle = None       # TurnHandle
        self.codex = None        # openai_codex.Codex runtime owned by this worker
        self.consumer: threading.Thread | None = None
        self.interrupt_requested = False
        self.lock = threading.Lock()       # serialize status/event handling
        self.ctl_lock = threading.Lock()   # serialize control calls such as steer/interrupt
        self.generation = 0                # turn generation; ignores late events from old streams
        self.terminal_since: float | None = None
        self._last_status_write = 0.0
        self._agent_msg_buf = ""       # accumulated in-flight agentMessage deltas
        self._last_agent_msg = ""      # last finalized agentMessage
        self._current_item_label: str | None = None
        self._current_item_since: float | None = None
        # The public status.json field needs_input_source is the SSOT for needs_input:
        # "question" (final QUESTION; wait exits 3 only while daemon-attached) |
        # "tool" (mid-turn wait; treated as active)
        self.status: dict = {}

    # ── status.json ──

    def init_status(self, thread_id: str | None, turns: int = 1) -> None:
        with self.lock:
            self._init_status_locked(thread_id, turns)

    def _init_status_locked(self, thread_id: str | None, turns: int) -> None:
        self.status = {
            "name": self.name,
            "thread_id": thread_id,
            "turn_id": None,
            "state": "starting",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "repo_root": self.repo_root,
            "repo_key": self.repo_key,
            "daemon_pid": os.getpid(),
            "cwd": self.cwd,
            "sandbox": self.sandbox.replace("_", "-"),
            "model": self.model,
            "effort": self.effort,
            "service_tier": self.service_tier,
            "thread_source": self.thread_source,
            "thread_ephemeral": self.thread_ephemeral,
            "mode": self.mode,
            "report": self.report,
            "current_item": None,
            "plan": [],
            "files_changed": [],
            "tokens": {"input": 0, "cached": 0, "output": 0},
            "last_message_tail": "",
            "needs_input_detail": None,
            "needs_input_source": None,
            "needs_input_target": None,
            "needs_input_kind": None,
            "runtime_lost_detail": None,
            "turns": turns,
        }
        self.write_status(force=True)

    def write_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_status_write < STATUS_THROTTLE_SEC:
            return
        self._last_status_write = now
        self.status["updated_at"] = now_iso()
        if self._current_item_label and self._current_item_since is not None:
            elapsed = int(time.monotonic() - self._current_item_since)
            self.status["current_item"] = f"{self._current_item_label} ({elapsed}s)"
        else:
            self.status["current_item"] = None
        state = self.status.get("state")
        if state in TERMINAL_STATES and self.terminal_since is None:
            self.terminal_since = time.monotonic()
        elif state not in TERMINAL_STATES:
            self.terminal_since = None
        atomic_write_json(self.dir / "status.json", self.status)

    def log_event(self, method: str, summary: str) -> None:
        line = f"{now_iso()} [{method}] {truncate(summary, EVENT_LINE_MAX - 60)}"
        with open(self.dir / "events.log", "a", encoding="utf-8") as f:
            f.write(line[:EVENT_LINE_MAX] + "\n")

    def _clear_needs_input_locked(self) -> None:
        self.status["needs_input_detail"] = None
        self.status["needs_input_source"] = None
        self.status["needs_input_target"] = None
        self.status["needs_input_kind"] = None

    # ── Event Handling ──

    def consume_stream(self, daemon: "Daemon", gen: int, handle) -> None:
        try:
            for note in handle.stream():
                try:
                    self.on_event(note, daemon, gen)
                except Exception as e:  # one event handler failure must not kill the worker
                    daemon.log(f"worker={self.name} event handler error: {e!r}")
            self.on_stream_end(gen)
        except Exception as e:
            with self.lock:
                state = self.status.get("state")
                question_final = (state == "needs_input"
                                  and self.status.get("needs_input_source") == "question")
                if gen == self.generation and state not in TERMINAL_STATES and not question_final:
                    self.status["state"] = "interrupted" if self.interrupt_requested else "failed"
                    self._clear_needs_input_locked()
                    self.log_event("stream/exception", f"{type(e).__name__}: {e}")
                    self.write_status(force=True)
            daemon.log(f"worker={self.name} stream exception: {traceback.format_exc(limit=3)}")
        finally:
            self.detach_runtime_refs_if_idle(daemon, gen, "stream ended")
            daemon.touch_activity()

    def on_event(self, note, daemon: "Daemon", gen: int) -> None:
        method = note.method
        payload = note.payload
        # mode="json": enum -> value strings, Path -> str (avoid exposing raw beta SDK enums)
        p = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else (
            payload if isinstance(payload, dict) else {})

        if DEBUG_EVENTS:
            try:
                with open(self.dir / "debug-events.log", "a", encoding="utf-8") as f:
                    f.write(f"{now_iso()} {method} {json.dumps(p, ensure_ascii=False, default=str)[:4000]}\n")
            except Exception:
                pass

        with self.lock:
            if gen != self.generation:
                return  # late event from an old turn; prevents status/result contamination
            self._handle_event(method, p)

    def _handle_event(self, method: str, p: dict) -> None:
        if method == "turn/started":
            self.status["turn_id"] = dig(p, "turn", "id")
            if self.status["state"] == "starting":
                self.status["state"] = "running"
            self.log_event(method, f"turn={self.status['turn_id']}")
            self.write_status(force=True)

        elif method == "item/started":
            item = p.get("item") or {}
            self._current_item_label = describe_item(item)
            self._current_item_since = time.monotonic()
            if item.get("type") == "agentMessage":
                self._agent_msg_buf = ""
            if self.status["state"] in ("starting", "needs_input"):
                self.status["state"] = "running"
                self._clear_needs_input_locked()
            self.write_status(force=True)

        elif method == "item/agentMessage/delta":
            self._agent_msg_buf += p.get("delta") or ""
            self.status["last_message_tail"] = self._agent_msg_buf[-500:]
            self.write_status()  # throttled

        elif method == "item/completed":
            self._on_item_completed(p.get("item") or {})

        elif method == "turn/plan/updated":
            marker = {"completed": "[done]", "inProgress": "[active]", "pending": "[ ]"}
            self.status["plan"] = [
                f"{marker.get(dig(s, 'status', default=''), '[?]')} {dig(s, 'step', default='')}"
                for s in p.get("plan") or []
            ]
            self.write_status(force=True)

        elif method == "turn/diff/updated":
            files = files_from_diff(p.get("diff") or "")
            if files:
                self.status["files_changed"] = files
            self.write_status()

        elif method == "thread/tokenUsage/updated":
            total = dig(p, "token_usage", "total", default={})
            self.status["tokens"] = {
                "input": dig(total, "input_tokens", default=0),
                "cached": dig(total, "cached_input_tokens", default=0),
                "output": dig(total, "output_tokens", default=0),
            }
            self.write_status()

        elif method == "turn/completed":
            self._on_turn_completed(p.get("turn") or {})

        elif method == "error":
            msg = dig(p, "error", "message", default="unknown error")
            will_retry = bool(p.get("will_retry"))
            self.log_event(method, f"{msg} (will_retry={will_retry})")
            if not will_retry:
                self.status["state"] = "failed"
                self._clear_needs_input_locked()
                self.write_status(force=True)

        elif method == "tool/requestUserInput" or method.endswith("/requestApproval"):
            # With config approval=never this should not happen; defensive handling only (v1: no auto-reply).
            self.status["state"] = "needs_input"
            self.status["needs_input_detail"] = truncate(json.dumps(p, ensure_ascii=False, default=str), 500)
            self.status["needs_input_source"] = "tool"  # mid-turn wait, not final; wait treats it as active
            self.status["needs_input_target"] = None
            self.status["needs_input_kind"] = None
            self.log_event(method, self.status["needs_input_detail"])
            self.write_status(force=True)

        elif method in ("item/commandExecution/outputDelta",
                        "item/reasoning/textDelta",
                        "item/reasoning/summaryTextDelta",
                        "item/reasoning/summaryPartAdded",
                        "item/fileChange/outputDelta",
                        "item/plan/delta"):
            self.write_status()  # deltas only refresh throttled status without logging (elapsed update)

        else:
            pass  # ignore unknown or irrelevant events

    def _on_item_completed(self, item: dict) -> None:
        itype = item.get("type", "unknown")
        if itype == "agentMessage":
            text = item.get("text") or self._agent_msg_buf
            self._last_agent_msg = text
            self.status["last_message_tail"] = text[-500:]
            self.log_event("item/completed", f"agentMessage: {truncate(text, 150)}")
        elif itype == "commandExecution":
            self.log_event(
                "item/completed",
                f"commandExecution: {truncate(item.get('command', ''), 150)}"
                f" → exit {item.get('exit_code')}",
            )
        elif itype == "fileChange":
            paths = [str(dig(c, "path", default="?")) for c in item.get("changes") or []]
            for path in paths:
                if path not in self.status["files_changed"]:
                    self.status["files_changed"].append(path)
            self.log_event("item/completed",
                           f"fileChange ({item.get('status')}): {', '.join(paths)}")
        elif itype == "mcpToolCall":
            self.log_event("item/completed",
                           f"mcpToolCall: {item.get('server')}/{item.get('tool')}"
                           f" → {item.get('status')}")
        elif itype == "webSearch":
            self.log_event("item/completed", f"webSearch: {truncate(item.get('query', ''), 150)}")
        # Other item types such as reasoning are noise, so do not log them.
        self._current_item_label = None
        self._current_item_since = None
        self.write_status(force=True)

    def _extract_question(self) -> str | None:
        """Return the final paragraph if the final agent message ends with a QUESTION: block."""
        msg = (self._last_agent_msg or self._agent_msg_buf).strip()
        if not msg:
            return None
        paragraphs = [blk.strip() for blk in re.split(r"\n\s*\n", msg) if blk.strip()]
        if paragraphs and paragraphs[-1].startswith("QUESTION:"):
            return paragraphs[-1]
        return None

    def _parse_decision(self) -> dict:
        msg = (self._last_agent_msg or self._agent_msg_buf).strip()
        if msg.startswith("```"):
            msg = re.sub(r"^```(?:json)?\s*", "", msg, flags=re.IGNORECASE)
            msg = re.sub(r"\s*```$", "", msg).strip()
        parsed = json.loads(msg)
        if not isinstance(parsed, dict):
            raise ValueError("decision report is not a JSON object")
        return parsed

    def _write_decision(self, decision: dict) -> str:
        atomic_write_json(self.dir / "decision.json", decision)
        rendered = render_decision(decision)
        path = self.dir / "decision.md"
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(tmp, path)
        return rendered

    def _on_turn_completed(self, turn: dict) -> None:
        turn_status = turn.get("status")  # completed | interrupted | failed | (future SDK values)
        prior = self.status.get("state")
        # Priority: preserve existing failed/interrupted > promote QUESTION > completed
        if prior in ("failed", "interrupted"):
            # A late completed event must not overwrite a failure already set by a non-retry error.
            self.log_event("turn/completed",
                           f"turn status {turn_status!r} ignored — state already {prior}")
        elif turn_status == "interrupted":
            self.status["state"] = "interrupted"
        elif turn_status == "completed":
            # Promote QUESTION only for normally completed turns so it cannot conflict with interrupted/failed.
            decision = None
            rendered = None
            if self.report == "decision":
                try:
                    decision = self._parse_decision()
                    rendered = self._write_decision(decision)
                except Exception as e:
                    self.log_event("decision/parse-failed", f"{type(e).__name__}: {e}")
            if decision is not None:
                decisions = decision.get("decisions") or []
                if decision.get("outcome") == "needs_decision" and decisions:
                    routed = next((d for d in decisions if d.get("target") == "user"), decisions[0])
                    self.status["state"] = "needs_input"
                    self.status["needs_input_detail"] = truncate(rendered or render_decision(decision), 500)
                    self.status["needs_input_source"] = "question"
                    self.status["needs_input_target"] = (
                        "user" if routed.get("target") == "user" else "dispatcher"
                    )
                    self.status["needs_input_kind"] = routed.get("kind")
                    self.log_event("decision/needs-decision", self.status["needs_input_detail"])
                else:
                    self.status["state"] = "completed"
            else:
                question = self._extract_question()
                if question:
                    target, kind = parse_question_metadata(question)
                    self.status["state"] = "needs_input"
                    self.status["needs_input_detail"] = truncate(question, 500)
                    self.status["needs_input_source"] = "question"
                    self.status["needs_input_target"] = target
                    self.status["needs_input_kind"] = kind
                    self.log_event("question", question)
                else:
                    self.status["state"] = "completed"
        elif turn_status == "failed":
            self.status["state"] = "failed"
            err = dig(turn, "error", "message")
            if err:
                self.log_event("turn/completed", f"failed: {truncate(err, 200)}")
        else:
            # Mapping unknown/missing statuses to completed would violate the wait contract.
            self.status["state"] = "interrupted" if self.interrupt_requested else "failed"
            self.log_event("turn/completed",
                           f"unexpected turn status {turn_status!r} → {self.status['state']}")
        # Clear stale tool wait details for every non-question terminal state (failed/interrupted/completed).
        if self.status["state"] != "needs_input":
            self._clear_needs_input_locked()
        self._current_item_label = None
        self._current_item_since = None
        self.write_result()
        self.log_event("turn/completed", f"state={self.status['state']}")
        self.write_status(force=True)

    def on_stream_end(self, gen: int) -> None:
        with self.lock:
            if gen != self.generation:
                return
            state = self.status.get("state")
            if state == "needs_input":
                if self.status.get("needs_input_source") == "question":
                    return  # final QUESTION; keep waiting for a follow-up answer
                # Stream ended while waiting on tool/approval without a terminal event = failure, not hidden.
                self.status["state"] = "interrupted" if self.interrupt_requested else "failed"
                self._clear_needs_input_locked()
                self.log_event("stream/ended",
                               f"stream ended while awaiting tool/approval → {self.status['state']}")
                self.write_result()
                self.write_status(force=True)
                return
            if state not in TERMINAL_STATES:
                self.status["state"] = "interrupted" if self.interrupt_requested else "failed"
                self.log_event("stream/ended", f"stream ended without terminal event → {self.status['state']}")
                self.write_result()
                self.write_status(force=True)

    def write_result(self) -> None:
        msg = self._last_agent_msg or self._agent_msg_buf or "(no agent message)"
        header = ""
        if self.status.get("turns", 1) > 1:
            header = f"\n\n---\n## Turn {self.status['turns']} ({now_iso()})\n\n"
        with open(self.dir / "result.md", "a", encoding="utf-8") as f:
            f.write(header + msg + "\n")

    # ── Reset For Follow ──

    def reset_for_follow(self, brief: str) -> None:
        with self.lock:
            self.generation += 1  # after this point, all old stream events are ignored
            self.interrupt_requested = False
            self._agent_msg_buf = ""
            self._last_agent_msg = ""
            self._current_item_label = None
            self._current_item_since = None
            self.terminal_since = None
            turns = int(self.status.get("turns", 1)) + 1
            sep = f"\n\n---\n## Turn {turns} ({now_iso()})\n\n"
            with open(self.dir / "brief.md", "a", encoding="utf-8") as f:
                f.write(sep + brief + "\n")
            with open(self.dir / "events.log", "a", encoding="utf-8") as f:
                f.write(f"--- turn {turns} ({now_iso()}) ---\n")
            self.status.update({
                "turn_id": None,
                "state": "starting",
                "started_at": now_iso(),
                "daemon_pid": os.getpid(),
                "current_item": None,
                "plan": [],
                "files_changed": [],
                "last_message_tail": "",
                "needs_input_detail": None,
                "needs_input_source": None,
                "needs_input_target": None,
                "needs_input_kind": None,
                "runtime_lost_detail": None,
                "turns": turns,
            })
            for fname in ("decision.json", "decision.md"):
                try:
                    (self.dir / fname).unlink()
                except FileNotFoundError:
                    pass
            self.write_status(force=True)

    def current_state(self) -> str:
        with self.lock:
            return self.status.get("state", "unknown")

    def has_live_turn(self) -> bool:
        """True only while a Codex turn may still need a live TurnHandle."""
        with self.lock:
            state = self.status.get("state")
            source = self.status.get("needs_input_source")
        return state in ("starting", "running") or (state == "needs_input" and source != "question")

    def detach_runtime_refs_if_idle(self, daemon: "Daemon", gen: int, reason: str,
                                    keep_thread: bool = True) -> None:
        """Release SDK runtime after a turn; keep it only for a replyable final QUESTION."""
        codex_to_close = None
        with self.ctl_lock:
            with self.lock:
                state = self.status.get("state")
                source = self.status.get("needs_input_source")
                detachable = state in TERMINAL_STATES or (state == "needs_input" and source == "question")
                if gen != self.generation or not detachable:
                    return
                keep_runtime = keep_thread and state == "needs_input" and source == "question"
                had_refs = self.handle is not None or self.thread is not None or self.codex is not None
                self.handle = None
                if not keep_runtime:
                    self.thread = None
                    codex_to_close = self.codex
                    self.codex = None
            if had_refs:
                detached = "turn handle" if codex_to_close is None else "runtime refs"
                daemon.log(f"detached {detached} worker={self.name} repo={self.repo_key} reason={reason}")
        if codex_to_close is not None:
            try:
                codex_to_close.close()
            except Exception as e:
                daemon.log(f"codex.close worker={self.name} repo={self.repo_key} error: {e!r}")

    def mark_failed(self, reason: str) -> None:
        with self.lock:
            self.status["state"] = "failed"
            self.status["runtime_lost_detail"] = None
            self.log_event("daemon/error", reason)
            self.write_status(force=True)

    def mark_interrupted(self, reason: str) -> None:
        with self.lock:
            self.interrupt_requested = True
            self.status["state"] = "interrupted"
            self._clear_needs_input_locked()
            self.status["runtime_lost_detail"] = None
            self.log_event("interrupt", reason)
            self.write_status(force=True)

    def consumer_finished(self, join_timeout: float = 3.0) -> bool:
        if self.consumer is None:
            return True
        self.consumer.join(timeout=join_timeout)
        return not self.consumer.is_alive()


# ── Daemon ─────────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self, home: Path, idle_timeout_sec: float | None = None):
        self.home = home
        self.sock_path = home / "meight.sock"
        self.pid_path = home / "daemon.pid"
        self.log_path = home / "daemon.log"
        self.workers: dict[str, Worker] = {}
        self.reg_lock = threading.Lock()
        self.shutting_down = threading.Event()
        self.server: socket.socket | None = None
        self.lock_file = None  # flock handle kept while the daemon is alive
        self.idle_timeout_sec = (
            _clamp_nonnegative_float(idle_timeout_sec)
            if idle_timeout_sec is not None
            else default_daemon_idle_timeout_sec()
        )
        self.worker_gc_ttl_sec = _env_float("MEIGHT_WORKER_GC_TTL_SEC", DEFAULT_WORKER_GC_TTL_SEC)
        self.last_activity = time.monotonic()

    def touch_activity(self) -> None:
        self.last_activity = time.monotonic()

    def log(self, msg: str) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{now_iso()} {msg}\n")
        except OSError:
            pass

    # ── Startup/Cleanup ──

    def run(self) -> int:
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "repos").mkdir(exist_ok=True)

        # Singleton guard 1: flock blocks concurrent startup regardless of pid file presence/reuse.
        self.lock_file = open(self.home / "daemon.lock", "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("daemon already running (daemon.lock held)", file=sys.stderr)
            return 1
        # Singleton guard 2: never unlink an existing socket if it is alive.
        if probe_daemon_socket(self.sock_path):
            print(f"daemon already running (live socket at {self.sock_path})", file=sys.stderr)
            return 1
        # From here on the state is confirmed stale, so clean up leftovers.
        for p in (self.sock_path, self.pid_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.sock_path))
        self.server.listen(16)
        self.server.settimeout(1.0)
        self.pid_path.write_text(str(os.getpid()) + "\n")

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        self.log(
            f"daemon started pid={os.getpid()} home={self.home} "
            f"idle_timeout_sec={self.idle_timeout_sec:g}"
        )
        print(f"claude-codex-meight daemon listening on {self.sock_path} (pid {os.getpid()})", flush=True)

        try:
            while not self.shutting_down.is_set():
                try:
                    conn, _ = self.server.accept()
                except socket.timeout:
                    self._maintenance()
                    continue
                except OSError:
                    break  # socket closed = shutdown
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
        finally:
            self._cleanup()
        return 0

    def _on_signal(self, signum, frame) -> None:
        self.log(f"signal {signum} received → shutdown")
        threading.Thread(target=self._shutdown_now, daemon=True).start()

    def _shutdown_now(self) -> None:
        if self.shutting_down.is_set():
            return
        self.shutting_down.set()
        with self.reg_lock:
            workers = list(self.workers.values())
        for w in workers:
            with w.ctl_lock:
                state = w.current_state()
                if w.has_live_turn() and w.handle is not None:
                    w.interrupt_requested = True
                    try:
                        w.handle.interrupt()
                    except Exception as e:
                        self.log(f"interrupt {w.name} failed: {e!r}")
                elif state in ACTIVE_STATES:
                    w.mark_interrupted("daemon shutdown")
        deadline = time.monotonic() + 10
        for w in workers:
            if w.consumer is not None:
                w.consumer.join(timeout=max(0.1, deadline - time.monotonic()))
        try:
            if self.server is not None:
                self.server.close()
        except OSError:
            pass

    def _active_workers_locked(self) -> list[Worker]:
        return [w for w in self.workers.values() if w.current_state() in ACTIVE_STATES]

    def _maintenance(self) -> None:
        now = time.monotonic()
        with self.reg_lock:
            for key, w in list(self.workers.items()):
                if w.current_state() in TERMINAL_STATES and w.consumer_finished():
                    terminal_since = w.terminal_since or now
                    if self.worker_gc_ttl_sec and now - terminal_since >= self.worker_gc_ttl_sec:
                        self.log(f"gc worker={w.name} repo={w.repo_key} state={w.current_state()}")
                        del self.workers[key]
            active = self._active_workers_locked()
        if active:
            return
        if self.idle_timeout_sec and now - self.last_activity >= self.idle_timeout_sec:
            self.log(f"idle timeout after {self.idle_timeout_sec:g}s → shutdown")
            threading.Thread(target=self._shutdown_now, daemon=True).start()

    def _cleanup(self) -> None:
        with self.reg_lock:
            workers = list(self.workers.values())
        for w in workers:
            w.detach_runtime_refs_if_idle(self, w.generation, "daemon cleanup", keep_thread=False)
        for p in (self.sock_path, self.pid_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        if self.lock_file is not None:
            try:
                self.lock_file.close()  # release flock
            except OSError:
                pass
        self.log("daemon stopped")

    # ── Socket Handling ──

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(SOCKET_TIMEOUT_SEC)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            req = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
            resp = self._dispatch(req)
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            if resp.pop("_shutdown", False):
                threading.Thread(target=self._shutdown_now, daemon=True).start()
        except Exception as e:
            self.log(f"conn error: {e!r}")
            try:
                conn.sendall((json.dumps({"ok": False, "error": str(e)}) + "\n").encode("utf-8"))
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        try:
            if cmd == "ping":
                return {"ok": True, "pid": os.getpid(), "idle_timeout_sec": self.idle_timeout_sec}
            if cmd == "start":
                return self.cmd_start(req)
            if cmd == "follow":
                return self.cmd_follow(req)
            if cmd == "steer":
                return self.cmd_steer(req)
            if cmd == "interrupt":
                return self.cmd_interrupt(req)
            if cmd == "shutdown":
                return self.cmd_shutdown(req)
            if cmd == "runtime_status":
                return self.cmd_runtime_status(req)
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        except Exception as e:
            self.log(f"cmd={cmd} error: {traceback.format_exc(limit=5)}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ── Command Implementations ──

    def _repo_from_req(self, req: dict) -> tuple[str, str, Path]:
        repo_key = req.get("repo_key")
        repo_root = req.get("repo_root")
        repo_home_raw = req.get("repo_home")
        if not repo_key or not repo_root or not repo_home_raw:
            raise ValueError("missing repo context")
        return str(repo_key), str(repo_root), Path(repo_home_raw)

    def _worker_key(self, repo_key: str, name: str) -> str:
        return registry_key(repo_key, name)

    def _load_worker_status(self, repo_home: Path, name: str) -> dict | None:
        sj = repo_home / "workers" / name / "status.json"
        if not sj.is_file():
            return None
        try:
            return json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def cmd_runtime_status(self, req: dict) -> dict:
        name = req["name"]
        repo_key, _, _ = self._repo_from_req(req)
        with self.reg_lock:
            w = self.workers.get(self._worker_key(repo_key, name))
        if w is None:
            return {"ok": True, "known": False, "pid": os.getpid()}
        with w.lock:
            state = w.status.get("state", "unknown")
            source = w.status.get("needs_input_source")
            daemon_pid = w.status.get("daemon_pid")
            codex = w.codex
        codex_proc = getattr(getattr(codex, "_client", None), "_proc", None)
        return {
            "ok": True,
            "known": True,
            "pid": os.getpid(),
            "worker_daemon_pid": daemon_pid,
            "state": state,
            "needs_input_source": source,
            "has_live_turn": w.has_live_turn(),
            "has_thread": w.thread is not None,
            "has_handle": w.handle is not None,
            "has_codex": codex is not None,
            "codex_pid": getattr(codex_proc, "pid", None),
        }

    def cmd_start(self, req: dict) -> dict:
        from openai_codex import Codex, Sandbox
        try:
            from openai_codex.types import ThreadSource
        except ImportError:
            ThreadSource = None

        name = req["name"]
        repo_key, repo_root, repo_home = self._repo_from_req(req)
        wid = self._worker_key(repo_key, name)
        brief = req["brief"]
        use_preamble = not req.get("no_preamble")
        raw_mode = req.get("mode")
        mode = MODE_MAP.get(raw_mode or "")
        if mode is None:
            # Enforced at the daemon boundary too: stale CLIs and direct socket clients
            # must not get an implicitly delegated worker.
            return {"ok": False,
                    "error": f"missing or invalid mode: {raw_mode!r} "
                             "(expected collab|collaborative|delegate|delegated)"}
        report = "decision" if req.get("report") == "decision" else "text"
        preamble = build_preamble(mode, report)
        turn_input = f"{preamble}\n{brief}" if use_preamble else brief
        file_brief = f"{preamble}\n---\n\n{brief}" if use_preamble else brief
        cwd = req.get("cwd") or os.getcwd()
        sandbox_key = SANDBOX_MAP.get(req.get("sandbox") or "full")
        if sandbox_key is None:
            return {"ok": False, "error": f"invalid sandbox: {req.get('sandbox')}"}
        model = req.get("model")
        effort = req.get("effort") or "medium"
        service_tier = req.get("service_tier")
        main_thread = bool(req.get("main_thread"))
        thread_source_label = "user" if main_thread else "subagent"
        thread_ephemeral = not main_thread
        if ThreadSource is None:
            return {"ok": False, "error": "openai-codex SDK does not expose ThreadSource"}

        with self.reg_lock:
            existing = self.workers.get(wid)
            if existing is not None:
                if existing.current_state() in ACTIVE_STATES:
                    return {"ok": False,
                            "error": f"worker '{name}' is already active ({existing.current_state()})"}
                # Even in a terminal state, reject reuse while the old consumer may still be writing files.
                if not existing.consumer_finished():
                    return {"ok": False,
                            "error": f"worker '{name}' previous stream is still finishing — retry shortly"}

            w = Worker(
                name,
                repo_home,
                repo_root,
                repo_key,
                cwd,
                sandbox_key,
                model,
                effort,
                service_tier,
                thread_source_label,
                thread_ephemeral,
                mode,
                report,
            )
            w.dir.mkdir(parents=True, exist_ok=True)
            # Restarting the same name creates a new worker, so reset prior outputs.
            for fname in ("events.log", "result.md", "debug-events.log", "decision.json", "decision.md"):
                try:
                    (w.dir / fname).unlink()
                except FileNotFoundError:
                    pass
            (w.dir / "brief.md").write_text(file_brief + "\n", encoding="utf-8")

            w.init_status(thread_id=None)
            try:
                w.codex = Codex()
                thread = w.codex.thread_start(
                    cwd=cwd,
                    # Hidden workers must be ephemeral subagent threads. Persistent user
                    # threads are opt-in because Codex Desktop lists them.
                    ephemeral=thread_ephemeral,
                    sandbox=getattr(Sandbox, sandbox_key),
                    thread_source=(ThreadSource.user if main_thread else ThreadSource.subagent),
                )
                w.thread = thread
                with w.lock:
                    w.status["thread_id"] = thread.id
                extra = {"output_schema": REPORT_SCHEMA} if report == "decision" else {}
                w.handle = thread.turn(
                    turn_input,
                    model=model, effort=effort, service_tier=service_tier,
                    **extra,
                )
            except Exception as e:
                # If SDK failure leaves a starting zombie, wait polls until timeout.
                w.mark_failed(f"start failed: {type(e).__name__}: {e}")
                w.detach_runtime_refs_if_idle(self, w.generation, "start failed", keep_thread=False)
                self.workers[wid] = w
                self.log(f"start worker={name} repo={repo_key} failed: {e!r}")
                return {"ok": False, "error": f"start failed: {type(e).__name__}: {e}"}

            w.generation = 1
            w.consumer = threading.Thread(
                target=w.consume_stream, args=(self, w.generation, w.handle), daemon=True,
                name=f"worker-{name}",
            )
            w.consumer.start()
            self.workers[wid] = w

        self.touch_activity()
        self.log(
            f"start worker={name} repo={repo_key} thread={thread.id} "
            f"cwd={cwd} sandbox={sandbox_key} thread_source={thread_source_label} "
            f"ephemeral={thread_ephemeral}"
        )
        return {"ok": True, "thread_id": thread.id}

    def cmd_follow(self, req: dict) -> dict:
        name = req["name"]
        repo_key, repo_root, repo_home = self._repo_from_req(req)
        wid = self._worker_key(repo_key, name)
        brief = req["brief"]
        use_preamble = not req.get("no_preamble")
        with self.reg_lock:
            w = self.workers.get(wid)
            if w is None:
                st = self._load_worker_status(repo_home, name)
                if st is not None:
                    return {"ok": False, "error":
                            f"worker '{name}' is not attached to this daemon; "
                            "same-thread follow expired after daemon restart or GC — start a new worker"}
                return {"ok": False, "error": f"unknown worker: {name}"}
            prev_state = w.current_state()
            # needs_input (waiting on QUESTION) can also follow; send the answer as a new turn on the same thread.
            if prev_state not in TERMINAL_STATES and prev_state != "needs_input":
                return {"ok": False, "error":
                        f"worker '{name}' is not in a terminal state ({prev_state})"}
            if w.thread is None:
                return {"ok": False, "error":
                        f"worker '{name}' has no live codex thread; terminal worker runtime was released — start a new worker"}
            # Reject follow until the old consumer fully exits (first guard against late-event contamination).
            if not w.consumer_finished():
                return {"ok": False,
                        "error": f"worker '{name}' previous stream is still finishing — retry shortly"}

            reminder = build_follow_reminder(w.mode, w.report)
            turn_input = f"{reminder}{brief}" if use_preamble else brief
            file_brief = f"{reminder}---\n\n{brief}" if use_preamble else brief
            w.reset_for_follow(file_brief)  # generation+1; also ignores any leftover old events (second guard)
            try:
                extra = {"output_schema": REPORT_SCHEMA} if w.report == "decision" else {}
                w.handle = w.thread.turn(
                    turn_input,
                    model=w.model, effort=w.effort, service_tier=w.service_tier,
                    **extra,
                )
            except Exception as e:
                w.mark_failed(f"follow turn failed (was {prev_state}): {type(e).__name__}: {e}")
                self.log(f"follow worker={name} failed: {e!r}")
                return {"ok": False, "error": f"follow failed: {type(e).__name__}: {e}"}
            with w.lock:
                gen = w.generation
                turns = w.status["turns"]
                thread_id = w.status["thread_id"]
            w.consumer = threading.Thread(
                target=w.consume_stream, args=(self, gen, w.handle), daemon=True,
                name=f"worker-{name}-t{turns}",
            )
            w.consumer.start()

        self.touch_activity()
        self.log(f"follow worker={name} repo={repo_key} thread={thread_id} turn#{turns}")
        return {"ok": True, "thread_id": thread_id, "turns": turns}

    def cmd_steer(self, req: dict) -> dict:
        name = req["name"]
        repo_key, _, _ = self._repo_from_req(req)
        with self.reg_lock:
            w = self.workers.get(self._worker_key(repo_key, name))
        if w is None:
            return {"ok": False, "error": f"unknown worker: {name}"}
        with w.ctl_lock:  # serialize concurrent steer/interrupt and re-check state inside the lock
            state = w.current_state()
            if state != "running":
                return {"ok": False, "error": f"worker '{name}' is not running ({state})"}
            if w.handle is None:
                return {"ok": False, "error": f"worker '{name}' has no live turn handle"}
            w.handle.steer(req["text"])
            w.log_event("steer", truncate(req["text"], 200))
        self.touch_activity()
        self.log(f"steer worker={name} repo={repo_key}")
        return {"ok": True}

    def cmd_interrupt(self, req: dict) -> dict:
        name = req["name"]
        repo_key, _, _ = self._repo_from_req(req)
        with self.reg_lock:
            w = self.workers.get(self._worker_key(repo_key, name))
        if w is None:
            return {"ok": False, "error": f"unknown worker: {name}"}
        with w.ctl_lock:
            state = w.current_state()
            if state in TERMINAL_STATES:
                return {"ok": True, "note": f"already terminal ({state})"}  # idempotent
            if state not in ACTIVE_STATES:
                return {"ok": False, "error": f"worker '{name}' is not active ({state})"}
            if w.interrupt_requested:
                return {"ok": True, "note": "interrupt already requested"}  # idempotent
            if w.handle is None:
                if state == "needs_input":
                    codex_to_close = None
                    with w.lock:
                        if w.status.get("needs_input_source") == "question":
                            w.interrupt_requested = True
                            w.status["state"] = "interrupted"
                            w._clear_needs_input_locked()
                            w.thread = None
                            codex_to_close = w.codex
                            w.codex = None
                            w.log_event("interrupt", "cleared final QUESTION wait")
                            w.write_status(force=True)
                            self.log(f"detached runtime refs worker={w.name} repo={w.repo_key} reason=question interrupted")
                    if codex_to_close is not None:
                        try:
                            codex_to_close.close()
                        except Exception as e:
                            self.log(f"codex.close worker={w.name} repo={w.repo_key} error: {e!r}")
                        self.touch_activity()
                        return {"ok": True, "note": "cleared QUESTION wait"}
                    with w.lock:
                        if w.status.get("state") == "interrupted":
                            return {"ok": True, "note": "cleared QUESTION wait"}
                return {"ok": False, "error": f"worker '{name}' has no live turn handle"}
            w.interrupt_requested = True
            try:
                w.handle.interrupt()
            except Exception as e:
                # Interrupt may fail right after a turn ends; keep the requested flag.
                w.log_event("interrupt", f"request failed: {type(e).__name__}: {e}")
                self.log(f"interrupt worker={name} sdk error: {e!r}")
                return {"ok": True, "note": f"interrupt call failed ({type(e).__name__}) — turn may have ended"}
            w.log_event("interrupt", "requested by client")
        self.touch_activity()
        self.log(f"interrupt worker={name} repo={repo_key}")
        return {"ok": True}

    def cmd_shutdown(self, req: dict) -> dict:
        force = bool(req.get("force"))
        with self.reg_lock:
            active = [f"{w.repo_key}:{w.name}" for w in self.workers.values()
                      if w.current_state() in ACTIVE_STATES]
        if active and not force:
            return {"ok": False,
                    "error": f"active workers: {', '.join(active)} — use --force to interrupt and shut down"}
        self.log(f"shutdown requested (force={force}, active={active})")
        return {"ok": True, "interrupted": active, "_shutdown": True}


# ── Client ─────────────────────────────────────────────────────────────────

def send_request(home: Path, req: dict, timeout: float = SOCKET_TIMEOUT_SEC) -> dict:
    sock_path = home / "meight.sock"
    if not sock_path.exists():
        raise SystemExit(f"daemon socket not found: {sock_path} (check that the daemon is running)")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                raise SystemExit("daemon closed connection without response")
            buf += chunk
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except OSError as e:
        raise SystemExit(f"daemon connection failed: {e}")
    except socket.timeout:
        raise SystemExit(f"daemon response timed out after {timeout}s")
    finally:
        s.close()


def query_runtime_status(home: Path, repo_home: Path, name: str, st: dict) -> dict | None:
    req = {
        "cmd": "runtime_status",
        "name": name,
        "repo_key": st.get("repo_key"),
        "repo_root": st.get("repo_root") or str(repo_home),
        "repo_home": str(repo_home),
    }
    if not req["repo_key"]:
        return None
    try:
        return send_request(home, req, timeout=5)
    except SystemExit:
        return None


def mark_worker_runtime_lost(repo_home: Path, name: str, st: dict, reason: str) -> dict:
    lost = dict(st)
    lost["state"] = "failed"
    lost["needs_input_detail"] = None
    lost["needs_input_source"] = None
    lost["needs_input_target"] = None
    lost["needs_input_kind"] = None
    lost["runtime_lost_detail"] = reason
    lost["updated_at"] = now_iso()
    worker_dir = repo_home / "workers" / name
    try:
        atomic_write_json(worker_dir / "status.json", lost)
        line = f"{now_iso()} [runtime/lost] {truncate(reason, EVENT_LINE_MAX - 60)}"
        with open(worker_dir / "events.log", "a", encoding="utf-8") as f:
            f.write(line[:EVENT_LINE_MAX] + "\n")
    except OSError:
        pass
    return lost


def expect_ok(resp: dict) -> dict:
    if not resp.get("ok"):
        print(f"error: {resp.get('error', 'unknown')}", file=sys.stderr)
        sys.exit(1)
    return resp


def read_brief(args) -> str:
    brief_file = getattr(args, "brief_file", None)
    if brief_file == "-":
        return sys.stdin.read()  # heredocs and similar inputs avoid shell quoting for long briefs
    if brief_file:
        return Path(brief_file).read_text(encoding="utf-8")
    if getattr(args, "brief", None):
        return args.brief
    raise SystemExit("--brief or --brief-file required")


def repo_home_for_cli(home: Path) -> Path:
    return Path(repo_context(home)["repo_home"])


def request_repo_context(home: Path) -> dict:
    return repo_context(home)


def load_statuses(repo_home: Path) -> list[dict]:
    out = []
    workers_dir = repo_home / "workers"
    if not workers_dir.is_dir():
        return out
    for d in sorted(workers_dir.iterdir()):
        sj = d / "status.json"
        if sj.is_file():
            try:
                out.append(json.loads(sj.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
    return out


def load_all_statuses(home: Path) -> list[dict]:
    out: list[dict] = []
    repos_dir = home / "repos"
    if not repos_dir.is_dir():
        return out
    for repo_home in sorted(repos_dir.iterdir()):
        if repo_home.is_dir():
            out.extend(load_statuses(repo_home))
    return out


def fmt_elapsed(st: dict) -> str:
    try:
        start = datetime.fromisoformat(st["started_at"])
        end = now_kst() if st.get("state") in ACTIVE_STATES else datetime.fromisoformat(st["updated_at"])
        sec = max(0, int((end - start).total_seconds()))
        if sec < 60:
            return f"{sec}s"
        return f"{sec // 60}m{sec % 60:02d}s"
    except (KeyError, ValueError):
        return "?"


def fmt_tokens(st: dict) -> str:
    t = st.get("tokens") or {}
    return f"in:{t.get('input', 0)} out:{t.get('output', 0)}"


def summary_line(st: dict, show_repo: bool = False) -> str:
    repo = f"{truncate(st.get('repo_key') or '-', 24):<24} " if show_repo else ""
    mode_full = st.get("mode") or "-"
    mode = {"collaborative": "collab", "delegated": "delegate"}.get(mode_full, mode_full)[:8]
    return (f"{repo}{st.get('name', '?'):<14} {st.get('state', '?'):<12} {mode:<9} "
            f"{fmt_elapsed(st):>8} "
            f"files:{len(st.get('files_changed') or []):<3} {fmt_tokens(st):<22} "
            f"{truncate(st.get('current_item') or '-', 60)}")


def print_status_table(statuses: list[dict], show_repo: bool = False) -> None:
    if not statuses:
        print("(no workers)")
        return
    repo = f"{'REPO':<24} " if show_repo else ""
    print(f"{repo}{'NAME':<14} {'STATE':<12} {'MODE':<9} {'ELAPSED':>8} {'FILES':<9} {'TOKENS':<22} CURRENT")
    for st in statuses:
        print(summary_line(st, show_repo=show_repo))


# ── CLI Commands ───────────────────────────────────────────────────────────

def cmd_daemon(args, home: Path) -> int:
    return Daemon(home, idle_timeout_sec=getattr(args, "idle_timeout_sec", None)).run()


def require_mode(args) -> None:
    """Validate --mode before any side effect (daemon auto-start included)."""
    if not MODE_MAP.get(getattr(args, "mode", None) or ""):
        print(MODE_TEACHING_ERROR, file=sys.stderr)
        raise SystemExit(2)


def start_request(args, home: Path) -> dict:
    require_mode(args)
    # --fast/--no-fast is the user-facing knob; map it to a codex service tier.
    # priority = Fast; default = a non-priority tier. The default is deliberately non-Fast.
    fast = bool(getattr(args, "fast", False))
    service_tier = "priority" if fast else "default"
    req = {
        "cmd": "start", "name": args.name, "brief": read_brief(args),
        "cwd": str(Path(args.cwd).resolve()) if args.cwd else os.getcwd(),
        "sandbox": args.sandbox, "model": args.model, "effort": args.effort,
        "service_tier": service_tier,
        "no_preamble": args.no_preamble,
        "main_thread": getattr(args, "main_thread", False),
        "mode": args.mode,
        "report": args.report,
    }
    req.update(request_repo_context(home))
    return send_request(home, req)


def cmd_start(args, home: Path) -> int:
    resp = expect_ok(start_request(args, home))
    print(f"started worker '{args.name}' thread={resp.get('thread_id')}")
    return 0


def cmd_follow(args, home: Path) -> int:
    req = {
        "cmd": "follow", "name": args.name, "brief": read_brief(args),
        "no_preamble": args.no_preamble,
    }
    req.update(request_repo_context(home))
    resp = expect_ok(send_request(home, req))
    print(f"follow turn #{resp.get('turns')} on worker '{args.name}' thread={resp.get('thread_id')}")
    return 0


def cmd_steer(args, home: Path) -> int:
    req = {"cmd": "steer", "name": args.name, "text": args.text}
    req.update(request_repo_context(home))
    expect_ok(send_request(home, req))
    print(f"steered '{args.name}'")
    return 0


def cmd_interrupt(args, home: Path) -> int:
    req = {"cmd": "interrupt", "name": args.name}
    req.update(request_repo_context(home))
    expect_ok(send_request(home, req))
    print(f"interrupt requested for '{args.name}'")
    return 0


def cmd_status(args, home: Path) -> int:
    name = getattr(args, "name", None)
    repo_home = repo_home_for_cli(home)
    if name:
        sj = repo_home / "workers" / name / "status.json"
        if not sj.is_file():
            print(f"no status for worker '{name}'", file=sys.stderr)
            return 1
        st = json.loads(sj.read_text(encoding="utf-8"))
        if getattr(args, "json", False):
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            print(summary_line(st))
            for key in ("thread_id", "turn_id", "repo_root", "repo_key", "cwd",
                        "sandbox", "model", "effort", "service_tier", "thread_source",
                        "thread_ephemeral", "daemon_pid", "started_at", "updated_at",
                        "turns", "mode", "report", "needs_input_source",
                        "needs_input_target", "needs_input_kind", "needs_input_detail",
                        "runtime_lost_detail"):
                print(f"  {key}: {st.get(key)}")
            if st.get("plan"):
                print("  plan:")
                for step in st["plan"]:
                    print(f"    {step}")
            if st.get("files_changed"):
                print("  files_changed:")
                for f in st["files_changed"]:
                    print(f"    {f}")
            if st.get("last_message_tail"):
                print(f"  last_message_tail: {truncate(st['last_message_tail'], 200)}")
        return 0
    all_repos = getattr(args, "all_repos", False)
    statuses = load_all_statuses(home) if all_repos else load_statuses(repo_home)
    if getattr(args, "json", False):
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
    else:
        print_status_table(statuses, show_repo=all_repos)
    return 0


def cmd_result(args, home: Path) -> int:
    worker_dir = repo_home_for_cli(home) / "workers" / args.name
    decision = worker_dir / "decision.md"
    result = worker_dir / "result.md"
    rp = result if getattr(args, "raw", False) or not decision.is_file() else decision
    if not rp.is_file():
        print(f"no result for worker '{args.name}'", file=sys.stderr)
        return 1
    print(rp.read_text(encoding="utf-8"), end="")
    return 0


def classify_wait_state(st: dict) -> int | None:
    """Map a status dict to a wait exit code. None means keep polling.
    needs_input can exit 3 only when source=="question" (final QUESTION);
    wait_for_worker checks daemon attachment before exposing that exit.
    tool/approval waits are treated as active until stream-end cleanup."""
    state = st.get("state")
    if state in TERMINAL_STATES:
        return 0 if state == "completed" else 2
    if state == "needs_input" and st.get("needs_input_source") == "question":
        return 3
    return None


def wait_for_worker(home: Path, repo_home: Path, name: str, timeout: float | None,
                    progress: float = 300.0) -> int:
    sj = repo_home / "workers" / name / "status.json"
    now = time.monotonic()
    deadline = now + timeout if timeout else None
    next_progress = now + progress if progress and progress > 0 else None
    dead_strikes = 0  # avoid false positives from transient ping failures while the daemon is busy
    while True:
        st = None
        if sj.is_file():
            try:
                st = json.loads(sj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                st = None
        if st is not None:
            if st.get("state") in ACTIVE_STATES:
                runtime = query_runtime_status(home, repo_home, name, st)
                if runtime and runtime.get("ok"):
                    dead_strikes = 0
                    if not runtime.get("known"):
                        reason = (
                            f"worker is active on disk but not attached to daemon pid "
                            f"{runtime.get('pid')} (recorded daemon_pid={st.get('daemon_pid')})"
                        )
                        st = mark_worker_runtime_lost(repo_home, name, st, reason)
                        print(summary_line(st))
                        return 2
                    code = classify_wait_state(st)
                    if code is not None:
                        print(summary_line(st))
                        return code
            else:
                code = classify_wait_state(st)
                if code is not None:
                    print(summary_line(st))
                    return code
        # Daemon death check: ping success means definitely alive. pid alone is insufficient due to pid reuse.
        if probe_daemon_socket(home / "meight.sock"):
            dead_strikes = 0
        else:
            dead_strikes += 1
            pid = read_daemon_pid(home)
            pid_dead = pid is None or not pid_alive(pid)
            if pid_dead or dead_strikes >= 2:
                print(f"{name:<14} daemon-dead (pid={pid})")
                return 4
        if deadline is not None and time.monotonic() > deadline:
            print(f"{name:<14} timeout after {timeout}s "
                  f"(state={st.get('state') if st else 'unknown'})")
            return 1
        # Periodic progress heartbeat — print one status line every `progress` seconds WITHOUT ending the
        # wait. Checked AFTER terminal/timeout/daemon-dead so a heartbeat never trails a real exit in the
        # .output. Backgrounded, these accumulate so the dispatcher reads mid-run progress without
        # re-waiting. Clamp to now+progress so a slept/blocked process doesn't emit catch-up bursts.
        # On by default (300s); `--progress 0` turns it off.
        if next_progress is not None and time.monotonic() >= next_progress:
            if st is not None:
                print(f"  [{time.strftime('%H:%M:%S')}] {summary_line(st)}", flush=True)
            next_progress = time.monotonic() + progress
        time.sleep(1)


def cmd_wait(args, home: Path) -> int:
    return wait_for_worker(home, repo_home_for_cli(home), args.name, args.timeout, args.progress)


def ensure_daemon(home: Path) -> bool:
    """Auto-start the daemon detached after ping failure and poll until it responds."""
    if probe_daemon_socket(home / "meight.sock"):
        return True
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "daemon.log", "a", encoding="utf-8") as log_f:
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "daemon",
                "--idle-timeout-sec",
                MANAGED_DAEMON_IDLE_TIMEOUT_SEC,
            ],
            stdout=log_f, stderr=log_f, stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=managed_daemon_env(home),
        )
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if probe_daemon_socket(home / "meight.sock"):
            return True
        time.sleep(0.25)
    return False


def cmd_dispatch(args, home: Path) -> int:
    """One-shot: auto-start daemon -> start -> wait -> print full result.md. Exit matches wait."""
    require_mode(args)  # before ensure_daemon: a rejected call must not auto-start a daemon
    if not ensure_daemon(home):
        print("error: daemon auto-start failed — check daemon.log", file=sys.stderr)
        return 4
    resp = start_request(args, home)
    if not resp.get("ok"):
        print(f"error: {resp.get('error', 'unknown')}", file=sys.stderr)
        return 1
    print(f"started worker '{args.name}' thread={resp.get('thread_id')}", flush=True)
    repo_home = repo_home_for_cli(home)
    code = wait_for_worker(home, repo_home, args.name, args.timeout, args.progress)
    worker_dir = repo_home / "workers" / args.name
    decision = worker_dir / "decision.md"
    rp = decision if decision.is_file() else worker_dir / "result.md"
    if code in (0, 2, 3) and rp.is_file():
        print("--- result ---")
        print(rp.read_text(encoding="utf-8"), end="", flush=True)
    if getattr(args, "shutdown_when_idle", False) and code in (0, 2, 3):
        resp = send_request(home, {"cmd": "shutdown", "force": False})
        if resp.get("ok"):
            print("daemon shutdown ok", flush=True)
        else:
            print(f"daemon kept alive: {resp.get('error')}", file=sys.stderr)
    return code


def cmd_reply(args, home: Path) -> int:
    """One-shot reply: follow -> wait -> print only the latest turn result. For QUESTION (exit 3)."""
    req = {
        "cmd": "follow", "name": args.name, "brief": read_brief(args),
        "no_preamble": args.no_preamble,
    }
    req.update(request_repo_context(home))
    resp = expect_ok(send_request(home, req))
    print(f"reply turn #{resp.get('turns')} on worker '{args.name}'", flush=True)
    repo_home = repo_home_for_cli(home)
    code = wait_for_worker(home, repo_home, args.name, args.timeout, args.progress)
    worker_dir = repo_home / "workers" / args.name
    decision = worker_dir / "decision.md"
    rp = decision if decision.is_file() else worker_dir / "result.md"
    if code in (0, 2, 3) and rp.is_file():
        text = rp.read_text(encoding="utf-8")
        if rp.name == "result.md":
            marker = "\n---\n## Turn "
            if marker in text:
                text = "## Turn " + text.rsplit(marker, 1)[1]
        print("--- result ---")
        print(text, end="", flush=True)
    if getattr(args, "shutdown_when_idle", False) and code in (0, 2, 3):
        resp = send_request(home, {"cmd": "shutdown", "force": False})
        if resp.get("ok"):
            print("daemon shutdown ok", flush=True)
        else:
            print(f"daemon kept alive: {resp.get('error')}", file=sys.stderr)
    return code


def cmd_shutdown(args, home: Path) -> int:
    resp = send_request(home, {"cmd": "shutdown", "force": args.force})
    if not resp.get("ok"):
        print(f"refused: {resp.get('error')}", file=sys.stderr)
        return 1
    interrupted = resp.get("interrupted") or []
    print("shutdown ok" + (f" (interrupted: {', '.join(interrupted)})" if interrupted else ""))
    return 0


def cmd_ping(args, home: Path) -> int:
    resp = expect_ok(send_request(home, {"cmd": "ping"}, timeout=10))
    print(f"pong (daemon pid {resp.get('pid')}, idle_timeout_sec={resp.get('idle_timeout_sec')})")
    return 0


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_payload(home: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(Path(__file__).resolve()),
            "daemon",
            "--idle-timeout-sec",
            MANAGED_DAEMON_IDLE_TIMEOUT_SEC,
        ],
        "RunAtLoad": True,
        # KeepAlive stays off; managed daemon launches disable idle shutdown so live
        # steer/follow/interrupt channels remain attached until explicit shutdown.
        "KeepAlive": False,
        "EnvironmentVariables": {
            **({"PATH": os.environ["PATH"]} if os.environ.get("PATH") else {}),
            "MEIGHT_HOME": str(home),
            "MEIGHT_IDLE_TIMEOUT_SEC": MANAGED_DAEMON_IDLE_TIMEOUT_SEC,
        },
        "StandardOutPath": str(home / "launchd.out.log"),
        "StandardErrorPath": str(home / "launchd.err.log"),
    }


def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def cmd_launchd_install(args, home: Path) -> int:
    path = launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(launchd_payload(home), sort_keys=False))
    print(f"wrote {path}")
    if args.load:
        subprocess.run(["launchctl", "bootout", launchctl_domain(), str(path)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["launchctl", "bootstrap", launchctl_domain(), str(path)], check=True)
        print(f"loaded {LAUNCHD_LABEL}")
    return 0


def cmd_launchd_uninstall(args, home: Path) -> int:
    path = launchd_plist_path()
    subprocess.run(["launchctl", "bootout", launchctl_domain(), str(path)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        path.unlink()
        print(f"removed {path}")
    except FileNotFoundError:
        print(f"not installed: {path}")
    return 0


def cmd_launchd_status(args, home: Path) -> int:
    path = launchd_plist_path()
    print(f"plist: {path} ({'present' if path.exists() else 'missing'})")
    proc = subprocess.run(["launchctl", "print", f"{launchctl_domain()}/{LAUNCHD_LABEL}"],
                          text=True, capture_output=True)
    if proc.returncode == 0:
        print(proc.stdout, end="")
        return 0
    print("launchd service not loaded")
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr)
    return 1


# ── argparse ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meight", description="claude-codex-meight: parallel Codex worker harness")
    sub = p.add_subparsers(dest="command", required=True)

    dp = sub.add_parser("daemon", help="foreground daemon")
    dp.add_argument("--idle-timeout-sec", type=float,
                    help="override idle shutdown seconds; 0 disables")
    dp.set_defaults(fn=cmd_daemon)
    sub.add_parser("ping", help="daemon health check").set_defaults(fn=cmd_ping)

    sp = sub.add_parser("launchd", help="manage optional macOS LaunchAgent for the global daemon")
    launchd_sub = sp.add_subparsers(dest="launchd_command", required=True)
    lp = launchd_sub.add_parser("install", help="write the LaunchAgent plist")
    lp.add_argument("--load", action="store_true", help="also load it with launchctl bootstrap")
    lp.set_defaults(fn=cmd_launchd_install)
    launchd_sub.add_parser("uninstall", help="unload and remove the LaunchAgent plist").set_defaults(
        fn=cmd_launchd_uninstall)
    launchd_sub.add_parser("status", help="show LaunchAgent status").set_defaults(fn=cmd_launchd_status)

    def add_start_options(sp):
        sp.add_argument("--brief-file", help="read from stdin when '-'")
        sp.add_argument("--brief")
        sp.add_argument("--cwd")
        sp.add_argument("--mode", choices=sorted(MODE_MAP.keys()))
        sp.add_argument("--report", choices=["text", "decision"], default="text")
        sp.add_argument("--sandbox", default="full", choices=sorted(SANDBOX_MAP.keys()))
        sp.add_argument("--model")
        sp.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh"])
        sp.add_argument("--fast", action=argparse.BooleanOptionalAction, default=False,
                        help="use the priority service tier (codex 'Fast'); omitted or --no-fast uses the non-priority default tier")
        sp.add_argument("--no-preamble", action="store_true", help="disable prepending the harness protocol preamble")
        sp.add_argument("--main-thread", action="store_true",
                        help="use ThreadSource.user instead of the default hidden ThreadSource.subagent — only for tools that require a visible/main Codex Desktop thread")

    sp = sub.add_parser("start", help="start a new worker")
    sp.add_argument("name")
    add_start_options(sp)
    sp.set_defaults(fn=cmd_start)

    sp = sub.add_parser("dispatch", help="one-shot: auto-start daemon + start + wait + print result")
    sp.add_argument("name")
    add_start_options(sp)
    sp.add_argument("--timeout", type=float, default=1800)
    sp.add_argument("--progress", type=float, default=300.0,
                    help="seconds between status heartbeats while waiting; 0=off")
    sp.add_argument("--shutdown-when-idle", action="store_true",
                    help="after a terminal result, ask the global daemon to stop if no workers are active")
    sp.set_defaults(fn=cmd_dispatch)

    sp = sub.add_parser("follow", help="new turn on the same thread for a terminal/QUESTION worker")
    sp.add_argument("name")
    sp.add_argument("--brief-file", help="read from stdin when '-'")
    sp.add_argument("--brief")
    sp.add_argument("--no-preamble", action="store_true")
    sp.set_defaults(fn=cmd_follow)

    sp = sub.add_parser("reply", help="one-shot reply: follow + wait + print latest turn result (for QUESTION)")
    sp.add_argument("name")
    sp.add_argument("--brief-file", help="read from stdin when '-'")
    sp.add_argument("--brief")
    sp.add_argument("--no-preamble", action="store_true")
    sp.add_argument("--timeout", type=float, default=1800)
    sp.add_argument("--progress", type=float, default=300.0,
                    help="seconds between status heartbeats while waiting; 0=off")
    sp.add_argument("--shutdown-when-idle", action="store_true",
                    help="after a terminal result, ask the global daemon to stop if no workers are active")
    sp.set_defaults(fn=cmd_reply)

    sp = sub.add_parser("steer", help="inject mid-turn text into a running turn")
    sp.add_argument("name")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_steer)

    sp = sub.add_parser("interrupt", help="interrupt a turn")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_interrupt)

    sp = sub.add_parser("status", help="worker status (daemon not required)")
    sp.add_argument("name", nargs="?")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--all-repos", action="store_true", help="show workers from every repo namespace")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("list", help="status alias")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--all-repos", action="store_true", help="show workers from every repo namespace")
    sp.set_defaults(fn=cmd_status, name=None)

    sp = sub.add_parser("result", help="print decision.md when present, else result.md")
    sp.add_argument("name")
    sp.add_argument("--raw", action="store_true", help="print raw result.md even when decision.md exists")
    sp.set_defaults(fn=cmd_result)

    sp = sub.add_parser("wait", help="poll until terminal state")
    sp.add_argument("name")
    sp.add_argument("--timeout", type=float, default=None)
    sp.add_argument("--progress", type=float, default=300.0,
                    help="seconds between status heartbeats while waiting; 0=off")
    sp.set_defaults(fn=cmd_wait)

    sp = sub.add_parser("shutdown", help="shut down daemon")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_shutdown)

    return p


def main() -> int:
    args = build_parser().parse_args()
    home = state_home()
    return args.fn(args, home)


if __name__ == "__main__":
    sys.exit(main())
