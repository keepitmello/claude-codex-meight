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

# Bidirectional workers: automatically prepend this before start/follow briefs (disable with --no-preamble)
PREAMBLE = """[Harness protocol — applies on top of the task below]
- You are the tech lead and you report to a planner (the orchestrator): you own HOW, technical judgment, technical design, implementation, and verification; the planner owns WHAT/WHY, priority, scope, UX/product judgment, review, and final sign-off. You're strong on detail (races, type drift, edge cases), the planner holds the product direction — run it two-way.
- Before starting work, read the Codex Worker Guide at `/Users/wy/.claude/claude-codex-meight/docs/codex-worker-guide.md` and follow it; if inaccessible, continue from this preamble and record `GUIDE NOT READ: <reason>` in your report or evidence artifact.
- Do not run `git commit` or `git push`; git sign-off belongs to the planner/orchestrator. You may suggest a commit message, but never create the commit or push it yourself.
- Your report to the planner is a DECISION SURFACE, not a technical log. Lead with conclusions, concise verification evidence needed for sign-off, and anything needing the planner's judgment (scope/UX/product-priority/tradeoff calls). Keep the planner out of technical execution/detail: keep detailed technical findings, review logs, command output, and implementation reasoning out of the report body; put them in a worker-unique evidence artifact when details are needed.
- When you write a detailed evidence artifact, make it self-contained for a follow-up worker, not just an archive for yourself: include the actionable handoff (what the next worker should do), relevant file/line evidence, verification commands, and any open decisions — so the next worker can pick up from that artifact alone and the planner never has to re-read or re-translate technical logs into a new brief.
- If you leave non-code artifact documents such as reports, analyses, evidence, or handoffs in the working directory (cwd), do not use fixed generic names like `result.md`; parallel workers in the same cwd can overwrite each other and pollute the repo. Use a worker-unique name such as `<worker-name>-evidence.md` or `<worker-name>-<short-topic>.md`, and keep that worker-name prefix for every cwd artifact document you create. The isolated worker report at `~/.meight/repos/.../workers/<name>/result.md` is the final message record, not a separate hidden detail channel. Code changes should be made directly in their source paths and are not part of this artifact-document naming rule.
- You are a teammate on this work, not a tool that only executes. If you see a better approach, the brief rests on a wrong assumption, or there's a tradeoff worth weighing before a direction is locked in, don't silently comply or guess — raise it in a final paragraph starting with `QUESTION:` only when it needs a planner-owned decision: scope, UX/product behavior, priority, risk appetite, irreversible action, or acceptance-criteria conflict. Local implementation choices are yours to decide; record them as judgment calls in the report or evidence artifact.
- Likewise, when you are genuinely blocked on a decision or missing information that only the orchestrator can provide, end with a `QUESTION:` paragraph stating exactly what you need instead of guessing. Resolve technical uncertainty with evidence first; if it does not change planner-owned direction, decide locally and report the judgment call.
"""

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
                 thread_source: str = "subagent", thread_ephemeral: bool = True):
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
        self.thread = None       # openai_codex.Thread (kept while daemon lives -> reused for follow)
        self.handle = None       # TurnHandle
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
        # "question" (final QUESTION; wait exits 3) | "tool" (mid-turn wait; treated as active)
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
            "cwd": self.cwd,
            "sandbox": self.sandbox.replace("_", "-"),
            "model": self.model,
            "effort": self.effort,
            "service_tier": self.service_tier,
            "thread_source": self.thread_source,
            "thread_ephemeral": self.thread_ephemeral,
            "current_item": None,
            "plan": [],
            "files_changed": [],
            "tokens": {"input": 0, "cached": 0, "output": 0},
            "last_message_tail": "",
            "needs_input_detail": None,
            "needs_input_source": None,
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
                    self.status["needs_input_detail"] = None
                    self.status["needs_input_source"] = None
                    self.log_event("stream/exception", f"{type(e).__name__}: {e}")
                    self.write_status(force=True)
            daemon.log(f"worker={self.name} stream exception: {traceback.format_exc(limit=3)}")
        finally:
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
                self.status["needs_input_detail"] = None
                self.status["needs_input_source"] = None
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
                self.status["needs_input_detail"] = None
                self.status["needs_input_source"] = None
                self.write_status(force=True)

        elif method == "tool/requestUserInput" or method.endswith("/requestApproval"):
            # With config approval=never this should not happen; defensive handling only (v1: no auto-reply).
            self.status["state"] = "needs_input"
            self.status["needs_input_detail"] = truncate(json.dumps(p, ensure_ascii=False, default=str), 500)
            self.status["needs_input_source"] = "tool"  # mid-turn wait, not final; wait treats it as active
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
            question = self._extract_question()
            if question:
                self.status["state"] = "needs_input"
                self.status["needs_input_detail"] = question if len(question) <= 500 else question[:499] + "…"
                self.status["needs_input_source"] = "question"
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
            self.status["needs_input_detail"] = None
            self.status["needs_input_source"] = None
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
                self.status["needs_input_detail"] = None
                self.status["needs_input_source"] = None
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
                "current_item": None,
                "plan": [],
                "files_changed": [],
                "last_message_tail": "",
                "needs_input_detail": None,
                "needs_input_source": None,
                "turns": turns,
            })
            self.write_status(force=True)

    def current_state(self) -> str:
        with self.lock:
            return self.status.get("state", "unknown")

    def mark_failed(self, reason: str) -> None:
        with self.lock:
            self.status["state"] = "failed"
            self.log_event("daemon/error", reason)
            self.write_status(force=True)

    def consumer_finished(self, join_timeout: float = 3.0) -> bool:
        if self.consumer is None:
            return True
        self.consumer.join(timeout=join_timeout)
        return not self.consumer.is_alive()


# ── Daemon ─────────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self, home: Path):
        self.home = home
        self.sock_path = home / "meight.sock"
        self.pid_path = home / "daemon.pid"
        self.log_path = home / "daemon.log"
        self.codex = None
        self.workers: dict[str, Worker] = {}
        self.reg_lock = threading.Lock()
        self.shutting_down = threading.Event()
        self.server: socket.socket | None = None
        self.lock_file = None  # flock handle kept while the daemon is alive
        self.idle_timeout_sec = _env_float("MEIGHT_IDLE_TIMEOUT_SEC", DEFAULT_IDLE_TIMEOUT_SEC)
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

        from openai_codex import Codex
        self.codex = Codex()

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.sock_path))
        self.server.listen(16)
        self.server.settimeout(1.0)
        self.pid_path.write_text(str(os.getpid()) + "\n")

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        self.log(f"daemon started pid={os.getpid()} home={self.home}")
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
                if w.current_state() in ACTIVE_STATES and w.handle is not None:
                    w.interrupt_requested = True
                    try:
                        w.handle.interrupt()
                    except Exception as e:
                        self.log(f"interrupt {w.name} failed: {e!r}")
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
        try:
            if self.codex is not None:
                self.codex.close()
        except Exception as e:
            self.log(f"codex.close() error: {e!r}")
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
                return {"ok": True, "pid": os.getpid()}
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

    def _resume_worker_locked(self, repo_key: str, repo_root: str, repo_home: Path, name: str):
        sj = repo_home / "workers" / name / "status.json"
        if not sj.is_file():
            return None
        try:
            st = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        thread_id = st.get("thread_id")
        if not thread_id:
            return None

        from openai_codex import Sandbox

        sandbox_key = str(st.get("sandbox") or "full-access").replace("-", "_")
        if sandbox_key not in set(SANDBOX_MAP.values()):
            sandbox_key = "full_access"
        cwd = st.get("cwd") or repo_root
        model = st.get("model")
        effort = st.get("effort") or "medium"
        service_tier = st.get("service_tier")
        thread_source = st.get("thread_source") or "subagent"
        thread_ephemeral = bool(st.get("thread_ephemeral", thread_source != "user"))

        thread = self.codex.thread_resume(
            thread_id,
            cwd=cwd,
            sandbox=getattr(Sandbox, sandbox_key),
            model=model,
            service_tier=service_tier,
        )
        w = Worker(
            name,
            repo_home,
            st.get("repo_root") or repo_root,
            st.get("repo_key") or repo_key,
            cwd,
            sandbox_key,
            model,
            effort,
            service_tier,
            thread_source,
            thread_ephemeral,
        )
        w.status = st
        w.thread = thread
        w.generation = int(st.get("turns") or 1)
        if w.current_state() in TERMINAL_STATES:
            w.terminal_since = time.monotonic()
        self.workers[self._worker_key(repo_key, name)] = w
        self.log(f"resumed worker={name} repo={repo_key} thread={thread_id}")
        return w

    def cmd_start(self, req: dict) -> dict:
        from openai_codex import Sandbox
        try:
            from openai_codex.types import ThreadSource
        except ImportError:
            ThreadSource = None

        name = req["name"]
        repo_key, repo_root, repo_home = self._repo_from_req(req)
        wid = self._worker_key(repo_key, name)
        brief = req["brief"]
        use_preamble = not req.get("no_preamble")
        turn_input = f"{PREAMBLE}\n{brief}" if use_preamble else brief
        file_brief = f"{PREAMBLE}\n---\n\n{brief}" if use_preamble else brief
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
            )
            w.dir.mkdir(parents=True, exist_ok=True)
            # Restarting the same name creates a new worker, so reset prior outputs.
            for fname in ("events.log", "result.md", "debug-events.log"):
                try:
                    (w.dir / fname).unlink()
                except FileNotFoundError:
                    pass
            (w.dir / "brief.md").write_text(file_brief + "\n", encoding="utf-8")

            w.init_status(thread_id=None)
            try:
                thread = self.codex.thread_start(
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
                w.handle = thread.turn(
                    turn_input,
                    model=model, effort=effort, service_tier=service_tier,
                )
            except Exception as e:
                # If SDK failure leaves a starting zombie, wait polls until timeout.
                w.mark_failed(f"start failed: {type(e).__name__}: {e}")
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
        turn_input = f"{PREAMBLE}\n{brief}" if use_preamble else brief
        file_brief = f"{PREAMBLE}\n---\n\n{brief}" if use_preamble else brief
        with self.reg_lock:
            w = self.workers.get(wid)
            if w is None:
                w = self._resume_worker_locked(repo_key, repo_root, repo_home, name)
            if w is None:
                return {"ok": False, "error": f"unknown worker: {name}"}
            prev_state = w.current_state()
            # needs_input (waiting on QUESTION) can also follow; send the answer as a new turn on the same thread.
            if prev_state not in TERMINAL_STATES and prev_state != "needs_input":
                return {"ok": False, "error":
                        f"worker '{name}' is not in a terminal state ({prev_state})"}
            if w.thread is None:
                return {"ok": False, "error":
                        f"worker '{name}' has no codex thread (start failed earlier) — use 'start' instead"}
            # Reject follow until the old consumer fully exits (first guard against late-event contamination).
            if not w.consumer_finished():
                return {"ok": False,
                        "error": f"worker '{name}' previous stream is still finishing — retry shortly"}

            w.reset_for_follow(file_brief)  # generation+1; also ignores any leftover old events (second guard)
            try:
                w.handle = w.thread.turn(
                    turn_input,
                    model=w.model, effort=w.effort, service_tier=w.service_tier,
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
    return (f"{repo}{st.get('name', '?'):<14} {st.get('state', '?'):<12} {fmt_elapsed(st):>8} "
            f"files:{len(st.get('files_changed') or []):<3} {fmt_tokens(st):<22} "
            f"{truncate(st.get('current_item') or '-', 60)}")


def print_status_table(statuses: list[dict], show_repo: bool = False) -> None:
    if not statuses:
        print("(no workers)")
        return
    repo = f"{'REPO':<24} " if show_repo else ""
    print(f"{repo}{'NAME':<14} {'STATE':<12} {'ELAPSED':>8} {'FILES':<9} {'TOKENS':<22} CURRENT")
    for st in statuses:
        print(summary_line(st, show_repo=show_repo))


# ── CLI Commands ───────────────────────────────────────────────────────────

def cmd_daemon(args, home: Path) -> int:
    return Daemon(home).run()


def start_request(args, home: Path) -> dict:
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
                        "thread_ephemeral", "started_at", "updated_at", "turns",
                        "needs_input_source", "needs_input_detail"):
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
    rp = repo_home_for_cli(home) / "workers" / args.name / "result.md"
    if not rp.is_file():
        print(f"no result for worker '{args.name}'", file=sys.stderr)
        return 1
    print(rp.read_text(encoding="utf-8"), end="")
    return 0


def classify_wait_state(st: dict) -> int | None:
    """Map a status dict to a wait exit code. None means keep polling.
    needs_input exits 3 only when source=="question" (final QUESTION);
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
        # .output. Backgrounded, these accumulate so the orchestrator reads mid-run progress without
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
            [sys.executable, str(Path(__file__).resolve()), "daemon"],
            stdout=log_f, stderr=log_f, stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "MEIGHT_HOME": str(home)},
        )
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if probe_daemon_socket(home / "meight.sock"):
            return True
        time.sleep(0.25)
    return False


def cmd_dispatch(args, home: Path) -> int:
    """One-shot: auto-start daemon -> start -> wait -> print full result.md. Exit matches wait."""
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
    rp = repo_home / "workers" / args.name / "result.md"
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
    rp = repo_home / "workers" / args.name / "result.md"
    if code in (0, 2, 3) and rp.is_file():
        text = rp.read_text(encoding="utf-8")
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
    print(f"pong (daemon pid {resp.get('pid')})")
    return 0


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_payload(home: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "daemon"],
        "RunAtLoad": True,
        # Do not KeepAlive: the daemon has its own idle timeout, and CLI auto-start
        # remains the on-demand recovery path.
        "KeepAlive": False,
        "EnvironmentVariables": {
            **({"PATH": os.environ["PATH"]} if os.environ.get("PATH") else {}),
            "MEIGHT_HOME": str(home),
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

    sub.add_parser("daemon", help="foreground daemon").set_defaults(fn=cmd_daemon)
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

    sp = sub.add_parser("result", help="print result.md")
    sp.add_argument("name")
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
