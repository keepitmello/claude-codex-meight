#!/usr/bin/env python3
"""claude-codex-meight: Harness for running multiple Codex workers in parallel. See SPEC.md for the contract.

Run: .venv/bin/python meight.py <cmd>
Observe by pulling disk digests, steer mid-turn, and push only through wait.
"""

from __future__ import annotations

import argparse
import codecs
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import stat
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
ACTIVE_STATES = {"target_preparing", "starting", "running", "needs_input"}
SOCKET_TIMEOUT_SEC = 60.0  # start/follow may take several seconds for thread_start+turn RPCs
TOOL_WAIT_GRACE_SEC = 15.0  # tool/approval waits older than this surface as exit 3 instead of hanging
STATUS_THROTTLE_SEC = 2.0
EVENT_LINE_MAX = 300
MESSAGE_LOG_NAME = "messages.log"  # unthrottled full agentMessage text for `watch`
WATCH_POLL_SEC = 0.25
WATCH_TAIL_CHARS = 2_000
WATCH_ELAPSED_RE = re.compile(r"^(?P<label>.*) \((?P<seconds>\d+)s\)\Z")
RECOVERY_ARTIFACT_MAX_CHARS = 24_000
DEFAULT_IDLE_TIMEOUT_SEC = 30 * 60
DEFAULT_WORKER_GC_TTL_SEC = 60 * 60
STATUS_ARCHIVE_AFTER_SEC = 6 * 60 * 60
DEFAULT_SESSION_RETENTION_SEC = 30 * 24 * 60 * 60
RETENTION_CLEANUP_INTERVAL_SEC = 60 * 60
MAX_SOCKET_REQUEST_BYTES = 1024 * 1024
LAUNCHD_LABEL = "com.keepitmello.meight"
MANAGED_DAEMON_IDLE_TIMEOUT_SEC = "0"
LAUNCHD_TRANSFER_TIMEOUT_SEC = 15.0
WORKER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
PRUNE_TOMBSTONE_PREFIX = ".meight-prune-"
# Capacity is provider-side pressure, so keep the selected model, effort, tier,
# and thread fixed while waiting it out. The retry policy is intentionally
# code-only: a generous wall-clock budget with capped exponential backoff is
# easier for a dispatcher to reason about than a retry-count promise.
CAPACITY_RETRY_INITIAL_DELAY_SEC = 5.0
CAPACITY_RETRY_MAX_DELAY_SEC = 60.0
CAPACITY_RETRY_BUDGET_SEC = 15 * 60.0
CAPACITY_RETRY_PROMPT = (
    "The previous turn ended because the selected model was at capacity. "
    "Resume the same approved task from the current repository state. "
    "Do not repeat work that is already complete."
)

# Mode contracts resolve relative to this file so any clone location works.
_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
MODE_SKILL_PATHS = {
    "mate": _SKILLS_ROOT / "meight-mate" / "SKILL.md",
    "worker": _SKILLS_ROOT / "meight-worker" / "SKILL.md",
}
COMMON_CONTRACT_PATH = _SKILLS_ROOT / "meight-common" / "CONTRACT.md"
PROTOCOL_EPOCH = "desktop1"
DAEMON_CAPABILITIES = [PROTOCOL_EPOCH]
TARGETS = {"mac", "desktop"}

# Every session runs in an explicit mode; the CLI requires it so the contract cannot be skipped.
# Legacy four-mode names map onto the two postures so old muscle memory and
# recorded status files keep working.
MODE_MAP = {
    "mate": "mate",
    "design": "mate",
    "collab": "mate",
    "collaborative": "mate",
    "review": "mate",
    "worker": "worker",
    "delegate": "worker",
    "delegated": "worker",
}

# Friendly names are a CLI contract, while the SDK requires ChatGPT-account model slugs.
# Keep matching exact so arbitrary full/custom model strings pass through unchanged.
MODEL_ALIASES = {
    "sol": "gpt-5.6-sol",
    "terra": "gpt-5.6-terra",
    "luna": "gpt-5.6-luna",
}

EFFORT_CHOICES = ["low", "medium", "high", "xhigh", "ultra", "max"]

# Start/dispatch defaults are deliberately code-only operator policy. Omitted
# flags select the mode row, then a known selected model reselects its effort
# and Fast defaults. Explicit overrides always win. Neither posture enforces a
# sandbox: read-only is brief-driven policy, not a harness gate.
MODE_START_DEFAULTS = {
    "mate": {
        "model": "sol", "effort": "medium", "fast": False,
        "sandbox": "full",
    },
    "worker": {
        "model": "sol", "effort": "medium", "fast": False,
        "sandbox": "full",
    },
}

MODEL_DEFAULT_EFFORTS = {
    "gpt-5.6-sol": "medium",
    "gpt-5.6-luna": "max",
}

MODEL_DEFAULT_FASTS = {
    "gpt-5.6-luna": True,
}

# start/dispatch must distinguish omission from explicit false-y values so
# --no-fast and every other explicit override retain provenance.
OMITTED_START_SETTING = object()

# follow/reply must distinguish an omitted option from an explicit false-y value
# such as --no-fast. argparse keeps this process-local sentinel out of the socket
# request; missing request keys are the daemon protocol's inheritance signal.
INHERIT_TURN_SETTING = object()


_sdk_effort_field_relaxed = False


def relax_sdk_effort_field() -> None:
    """Accept every effort string the app-server accepts.

    Codex app-server advertises ReasoningEffort as a non-empty string, but the
    pinned SDK still generates a closed enum ending at xhigh. The enum is a
    client-side artifact, so widen the local pydantic field once per process
    before Thread.turn constructs TurnStartParams. Widening by value (rather
    than for a known list like ultra/max) keeps future server-side tiers working
    without a code change here.
    """
    global _sdk_effort_field_relaxed
    if _sdk_effort_field_relaxed:
        return

    try:
        from openai_codex.generated.v2_all import TurnStartParams
    except ImportError:
        # Nothing to widen without the SDK. Let the turn itself report the
        # missing dependency instead of failing the whole follow here.
        return

    field = TurnStartParams.model_fields["effort"]
    if field.annotation != (str | None):
        field.annotation = str | None
        TurnStartParams.model_rebuild(force=True)
    _sdk_effort_field_relaxed = True


def relax_sdk_effort_echo() -> None:
    """Thread lifecycle responses echo the account-default reasoning effort
    (e.g. model_reasoning_effort = "ultra" in ~/.codex/config.toml), which the
    pinned SDK's closed ReasoningEffort enum rejects regardless of the effort
    requested for the turn. Relax those response fields to plain strings."""
    from openai_codex.generated import v2_all

    for cls_name in ("ThreadStartResponse", "ThreadForkResponse", "ThreadResumeResponse"):
        cls = getattr(v2_all, cls_name, None)
        if cls is None:
            continue
        field = cls.model_fields.get("reasoning_effort")
        if field is None or field.annotation == (str | None):
            continue
        field.annotation = str | None
        cls.model_rebuild(force=True)


def normalize_model(model: str | None) -> str | None:
    return MODEL_ALIASES.get(model, model)


def normalize_mode(mode: str | None) -> str | None:
    return MODE_MAP.get(mode or "")

# Single source of the teaching error shown wherever --mode is missing (validated before any side effect).
MODE_TEACHING_ERROR = """error: --mode is required. Pick one:
  --mode mate    thinking partner: design, diagnosis, independent review, direction
  --mode worker  team implementer: owns how, implementation, verification, self-review
(legacy aliases: design|collab|collaborative|review → mate; delegate|delegated → worker)"""

PROTOCOL_EPOCH_ERROR = (
    f"protocol epoch mismatch: expected {PROTOCOL_EPOCH}; "
    "restart or upgrade the CLI and daemon together"
)

# Initial turns receive runtime mode plus mode/common SSOT paths.
# All operating rules live in those files so the harness cannot drift into another contract.
_PREAMBLE_TEMPLATE = """Runtime contract: mode={mode}.
Follow the {skill_name} contract at `{skill_path}` and the shared meight contract at `{common_path}`.
"""


def build_preamble(mode: str) -> str:
    normalized_mode = normalize_mode(mode)
    if normalized_mode is None:
        raise ValueError(f"invalid mode: {mode!r}")
    skill_path = MODE_SKILL_PATHS[normalized_mode]
    return _PREAMBLE_TEMPLATE.format(
        mode=normalized_mode,
        skill_name=skill_path.parent.name,
        skill_path=skill_path,
        common_path=COMMON_CONTRACT_PATH,
    )


def build_follow_reminder(mode: str) -> str:
    """Follow/reply turns get a one-line reminder instead of re-injecting the full preamble."""
    normalized_mode = normalize_mode(mode)
    if normalized_mode is None:
        raise ValueError(f"invalid mode: {mode!r}")
    return (f"Continue with runtime contract mode={normalized_mode}. "
            f"Follow the mode skill at `{MODE_SKILL_PATHS[normalized_mode]}` and shared "
            f"contract at `{COMMON_CONTRACT_PATH}`.\n")


def install_computer_use_approval_bridge(codex, worker_name: str) -> None:
    """Approve only this worker's explicit Computer Use app-access requests.

    The pinned SDK exposes server-request handling only through its internal
    client. Keep that compatibility boundary here, and leave every other MCP
    elicitation with the SDK's existing handler.
    """
    client = getattr(codex, "_client", None)
    fallback = getattr(client, "_approval_handler", None)
    if not callable(fallback):
        raise RuntimeError("openai-codex SDK does not expose an approval handler")

    def approval_handler(method: str, params: dict | None) -> dict:
        if not isinstance(params, dict):
            return fallback(method, params)
        meta = params.get("_meta")
        if not isinstance(meta, dict) or meta.get("connector_id") != "computer-use":
            return fallback(method, params)
        tool_params = meta.get("tool_params")
        if method == "mcpServer/elicitation/request" and isinstance(tool_params, dict):
            app = tool_params.get("app") or "unknown"
            print(f"computer-use approval accepted worker={worker_name} app={app}", flush=True)
            return {"action": "accept", "_meta": {"persist": "session"}}
        return fallback(method, params)

    client._approval_handler = approval_handler


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


def parse_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def is_real_directory(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) and not stat.S_ISLNK(mode)


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


def validate_worker_name(name: object) -> str:
    """Return a filesystem-safe worker name or reject it at the trust boundary."""
    if not isinstance(name, str) or not WORKER_NAME_RE.fullmatch(name):
        raise ValueError(
            "invalid worker name: use 1-128 ASCII letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return name


def worker_name_arg(value: str) -> str:
    try:
        return validate_worker_name(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def ensure_private_dir(path: Path) -> Path:
    """Create/repair an owner-only directory without ever following its leaf as a symlink."""
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise RuntimeError(f"unsafe state directory (must be a real directory): {path}")
    os.chmod(path, 0o700)
    return path


def ensure_worker_state_dir(home: Path, repo_home: Path, name: str) -> Path:
    """Create the derived worker path, rejecting every mutable state leaf symlink."""
    name = validate_worker_name(name)
    home = ensure_private_dir(home)
    repos = ensure_private_dir(home / "repos")
    expected_parent = repos.resolve()
    if repo_home.parent.resolve() != expected_parent:
        raise ValueError("repo home escapes daemon repos directory")
    ensure_private_dir(repo_home)
    workers = ensure_private_dir(repo_home / "workers")
    return ensure_private_dir(workers / name)


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


def system_codex_bin() -> str:
    """Return the current system Codex CLI instead of the SDK's stale bundled runtime."""
    configured = os.environ.get("MEIGHT_CODEX_BIN")
    candidate = configured or shutil.which("codex")
    if not candidate:
        raise FileNotFoundError(
            "codex CLI not found; install it or set MEIGHT_CODEX_BIN to its executable path"
        )
    path = Path(candidate).expanduser()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"Codex executable is not runnable: {path}")
    return str(path)


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


def verified_repo_context(home: Path, req: dict) -> dict:
    """Derive repo state inside the daemon and reject forged client context fields."""
    raw_root = req.get("repo_root")
    raw_key = req.get("repo_key")
    raw_home = req.get("repo_home")
    if not all(isinstance(value, str) and value for value in (raw_root, raw_key, raw_home)):
        raise ValueError("missing repo context")
    derived = repo_context(home, raw_root)
    supplied_root = str(Path(raw_root).expanduser().resolve())
    supplied_home = str(Path(raw_home).expanduser().resolve())
    if supplied_root != derived["repo_root"]:
        raise ValueError("repo_root does not match daemon-derived repository root")
    if raw_key != derived["repo_key"]:
        raise ValueError("repo_key does not match daemon-derived repository key")
    if supplied_home != str(Path(derived["repo_home"]).resolve()):
        raise ValueError("repo_home does not match daemon-derived state path")
    return derived


def registry_key(repo_key: str, name: str) -> str:
    return f"{repo_key}\0{name}"


def atomic_write_json(path: Path, obj: dict) -> None:
    # Include pid+thread id in tmp names so concurrent writers cannot steal each other's tmp files.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_bounded_json(path: Path, limit: int = MAX_SOCKET_REQUEST_BYTES) -> object:
    """Read a small state record with a hard byte bound, including under reg_lock rechecks."""
    with open(path, "rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"JSON state exceeds {limit} byte limit")
    return json.loads(payload.decode("utf-8"))


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


def read_text_tail(path: Path, limit: int = RECOVERY_ARTIFACT_MAX_CHARS) -> str:
    """Read a bounded UTF-8 tail for legacy worker recovery."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit * 4))
            return f.read(limit * 4).decode("utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def dig(d: object, *keys: str, default=None):
    """Chained dict.get helper for missing SDK payload fields."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def failure_detail(payload: dict) -> dict:
    """Extract only user-relevant SDK error fields; never persist the full payload."""
    error = payload.get("error")
    if not isinstance(error, dict):
        error = {"message": error} if error else {}
    raw_message = error.get("message") or payload.get("message")
    provider = None
    if isinstance(raw_message, str):
        try:
            decoded = json.loads(raw_message)
            provider = decoded if isinstance(decoded, dict) else None
        except json.JSONDecodeError:
            pass
    provider_error = provider.get("error") if provider else None
    if not isinstance(provider_error, dict):
        provider_error = {}
    message = provider_error.get("message") or (
        provider.get("message") if provider else None
    ) or raw_message or "unknown error"
    status = next((value for value in (
        provider.get("status") if provider else None,
        error.get("status"), error.get("status_code"), error.get("http_status"),
        payload.get("status"), payload.get("status_code"),
    ) if value is not None), None)
    error_type = (
        provider_error.get("type") or provider_error.get("code")
        or error.get("type") or error.get("code") or payload.get("type")
    )
    return {
        "message": str(message),
        "status": status if isinstance(status, (int, str)) else None,
        "type": str(error_type) if error_type is not None else None,
    }


def format_failure_detail(detail: dict) -> str:
    labels = []
    status = detail.get("status")
    if status is not None:
        labels.append(f"HTTP {status}" if str(status).isdigit() else f"status={status}")
    if detail.get("type"):
        labels.append(str(detail["type"]))
    prefix = " ".join(labels)
    return f"{prefix}: {detail['message']}" if prefix else str(detail["message"])


def is_capacity_failure(detail: dict) -> bool:
    return "selected model is at capacity" in str(detail.get("message", "")).lower()


def capacity_retry_delay(retry_number: int) -> float:
    """Return the capped exponential delay before a 1-based retry."""
    delay = CAPACITY_RETRY_INITIAL_DELAY_SEC
    for _ in range(max(0, retry_number - 1)):
        if delay >= CAPACITY_RETRY_MAX_DELAY_SEC:
            break
        delay = min(CAPACITY_RETRY_MAX_DELAY_SEC, delay * 2)
    return delay


def capacity_retry_budget_for_timeout(timeout: float | None) -> float:
    """Keep a dispatch retry budget below its wait checkpoint when bounded."""
    if timeout is None:
        return CAPACITY_RETRY_BUDGET_SEC
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        return CAPACITY_RETRY_BUDGET_SEC
    if timeout <= 0:
        # Existing wait semantics use 0 as an unbounded checkpoint.
        return CAPACITY_RETRY_BUDGET_SEC
    return min(CAPACITY_RETRY_BUDGET_SEC, timeout)


def normalize_capacity_retry_budget(value: object) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return CAPACITY_RETRY_BUDGET_SEC


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
                 mode: str = "worker", capacity_retry_budget_sec: float | None = None,
                 target: str = "mac", runtime: str = "codex"):
        self.name = name
        self.repo_home = repo_home
        self.repo_root = repo_root
        self.repo_key = repo_key
        self.dir = repo_home / "workers" / name
        self.cwd = cwd
        self.sandbox = sandbox  # normalized key such as "workspace_write"
        self.model = model
        self.effort = effort
        self.service_tier = service_tier  # "priority" by default; --no-fast selects "default"
        self.thread_source = thread_source
        self.thread_ephemeral = thread_ephemeral
        # Canonical posture; follow/reply turns inherit it. Normalizing here keeps
        # sessions recorded under legacy four-mode names handoff-consistent.
        self.mode = normalize_mode(mode) or "worker"
        self.target = target if target in TARGETS else "mac"
        self.runtime = runtime
        self.capacity_retry_budget_sec = normalize_capacity_retry_budget(capacity_retry_budget_sec)
        self.thread = None       # openai_codex.Thread (live only while starting/running a turn)
        self.handle = None       # TurnHandle
        self.codex = None        # openai_codex.Codex runtime owned by this worker
        self.backend = None      # DesktopBackend for remote turns; local path remains unchanged
        self.consumer: threading.Thread | None = None
        self.interrupt_requested = False
        self.lock = threading.Lock()       # serialize status/event handling
        self.ctl_lock = threading.Lock()   # serialize control calls such as steer/interrupt
        self.generation = 0                # turn generation; ignores late events from old streams
        self.terminal_since: float | None = None
        self._last_status_write = 0.0
        self._agent_msg_buf = ""       # accumulated in-flight agentMessage deltas
        self._last_agent_msg = ""      # last finalized agentMessage
        self._result_written = False    # one result block per turn, including terminal SDK errors
        self._capacity_retry_pending = False
        self._capacity_retry_started_monotonic: float | None = None
        self._capacity_retry_deadline: float | None = None
        self._current_item_label: str | None = None
        self._current_item_since: float | None = None
        self._message_file = None      # messages.log handle, held for the live turn
        self._message_open = False     # a message block header has been written
        self._message_chars = 0        # characters of the current message already on disk
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
            "terminal_at": None,
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
            "target": self.target,
            "runtime": self.runtime,
            "host_id": None,
            "dispatch_id": None,
            "remote_state": None,
            "remote_event_seq": 0,
            "attempt_id": None,
            "lease_epoch": None,
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
            "error_detail": None,
            "capacity_retries": 0,
            "capacity_retry_budget_sec": self.capacity_retry_budget_sec,
            "capacity_retry": None,
            "capacity_retry_summary": None,
            "turns": turns,
        }
        self.write_status(force=True)

    def _refresh_capacity_retry_status_locked(self, now: float | None = None) -> None:
        info = self.status.get("capacity_retry")
        if not isinstance(info, dict) or info.get("state") != "waiting":
            return
        now = time.monotonic() if now is None else now
        started = self._capacity_retry_started_monotonic
        elapsed = max(0.0, now - started) if started is not None else 0.0
        remaining = max(0.0, self.capacity_retry_budget_sec - elapsed)
        next_in = (
            max(0.0, self._capacity_retry_deadline - now)
            if self._capacity_retry_deadline is not None else 0.0
        )
        info.update({
            "elapsed_sec": round(elapsed, 1),
            "remaining_sec": round(remaining, 1),
            "next_retry_in_sec": round(next_in, 1),
        })

    def write_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_status_write < STATUS_THROTTLE_SEC:
            return
        self._last_status_write = now
        timestamp = now_iso()
        self.status["updated_at"] = timestamp
        self._refresh_capacity_retry_status_locked(now)
        retry_info = self.status.get("capacity_retry")
        if isinstance(retry_info, dict) and retry_info.get("state") == "waiting":
            attempt = retry_info.get("attempt", self.status.get("capacity_retries", 0))
            next_in = int(max(0.0, float(retry_info.get("next_retry_in_sec", 0))))
            self.status["current_item"] = f"capacity retry #{attempt} in {next_in}s"
        elif self._current_item_label and self._current_item_since is not None:
            elapsed = int(time.monotonic() - self._current_item_since)
            self.status["current_item"] = f"{self._current_item_label} ({elapsed}s)"
        else:
            self.status["current_item"] = None
        state = self.status.get("state")
        if state in TERMINAL_STATES and not self.status.get("terminal_at"):
            self.status["terminal_at"] = timestamp
        dormant_question = (
            state == "needs_input"
            and self.status.get("needs_input_source") == "question"
        )
        if (state in TERMINAL_STATES or dormant_question) and self.terminal_since is None:
            self.terminal_since = time.monotonic()
        elif state not in TERMINAL_STATES and not dormant_question:
            self.terminal_since = None
        atomic_write_json(self.dir / "status.json", self.status)

    def log_event(self, method: str, summary: str) -> None:
        line = f"{now_iso()} [{method}] {truncate(summary, EVENT_LINE_MAX - 60)}"
        with open(self.dir / "events.log", "a", encoding="utf-8") as f:
            f.write(line[:EVENT_LINE_MAX] + "\n")

    # ── messages.log ──
    # The full text the worker speaks, streamed as it arrives. status.json keeps
    # a 500-character tail and events.log a 150-character summary; neither can
    # carry a message a human wants to read while it is still being written.

    def append_message_text(self, text: str) -> None:
        """Append agent message text immediately, opening the block on first write."""
        if not text:
            return
        try:
            if self._message_file is None:
                self._message_file = open(self.dir / MESSAGE_LOG_NAME, "a", encoding="utf-8")
            if not self._message_open:
                self._message_file.write(f"\n── {now_iso()} ──\n")
                self._message_open = True
            self._message_file.write(text)
            self._message_file.flush()  # a buffered live view is not a live view
            self._message_chars += len(text)
        except OSError:
            # The live view is an accessory; losing it must not stop the turn.
            self.close_message_log()

    def close_message_block(self, text: str = "") -> None:
        """End the current message, writing whatever the deltas did not carry."""
        self.append_message_text(text[self._message_chars:])
        if self._message_open and self._message_file is not None:
            try:
                self._message_file.write("\n")
                self._message_file.flush()
            except OSError:
                self.close_message_log()
        self._message_open = False
        self._message_chars = 0

    def close_message_log(self) -> None:
        if self._message_file is not None:
            try:
                self._message_file.close()
            except OSError:
                pass
            self._message_file = None

    def _clear_needs_input_locked(self) -> None:
        self.status["needs_input_detail"] = None
        self.status["needs_input_source"] = None
        self.status["needs_input_target"] = None
        self.status["needs_input_kind"] = None

    # ── Event Handling ──

    def consume_stream(self, daemon: "Daemon", gen: int, handle) -> None:
        try:
            current_handle = handle
            while True:
                for note in current_handle.stream():
                    try:
                        self.on_event(note, daemon, gen)
                    except Exception as e:  # one event handler failure must not kill the worker
                        daemon.log(f"worker={self.name} event handler error: {e!r}")
                with self.lock:
                    retry_pending = gen == self.generation and self._capacity_retry_pending
                if retry_pending:
                    next_handle = self._retry_capacity_turn(daemon, gen)
                    if next_handle is not None:
                        current_handle = next_handle
                        continue
                else:
                    self.on_stream_end(gen)
                break
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
            with self.lock:
                self.close_message_block()
                self.close_message_log()
            self.detach_runtime_refs_if_idle(daemon, gen, "stream ended")
            daemon.touch_activity()

    def consume_desktop(self, daemon: "Daemon", gen: int, backend, spec: dict) -> None:
        try:
            backend.monitor(spec)
        except Exception as e:
            reason = getattr(e, "reason", "remote_runtime_lost")
            with self.lock:
                if gen == self.generation and self.status.get("state") not in TERMINAL_STATES:
                    self.status["state"] = "failed"
                    self.status["remote_state"] = reason
                    self.status["runtime_lost_detail"] = f"{type(e).__name__}: {e}"
                    self.log_event("remote/error", self.status["runtime_lost_detail"])
                    self.write_status(force=True)
            daemon.log(f"worker={self.name} desktop monitor error: {e!r}")
        finally:
            with self.ctl_lock:
                if gen == self.generation:
                    self.backend = None
            daemon.touch_activity()

    def _retry_capacity_turn(self, daemon: "Daemon", gen: int):
        with self.lock:
            if gen != self.generation or not self._capacity_retry_pending:
                return None
            now = time.monotonic()
            if self._capacity_retry_started_monotonic is None:
                self._capacity_retry_started_monotonic = now
                self.status["capacity_retry_summary"] = None
            retry_count = int(self.status.get("capacity_retries", 0))
            retry_attempt = retry_count + 1
            elapsed = max(0.0, now - self._capacity_retry_started_monotonic)
            if elapsed >= self.capacity_retry_budget_sec:
                self._finish_capacity_retry_locked(elapsed)
                return None
            delay = min(
                capacity_retry_delay(retry_attempt),
                max(0.0, self.capacity_retry_budget_sec - elapsed),
            )
            self.status["capacity_retry"] = {
                "state": "waiting",
                "attempt": retry_attempt,
                "elapsed_sec": round(elapsed, 1),
                "remaining_sec": round(max(0.0, self.capacity_retry_budget_sec - elapsed), 1),
                "next_retry_in_sec": round(delay, 1),
                "budget_sec": self.capacity_retry_budget_sec,
            }
            self._capacity_retry_deadline = now + delay
            self.log_event(
                "capacity/retry",
                f"attempt={retry_attempt} delay={delay:g}s "
                f"elapsed={elapsed:.1f}s budget={self.capacity_retry_budget_sec:g}s",
            )
            self.write_status(force=True)

        deadline = self._capacity_retry_deadline
        while deadline is not None and time.monotonic() < deadline:
            if self.interrupt_requested or daemon.shutting_down.is_set():
                with self.lock:
                    self._capacity_retry_pending = False
                    self._capacity_retry_deadline = None
                    if isinstance(self.status.get("capacity_retry"), dict):
                        self.status["capacity_retry"]["state"] = "interrupted"
                    self.status["state"] = "interrupted"
                    self.write_result()
                    self.write_status(force=True)
                return None
            with self.lock:
                self.write_status()
            time.sleep(min(0.5, max(0.01, deadline - time.monotonic())))

        with self.ctl_lock:
            if self.interrupt_requested or daemon.shutting_down.is_set() or self.thread is None:
                with self.lock:
                    self._capacity_retry_pending = False
                    self._capacity_retry_deadline = None
                    if isinstance(self.status.get("capacity_retry"), dict):
                        self.status["capacity_retry"]["state"] = "interrupted"
                    self.status["state"] = "interrupted"
                    self.write_result()
                    self.write_status(force=True)
                return None
            with self.lock:
                started = self._capacity_retry_started_monotonic
                elapsed = max(
                    0.0,
                    time.monotonic() - started if started is not None else 0.0,
                )
                if elapsed >= self.capacity_retry_budget_sec:
                    self._finish_capacity_retry_locked(elapsed)
                    return None
                self._capacity_retry_pending = False
                self._capacity_retry_deadline = None
                self.status["capacity_retries"] = retry_attempt
                self._agent_msg_buf = ""
                self._last_agent_msg = ""
                self.status["turn_id"] = None
                self.status["state"] = "starting"
                self.status["terminal_at"] = None
                self.status["last_message_tail"] = ""
                self.status["error_detail"] = None
                if isinstance(self.status.get("capacity_retry"), dict):
                    self.status["capacity_retry"]["state"] = "resumed"
                    self.status["capacity_retry"]["next_retry_in_sec"] = None
                self.write_status(force=True)
            relax_sdk_effort_field()
            next_handle = self.thread.turn(
                CAPACITY_RETRY_PROMPT,
                model=self.model,
                effort=self.effort,
                service_tier=self.service_tier,
            )
            self.handle = next_handle
        daemon.log(
            f"capacity retry worker={self.name} repo={self.repo_key} "
            f"attempt={retry_attempt} budget={self.capacity_retry_budget_sec:g}s"
        )
        return next_handle

    def _finish_capacity_retry_locked(self, elapsed: float) -> None:
        retry_count = int(self.status.get("capacity_retries", 0))
        elapsed = max(0.0, elapsed)
        summary = (
            f"capacity retries stopped after {retry_count} retries over "
            f"{elapsed:.1f}s (budget {self.capacity_retry_budget_sec:g}s)"
        )
        self._capacity_retry_pending = False
        self._capacity_retry_deadline = None
        self.status["capacity_retry"] = {
            "state": "exhausted",
            "retries": retry_count,
            "elapsed_sec": round(elapsed, 1),
            "budget_sec": self.capacity_retry_budget_sec,
        }
        self.status["capacity_retry_summary"] = summary
        self.status["state"] = "failed"
        self.log_event("capacity/exhausted", summary)
        self.write_result()
        self.write_status(force=True)

    def on_event(self, note, daemon: "Daemon", gen: int) -> None:
        method = note.method
        payload = note.payload
        # mode="json": enum -> value strings, Path -> str (avoid exposing raw SDK enums)
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
            delta = p.get("delta") or ""
            self._agent_msg_buf += delta
            self.append_message_text(delta)  # unthrottled: this is the live view
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
            detail = failure_detail(p)
            msg = detail["message"]
            will_retry = bool(p.get("will_retry"))
            self.log_event(method, f"{msg} (will_retry={will_retry})")
            if not will_retry:
                self.status["error_detail"] = detail
                if is_capacity_failure(detail):
                    self._capacity_retry_pending = True
                else:
                    self.status["state"] = "failed"
                    self._clear_needs_input_locked()
                    self.write_result()
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
            self.close_message_block(text)
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
        if self._capacity_retry_pending:
            self.log_event(
                "turn/completed",
                f"turn status {turn_status!r} deferred for capacity retry",
            )
            self.write_status(force=True)
            return
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
            detail = failure_detail({"error": turn.get("error") or {}})
            self.status["error_detail"] = detail
            self.log_event("turn/completed", f"failed: {truncate(detail['message'], 200)}")
        else:
            # Mapping unknown/missing statuses to completed would violate the wait contract.
            self.status["state"] = "interrupted" if self.interrupt_requested else "failed"
            self.log_event("turn/completed",
                           f"unexpected turn status {turn_status!r} → {self.status['state']}")
        # Clear stale tool wait details for every non-question terminal state (failed/interrupted/completed).
        if self.status["state"] != "needs_input":
            self._clear_needs_input_locked()
        retry_info = self.status.get("capacity_retry")
        if isinstance(retry_info, dict) and retry_info.get("state") == "resumed":
            started = self._capacity_retry_started_monotonic
            elapsed = max(
                0.0,
                time.monotonic() - started if started is not None else 0.0,
            )
            retry_info.update({"state": "completed", "elapsed_sec": round(elapsed, 1)})
        self._current_item_label = None
        self._current_item_since = None
        self.close_message_block()  # an interrupted message still ends the block
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
        if self._result_written:
            return
        msg = self._last_agent_msg or self._agent_msg_buf
        detail = self.status.get("error_detail")
        if detail:
            error_text = format_failure_detail(detail)
            msg = f"{msg}\n\n## Error\n\n{error_text}" if msg else f"## Error\n\n{error_text}"
        elif not msg:
            msg = "(no agent message)"
        retry_summary = self.status.get("capacity_retry_summary")
        if retry_summary:
            msg = f"{msg}\n\n## Capacity retry\n\n{retry_summary}"
        header = ""
        if self.status.get("turns", 1) > 1:
            header = f"\n\n---\n## Turn {self.status['turns']} ({now_iso()})\n\n"
        with open(self.dir / "result.md", "a", encoding="utf-8") as f:
            f.write(header + msg + "\n")
        self._result_written = True

    # ── Reset For Follow ──

    def reset_for_follow(self, brief: str) -> None:
        with self.lock:
            self.generation += 1  # after this point, all old stream events are ignored
            self.interrupt_requested = False
            self._agent_msg_buf = ""
            self._last_agent_msg = ""
            self._result_written = False
            self._capacity_retry_pending = False
            self._capacity_retry_started_monotonic = None
            self._capacity_retry_deadline = None
            self._current_item_label = None
            self._current_item_since = None
            self.terminal_since = None
            self.close_message_log()
            self._message_open = False
            self._message_chars = 0
            turns = int(self.status.get("turns", 1)) + 1
            sep = f"\n\n---\n## Turn {turns} ({now_iso()})\n\n"
            with open(self.dir / "brief.md", "a", encoding="utf-8") as f:
                f.write(sep + brief + "\n")
            with open(self.dir / "events.log", "a", encoding="utf-8") as f:
                f.write(f"--- turn {turns} ({now_iso()}) ---\n")
            with open(self.dir / MESSAGE_LOG_NAME, "a", encoding="utf-8") as f:
                f.write(f"\n=== turn {turns} ({now_iso()}) ===\n")
            for fname in ("decision.json", "decision.md"):
                try:
                    (self.dir / fname).unlink()
                except FileNotFoundError:
                    pass
            self.status.update({
                "turn_id": None,
                "state": "starting",
                "started_at": now_iso(),
                "terminal_at": None,
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
                "error_detail": None,
                "capacity_retries": 0,
                "capacity_retry": None,
                "capacity_retry_summary": None,
                "turns": turns,
            })
            self.write_status(force=True)

    def handoff_context(self) -> str:
        """Build bounded continuity for a fresh ephemeral follow/reply thread."""
        prior_brief = read_text_tail(self.dir / "brief.md")
        prior_result = read_text_tail(self.dir / "result.md")
        prior_events = read_text_tail(self.dir / "events.log", 12_000)
        return (
            "Meight uses ephemeral Codex threads so worker sessions do not accumulate "
            "in the Codex app. Continue this worker from the durable handoff below. "
            "Treat the current repository state as authoritative and inspect it before "
            "making changes.\n\n"
            "## Prior brief\n\n"
            f"{prior_brief or '(unavailable)'}\n\n"
            "## Prior result\n\n"
            f"{prior_result or '(unavailable)'}\n\n"
            "## Recent events\n\n"
            f"{prior_events or '(unavailable)'}\n\n"
            "## New follow-up\n\n"
        )

    def record_turn_settings(self, model: str | None, effort: str,
                             service_tier: str | None) -> None:
        """Persist settings only after a follow turn has been created successfully."""
        with self.lock:
            self.model = model
            self.effort = effort
            self.service_tier = service_tier
            self.status.update({
                "model": model,
                "effort": effort,
                "service_tier": service_tier,
            })
            self.write_status(force=True)

    def current_state(self) -> str:
        with self.lock:
            return self.status.get("state", "unknown")

    def has_live_turn(self) -> bool:
        """True only while a Codex turn may still need a live TurnHandle."""
        with self.lock:
            state = self.status.get("state")
            source = self.status.get("needs_input_source")
        return state in ("target_preparing", "starting", "running") or (state == "needs_input" and source != "question")

    def is_dormant_question(self) -> bool:
        """True when durable status is waiting but no SDK runtime is required."""
        with self.lock:
            return (
                self.status.get("state") == "needs_input"
                and self.status.get("needs_input_source") == "question"
            )

    def detach_runtime_refs_if_idle(self, daemon: "Daemon", gen: int, reason: str) -> None:
        """Release the SDK runtime after every terminal or replyable-question turn."""
        codex_to_close = None
        with self.ctl_lock:
            with self.lock:
                state = self.status.get("state")
                source = self.status.get("needs_input_source")
                error_detail = self.status.get("error_detail")
                detachable = state in TERMINAL_STATES or (state == "needs_input" and source == "question")
                if gen != self.generation or not detachable:
                    return
                had_refs = self.handle is not None or self.thread is not None or self.codex is not None
                self.handle = None
                self.thread = None
                codex_to_close = self.codex
                self.codex = None
            if had_refs:
                outcome = f"state={state}"
                if state == "failed" and isinstance(error_detail, dict):
                    outcome += (
                        f" error={truncate(format_failure_detail(error_detail), 300)!r}"
                    )
                daemon.log(
                    f"detached runtime refs worker={self.name} "
                    f"repo={self.repo_key} {outcome} reason={reason}"
                )
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
        self.session_retention_sec = _env_float(
            "MEIGHT_SESSION_RETENTION_SEC", DEFAULT_SESSION_RETENTION_SEC
        )
        self.last_activity = time.monotonic()
        self.last_retention_cleanup = -RETENTION_CLEANUP_INTERVAL_SEC
        self.retention_lock = threading.Lock()
        self.retention_thread: threading.Thread | None = None
        self.socket_identity: tuple[int, int] | None = None

    def touch_activity(self) -> None:
        self.last_activity = time.monotonic()

    def _owns_socket_path(self) -> bool:
        """Confirm the published socket pathname still names this daemon's socket."""
        if self.socket_identity is None:
            return False
        try:
            current = os.lstat(self.sock_path)
        except OSError:
            return False
        return self.socket_identity == (current.st_dev, current.st_ino)

    def log(self, msg: str) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{now_iso()} {msg}\n")
        except OSError:
            pass

    # ── Startup/Cleanup ──

    def run(self) -> int:
        ensure_private_dir(self.home)
        ensure_private_dir(self.home / "repos")

        # Singleton guard 1: flock blocks concurrent startup regardless of pid file presence/reuse.
        self.lock_file = open(self.home / "daemon.lock", "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            self.lock_file = None
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

        # Ownership is now exclusive. Live turns from the previous daemon cannot
        # be recovered safely; dormant questions can continue via artifact handoff.
        self._reconcile_startup_orphans()

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.sock_path))
        os.chmod(self.sock_path, 0o600)
        sock_stat = os.lstat(self.sock_path)
        self.socket_identity = (sock_stat.st_dev, sock_stat.st_ino)
        self.server.listen(16)
        self.server.settimeout(1.0)
        self.pid_path.write_text(str(os.getpid()) + "\n")

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        self.log(
            f"daemon started pid={os.getpid()} home={self.home} "
            f"idle_timeout_sec={self.idle_timeout_sec:g} "
            f"session_retention_sec={self.session_retention_sec:g}"
        )
        print(f"claude-codex-meight daemon listening on {self.sock_path} (pid {os.getpid()})", flush=True)

        exit_code = 0
        self._schedule_retention_cleanup()
        try:
            while not self.shutting_down.is_set():
                if not self._owns_socket_path():
                    self.log("daemon socket pathname ownership lost")
                    exit_code = 1
                    break
                try:
                    conn, _ = self.server.accept()
                except socket.timeout:
                    self._maintenance()
                    continue
                except OSError as e:
                    if self.shutting_down.is_set():
                        break  # intentional close after shutdown acknowledgement
                    self.log(f"unexpected accept failure: {type(e).__name__}: {e}")
                    exit_code = 1
                    break
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
        finally:
            self._cleanup()
        return exit_code

    def _reconcile_startup_orphans(self) -> None:
        """Preserve prior evidence while making non-resumable active rows terminal."""
        repos_dir = self.home / "repos"
        if not is_real_directory(repos_dir):
            return
        for repo_dir in repos_dir.iterdir():
            workers_dir = repo_dir / "workers"
            if not is_real_directory(repo_dir) or not is_real_directory(workers_dir):
                continue
            for worker_dir in workers_dir.iterdir():
                status_path = worker_dir / "status.json"
                if (not is_real_directory(worker_dir) or status_path.is_symlink()
                        or not status_path.is_file()):
                    continue
                try:
                    status_obj = read_bounded_json(status_path)
                except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(status_obj, dict) or status_obj.get("state") not in ACTIVE_STATES:
                    continue
                if (
                    status_obj.get("target") == "desktop"
                    and isinstance(status_obj.get("dispatch_id"), str)
                    and status_obj.get("dispatch_id")
                ):
                    # Remote spool/job identity survives this Mac daemon. Reattach the
                    # monitor instead of marking a possibly-live attempt failed or
                    # spawning a duplicate.
                    try:
                        repo_root = str(status_obj.get("repo_root") or "")
                        repo_key = str(status_obj.get("repo_key") or repo_dir.name)
                        worker = self._restore_worker_from_status(
                            repo_dir, repo_root, repo_key, worker_dir.name, status_obj,
                        )
                        from meight_desktop_backend import DesktopBackend

                        worker.backend = DesktopBackend(worker)
                        spec = {
                            "dispatch_id": status_obj["dispatch_id"],
                            "generation": worker.generation,
                        }
                        worker.consumer = threading.Thread(
                            target=worker.consume_desktop,
                            args=(self, worker.generation, worker.backend, spec),
                            daemon=True,
                            name=f"worker-{worker.name}-desktop-reconcile",
                        )
                        self.workers[self._worker_key(repo_key, worker.name)] = worker
                        worker.consumer.start()
                        continue
                    except Exception as e:
                        self.log(f"remote reconcile attach failed path={worker_dir}: {e!r}")
                if (
                    status_obj.get("state") == "needs_input"
                    and status_obj.get("needs_input_source") == "question"
                    and isinstance(status_obj.get("thread_id"), str)
                    and status_obj["thread_id"]
                ):
                    # Final questions are durable dormant states. Their runtime was
                    # already closed and follow can continue via artifact handoff.
                    continue
                timestamp = now_iso()
                prior_state = status_obj.get("state")
                status_obj["state"] = "failed"
                status_obj["needs_input_detail"] = None
                status_obj["needs_input_source"] = None
                status_obj["needs_input_target"] = None
                status_obj["needs_input_kind"] = None
                status_obj["runtime_lost_detail"] = (
                    f"daemon restarted; orphaned {prior_state} runtime from daemon pid "
                    f"{status_obj.get('daemon_pid')} cannot be resumed"
                )
                status_obj["updated_at"] = timestamp
                if not status_obj.get("terminal_at"):
                    status_obj["terminal_at"] = timestamp
                try:
                    atomic_write_json(status_path, status_obj)
                    with open(worker_dir / "events.log", "a", encoding="utf-8") as event_file:
                        event_file.write(
                            f"{timestamp} [runtime/lost] {status_obj['runtime_lost_detail']}\n"
                        )
                except OSError as e:
                    self.log(f"orphan reconciliation failed path={worker_dir}: {e!r}")

    def _retention_timestamp(self, status_obj: dict) -> datetime | None:
        if "terminal_at" in status_obj:
            return parse_aware_timestamp(status_obj.get("terminal_at"))
        return parse_aware_timestamp(status_obj.get("updated_at"))

    def _expired_worker_status(self, worker_dir: Path, cutoff_now: datetime) -> bool:
        status_path = worker_dir / "status.json"
        if (not is_real_directory(worker_dir) or status_path.is_symlink()
                or not status_path.is_file()):
            return False
        try:
            status_obj = read_bounded_json(status_path)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(status_obj, dict) or status_obj.get("state") not in TERMINAL_STATES:
            return False
        terminal_at = self._retention_timestamp(status_obj)
        if terminal_at is None:
            return False
        return (cutoff_now - terminal_at).total_seconds() >= self.session_retention_sec

    def _prune_expired_sessions(self, cutoff_now: datetime | None = None) -> None:
        """Rename eligible state under reg_lock; perform recursive deletion after releasing it."""
        if self.session_retention_sec <= 0:
            return
        cutoff_now = cutoff_now or now_kst()
        repos_dir = self.home / "repos"
        if not is_real_directory(repos_dir):
            return
        tombstone_candidates: list[tuple[str, str, Path]] = []
        candidates: list[tuple[str, str, Path]] = []
        for repo_dir in repos_dir.iterdir():
            workers_dir = repo_dir / "workers"
            if not is_real_directory(repo_dir) or not is_real_directory(workers_dir):
                continue
            for entry in workers_dir.iterdir():
                if entry.name.startswith(PRUNE_TOMBSTONE_PREFIX):
                    if self._expired_worker_status(entry, cutoff_now):
                        tombstone_candidates.append((repo_dir.name, entry.name, entry))
                    continue
                try:
                    validate_worker_name(entry.name)
                except ValueError:
                    continue
                if self._expired_worker_status(entry, cutoff_now):
                    candidates.append((repo_dir.name, entry.name, entry))

        renamed: list[Path] = []
        recovered: list[Path] = []
        rename_errors: list[tuple[Path, OSError]] = []
        with self.reg_lock:
            # Prefix alone is not proof of an internal tombstone: older meight
            # versions allowed worker names beginning with it. Reapply the same
            # terminal/expiry/registry gates before recovering an interrupted delete.
            for repo_key, name, tombstone in tombstone_candidates:
                if self._worker_key(repo_key, name) in self.workers:
                    continue
                if self._expired_worker_status(tombstone, cutoff_now):
                    recovered.append(tombstone)
            for repo_key, name, worker_dir in candidates:
                if self._worker_key(repo_key, name) in self.workers:
                    continue
                if not self._expired_worker_status(worker_dir, cutoff_now):
                    continue
                tombstone = worker_dir.with_name(
                    f"{PRUNE_TOMBSTONE_PREFIX}{name}-{os.getpid()}-{time.time_ns()}"
                )
                try:
                    os.replace(worker_dir, tombstone)
                except OSError as e:
                    rename_errors.append((worker_dir, e))
                    continue
                renamed.append(tombstone)

        for worker_dir, error in rename_errors:
            self.log(f"retention rename skipped path={worker_dir}: {error!r}")
        for tombstone in recovered + renamed:
            if not is_real_directory(tombstone):
                continue
            try:
                shutil.rmtree(tombstone)
                self.log(f"retention pruned path={tombstone}")
            except OSError as e:
                self.log(f"retention delete deferred path={tombstone}: {e!r}")

    def _retention_cleanup_runner(self) -> None:
        try:
            self._prune_expired_sessions()
        except Exception as e:
            self.log(f"retention cleanup error: {type(e).__name__}: {e}")
        finally:
            with self.retention_lock:
                self.retention_thread = None

    def _schedule_retention_cleanup(self, now: float | None = None) -> bool:
        if self.session_retention_sec <= 0:
            return False
        now = time.monotonic() if now is None else now
        with self.retention_lock:
            if self.retention_thread is not None:
                return False
            if now - self.last_retention_cleanup < RETENTION_CLEANUP_INTERVAL_SEC:
                return False
            self.last_retention_cleanup = now
            self.retention_thread = threading.Thread(
                target=self._retention_cleanup_runner,
                daemon=True,
                name="meight-retention",
            )
            self.retention_thread.start()
        return True

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
                elif w.has_live_turn():
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
        return [w for w in self.workers.values() if w.has_live_turn()]

    def _maintenance(self) -> None:
        now = time.monotonic()
        with self.reg_lock:
            for key, w in list(self.workers.items()):
                if w.current_state() not in TERMINAL_STATES and not w.is_dormant_question():
                    continue
                consumer = w.consumer
                # Non-blocking liveness only: the accept loop runs maintenance, and a
                # consumer join here would stall every socket command (control plane
                # never waits on the data plane). A live consumer just defers GC.
                if consumer is not None and consumer.is_alive():
                    continue
                terminal_since = w.terminal_since or now
                if self.worker_gc_ttl_sec and now - terminal_since >= self.worker_gc_ttl_sec:
                    self.log(f"gc worker={w.name} repo={w.repo_key} state={w.current_state()}")
                    del self.workers[key]
            active = self._active_workers_locked()
        self._schedule_retention_cleanup(now)
        if active:
            return
        if self.idle_timeout_sec and now - self.last_activity >= self.idle_timeout_sec:
            self.log(f"idle timeout after {self.idle_timeout_sec:g}s → shutdown")
            threading.Thread(target=self._shutdown_now, daemon=True).start()

    def _cleanup(self) -> None:
        with self.reg_lock:
            workers = list(self.workers.values())
        for w in workers:
            w.detach_runtime_refs_if_idle(self, w.generation, "daemon cleanup")
        try:
            current = os.lstat(self.sock_path)
            if self.socket_identity == (current.st_dev, current.st_ino):
                self.sock_path.unlink()
        except FileNotFoundError:
            pass
        try:
            if int(self.pid_path.read_text().strip()) == os.getpid():
                self.pid_path.unlink()
        except (FileNotFoundError, OSError, ValueError):
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
                if len(buf) > MAX_SOCKET_REQUEST_BYTES:
                    raise ValueError(f"request exceeds {MAX_SOCKET_REQUEST_BYTES} byte limit")
            request_line = buf.split(b"\n", 1)[0]
            if len(request_line) > MAX_SOCKET_REQUEST_BYTES:
                raise ValueError(f"request exceeds {MAX_SOCKET_REQUEST_BYTES} byte limit")
            req = json.loads(request_line.decode("utf-8"))
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
            resp = self._dispatch(req)
            shutdown = resp.pop("_shutdown", False)
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            if shutdown:
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
        # The epoch gate is the first command-specific operation for start/follow.
        # It must reject stale clients before imports, path resolution or creation,
        # registry reservation, SDK startup, or turn start.
        if cmd in {"start", "follow"} and req.get("protocol_epoch") != PROTOCOL_EPOCH:
            return {"ok": False, "error": PROTOCOL_EPOCH_ERROR}
        try:
            if cmd == "ping":
                return {
                    "ok": True,
                    "pid": os.getpid(),
                    "idle_timeout_sec": self.idle_timeout_sec,
                    "session_retention_sec": self.session_retention_sec,
                    "capabilities": DAEMON_CAPABILITIES,
                }
            if cmd == "start":
                return self.cmd_start(req)
            if cmd == "follow":
                validate_worker_name(req.get("name"))
                return self.cmd_follow(req)
            if cmd == "steer":
                validate_worker_name(req.get("name"))
                return self.cmd_steer(req)
            if cmd == "interrupt":
                validate_worker_name(req.get("name"))
                return self.cmd_interrupt(req)
            if cmd == "shutdown":
                return self.cmd_shutdown(req)
            if cmd == "runtime_status":
                validate_worker_name(req.get("name"))
                return self.cmd_runtime_status(req)
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        except Exception as e:
            self.log(f"cmd={cmd} error: {traceback.format_exc(limit=5)}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ── Command Implementations ──

    def _repo_from_req(self, req: dict) -> tuple[str, str, Path]:
        context = verified_repo_context(self.home, req)
        return context["repo_key"], context["repo_root"], Path(context["repo_home"])

    def _worker_key(self, repo_key: str, name: str) -> str:
        return registry_key(repo_key, name)

    def _load_worker_status(self, repo_home: Path, name: str) -> dict | None:
        sj = repo_home / "workers" / name / "status.json"
        if sj.is_symlink() or not sj.is_file():
            return None
        try:
            value = read_bounded_json(sj)
            return value if isinstance(value, dict) else None
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None

    def _restore_worker_from_status(
        self,
        repo_home: Path,
        repo_root: str,
        repo_key: str,
        name: str,
        status: dict,
    ) -> Worker:
        """Reattach durable worker metadata for an ephemeral follow handoff."""
        sandbox = str(status.get("sandbox") or "full-access").replace("-", "_")
        if sandbox not in set(SANDBOX_MAP.values()):
            raise ValueError(f"worker '{name}' has invalid recorded sandbox: {sandbox!r}")
        ensure_worker_state_dir(self.home, repo_home, name)
        worker = Worker(
            name,
            repo_home,
            repo_root,
            repo_key,
            str(status.get("cwd") or repo_root),
            sandbox,
            status.get("model"),
            str(status.get("effort") or "medium"),
            status.get("service_tier"),
            str(status.get("thread_source") or "subagent"),
            bool(status.get("thread_ephemeral", True)),
            mode=str(status.get("mode") or "worker"),
            capacity_retry_budget_sec=status.get("capacity_retry_budget_sec"),
            target=str(status.get("target") or "mac"),
            runtime=str(status.get("runtime") or "codex"),
        )
        worker.status = dict(status)
        # Drop fields from pre-text-only sessions so status/result stay on the
        # current plain-text contract after a daemon restart or follow.
        worker.status.pop("report", None)
        worker.status.pop("output_schema", None)
        worker.generation = max(0, int(status.get("turns") or 0))
        if worker.current_state() in TERMINAL_STATES or worker.is_dormant_question():
            worker.terminal_since = time.monotonic()
        return worker

    def cmd_runtime_status(self, req: dict) -> dict:
        name = req["name"]
        repo_key, _, _ = self._repo_from_req(req)
        with self.reg_lock:
            w = self.workers.get(self._worker_key(repo_key, name))
        if w is None:
            return {
                "ok": True,
                "known": False,
                "pid": os.getpid(),
                "capabilities": DAEMON_CAPABILITIES,
            }
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
            "capabilities": DAEMON_CAPABILITIES,
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
        raw_mode = req.get("mode")
        mode = normalize_mode(raw_mode)
        if mode is None:
            # Keep this before imports, path creation, registry reservation, or SDK
            # startup. Direct socket clients receive the same teaching contract as the
            # CLI and can never silently fall back to a default contract.
            return {"ok": False, "error": MODE_TEACHING_ERROR.removeprefix("error: ")}

        name = validate_worker_name(req["name"])
        repo_key, repo_root, repo_home = self._repo_from_req(req)
        wid = self._worker_key(repo_key, name)
        brief = req["brief"]
        use_preamble = not req.get("no_preamble")
        preamble = build_preamble(mode)
        turn_input = f"{preamble}\n{brief}" if use_preamble else brief
        file_brief = f"{preamble}\n---\n\n{brief}" if use_preamble else brief
        cwd = req.get("cwd") or os.getcwd()
        sandbox_key = SANDBOX_MAP.get(req.get("sandbox") or "full")
        if sandbox_key is None:
            return {"ok": False, "error": f"invalid sandbox: {req.get('sandbox')}"}
        # Daemon-authoritative normalization covers stale CLIs and direct socket clients.
        model = normalize_model(req.get("model"))
        effort = req.get("effort") or "medium"
        service_tier = req.get("service_tier")
        capacity_retry_budget_sec = normalize_capacity_retry_budget(
            req.get("capacity_retry_budget_sec")
        )
        target = req.get("target") or "mac"
        runtime = req.get("runtime") or "codex"
        if target not in TARGETS:
            return {"ok": False, "error": f"invalid target: {target!r}"}
        if runtime != "codex":
            return {"ok": False, "error": f"unsupported runtime: {runtime!r}"}
        if target == "desktop":
            try:
                from meight_desktop_backend import git_repo_spec

                git_repo_spec(cwd, repo_root)
            except Exception as e:
                reason = getattr(e, "reason", "remote_spawn_failed")
                return {"ok": False, "error": f"{reason}: {e}"}
        # ThreadSource is analytics metadata, not a UI-hiding mechanism. Ephemeral
        # threads are not materialized in Codex's stored thread listings. Legacy
        # clients may still send main_thread, but it is intentionally ignored.
        thread_source_label = "subagent"
        thread_ephemeral = True
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
                mode=mode,
                capacity_retry_budget_sec=capacity_retry_budget_sec,
                target=target,
                runtime=runtime,
            )
            ensure_worker_state_dir(self.home, repo_home, name)
            # Restarting the same name creates a new worker, so reset prior outputs.
            for fname in ("events.log", MESSAGE_LOG_NAME, "result.md", "debug-events.log",
                          "decision.json", "decision.md"):
                try:
                    (w.dir / fname).unlink()
                except FileNotFoundError:
                    pass
            (w.dir / "brief.md").write_text(file_brief + "\n", encoding="utf-8")

            w.init_status(thread_id=None)  # in-memory state "starting" makes the reservation below effective
            # Register the placeholder BEFORE the SDK phase: a concurrent same-name start
            # must fail the active check above instead of racing the slow thread_start.
            self.workers[wid] = w

        # Data-plane phase — deliberately OUTSIDE reg_lock. thread_start spawns a codex
        # app-server (seconds of subprocess+RPC); holding reg_lock across it starves the
        # accept loop via _maintenance and made concurrent waits misread the daemon as
        # dead (false exit 4). Control plane never waits on the data plane.
        try:
            if target == "desktop":
                from meight_desktop_backend import DesktopBackend

                w.generation = 1
                w.backend = DesktopBackend(w)
                spec = w.backend.prepare_and_start(turn_input)
                thread = None
            else:
                from openai_codex import Codex, CodexConfig, Sandbox
                from openai_codex.types import ThreadSource

                w.codex = Codex(config=CodexConfig(codex_bin=system_codex_bin()))
                install_computer_use_approval_bridge(w.codex, w.name)
                relax_sdk_effort_echo()
                thread = w.codex.thread_start(
                    cwd=cwd,
                    ephemeral=thread_ephemeral,
                    sandbox=getattr(Sandbox, sandbox_key),
                    thread_source=ThreadSource.subagent,
                )
                w.thread = thread
                with w.lock:
                    w.status["thread_id"] = thread.id
                relax_sdk_effort_field()
                w.handle = thread.turn(
                    turn_input,
                    model=model, effort=effort, service_tier=service_tier,
                )
        except Exception as e:
            # The failed placeholder stays registered so status/wait see a terminal state
            # instead of a zombie that blocks its name forever.
            w.mark_failed(f"start failed: {type(e).__name__}: {e}")
            w.detach_runtime_refs_if_idle(self, w.generation, "start failed")
            self.log(f"start worker={name} repo={repo_key} failed: {e!r}")
            return {"ok": False, "error": f"start failed: {type(e).__name__}: {e}"}

        # Post-SDK commit is atomic under ctl_lock: _shutdown_now and cmd_interrupt also
        # take ctl_lock per worker, so either they run first (flag set → we abort) or the
        # commit runs first (their snapshot sees the live consumer/handle and covers it).
        # This closes the TOCTOU between the guard check and consumer.start().
        aborted = False
        with w.ctl_lock:
            if self.shutting_down.is_set() or w.interrupt_requested:
                aborted = True
                try:
                    if w.backend is not None:
                        w.backend.send_control("interrupt")
                    elif w.handle is not None:
                        w.handle.interrupt()
                except Exception:
                    pass
            else:
                w.generation = 1
                if target == "desktop":
                    w.consumer = threading.Thread(
                        target=w.consume_desktop, args=(self, w.generation, w.backend, spec), daemon=True,
                        name=f"worker-{name}-desktop",
                    )
                else:
                    w.consumer = threading.Thread(
                        target=w.consume_stream, args=(self, w.generation, w.handle), daemon=True,
                        name=f"worker-{name}",
                    )
                w.consumer.start()
        if aborted:
            w.mark_interrupted("start aborted: daemon shutting down or interrupted")
            w.detach_runtime_refs_if_idle(self, w.generation, "start aborted")
            return {"ok": False, "error": "start aborted: daemon shutting down or interrupted"}

        self.touch_activity()
        self.log(
            f"start worker={name} repo={repo_key} thread={getattr(thread, 'id', None)} "
            f"cwd={cwd} sandbox={sandbox_key} thread_source={thread_source_label} "
            f"ephemeral={thread_ephemeral} mode={mode} target={target} runtime={runtime}"
        )
        return {
            "ok": True,
            "thread_id": getattr(thread, "id", None),
            "mode": mode,
            "target": target,
            "runtime": runtime,
            "protocol_epoch": PROTOCOL_EPOCH,
        }

    def cmd_follow(self, req: dict) -> dict:
        name = req["name"]
        raw_model = req.get("model", INHERIT_TURN_SETTING)
        raw_effort = req.get("effort", INHERIT_TURN_SETTING)
        raw_service_tier = req.get("service_tier", INHERIT_TURN_SETTING)
        if raw_model is not INHERIT_TURN_SETTING and (
                not isinstance(raw_model, str) or not raw_model.strip()):
            return {"ok": False, "error": "model override must be a non-empty string"}
        if raw_effort is not INHERIT_TURN_SETTING and raw_effort not in EFFORT_CHOICES:
            return {"ok": False, "error": f"invalid effort override: {raw_effort!r}"}
        if (raw_service_tier is not INHERIT_TURN_SETTING
                and raw_service_tier not in ("default", "priority")):
            return {"ok": False,
                    "error": f"invalid service_tier override: {raw_service_tier!r}"}

        repo_key, repo_root, repo_home = self._repo_from_req(req)
        wid = self._worker_key(repo_key, name)
        brief = req["brief"]
        use_preamble = not req.get("no_preamble")
        with self.reg_lock:
            w = self.workers.get(wid)
            if w is None:
                st = self._load_worker_status(repo_home, name)
                if st is None:
                    return {"ok": False, "error": f"unknown worker: {name}"}
                try:
                    w = self._restore_worker_from_status(
                        repo_home, repo_root, repo_key, name, st
                    )
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                self.workers[wid] = w
            prev_state = w.current_state()
            # needs_input (waiting on QUESTION) can also follow; send the answer as a new turn on the same thread.
            if prev_state not in TERMINAL_STATES and prev_state != "needs_input":
                return {"ok": False, "error":
                        f"worker '{name}' is not in a terminal state ({prev_state})"}
            # Reject follow until the old consumer fully exits (first guard against late-event contamination).
            if not w.consumer_finished():
                return {"ok": False,
                        "error": f"worker '{name}' previous stream is still finishing — retry shortly"}

            model = (w.model if raw_model is INHERIT_TURN_SETTING
                     else normalize_model(raw_model))
            effort = w.effort if raw_effort is INHERIT_TURN_SETTING else raw_effort
            service_tier = (w.service_tier if raw_service_tier is INHERIT_TURN_SETTING
                            else raw_service_tier)
            previous_thread_id = w.status.get("thread_id")
            reuse_ephemeral_thread = w.thread is not None and w.thread_ephemeral
            recovery_context = "" if reuse_ephemeral_thread else w.handoff_context()

            reminder = build_follow_reminder(w.mode)
            turn_input = f"{reminder}{brief}" if use_preamble else brief
            file_brief = f"{reminder}---\n\n{brief}" if use_preamble else brief
            # reset_for_follow flips the worker back to "starting", which reserves it:
            # concurrent follow/start on the same name is rejected while we run the SDK
            # phase below without holding reg_lock.
            w.reset_for_follow(file_brief)  # generation+1; also ignores any leftover old events (second guard)

        # Data-plane phase — outside reg_lock for the same reason as cmd_start.
        try:
            if w.target == "desktop":
                from meight_desktop_backend import DesktopBackend

                w.backend = DesktopBackend(w)
                spec = w.backend.prepare_and_start(f"{recovery_context}{turn_input}")
                thread_id = None
            elif not reuse_ephemeral_thread:
                from openai_codex import Codex, CodexConfig, Sandbox
                from openai_codex.types import ThreadSource

                w.codex = Codex(config=CodexConfig(codex_bin=system_codex_bin()))
                install_computer_use_approval_bridge(w.codex, w.name)
                relax_sdk_effort_echo()
                w.thread = w.codex.thread_start(
                    cwd=w.cwd,
                    ephemeral=True,
                    sandbox=getattr(Sandbox, w.sandbox),
                    service_tier=service_tier,
                    thread_source=ThreadSource.subagent,
                )
                thread_id = w.thread.id
                turn_input = f"{recovery_context}{turn_input}"
                with w.lock:
                    w.thread_ephemeral = True
                    w.thread_source = "subagent"
                    w.status["thread_id"] = thread_id
                    w.status["thread_ephemeral"] = True
                    w.status["thread_source"] = "subagent"
                    w.status["continued_from_thread_id"] = previous_thread_id
                    w.write_status(force=True)
                w.log_event(
                    "thread/handoff",
                    f"ephemeral handoff {previous_thread_id or '(none)'} -> {thread_id}",
                )
            else:
                thread_id = previous_thread_id
            if w.target == "mac":
                relax_sdk_effort_field()
                w.handle = w.thread.turn(
                    turn_input,
                    model=model, effort=effort, service_tier=service_tier,
                )
        except Exception as e:
            w.mark_failed(f"follow turn failed (was {prev_state}): {type(e).__name__}: {e}")
            w.detach_runtime_refs_if_idle(self, w.generation, "follow failed")
            self.log(f"follow worker={name} failed: {e!r}")
            return {"ok": False, "error": f"follow failed: {type(e).__name__}: {e}"}

        # Same atomic post-SDK commit as cmd_start (see the TOCTOU note there).
        aborted = False
        with w.ctl_lock:
            if self.shutting_down.is_set() or w.interrupt_requested:
                aborted = True
                try:
                    if w.backend is not None:
                        w.backend.send_control("interrupt")
                    elif w.handle is not None:
                        w.handle.interrupt()
                except Exception:
                    pass
            else:
                w.record_turn_settings(model, effort, service_tier)
                with w.lock:
                    gen = w.generation
                    turns = w.status["turns"]
                    thread_id = w.status["thread_id"]
                if w.target == "desktop":
                    w.consumer = threading.Thread(
                        target=w.consume_desktop, args=(self, gen, w.backend, spec), daemon=True,
                        name=f"worker-{name}-desktop-t{turns}",
                    )
                else:
                    w.consumer = threading.Thread(
                        target=w.consume_stream, args=(self, gen, w.handle), daemon=True,
                        name=f"worker-{name}-t{turns}",
                    )
                w.consumer.start()
        if aborted:
            w.mark_interrupted("follow aborted: daemon shutting down or interrupted")
            w.detach_runtime_refs_if_idle(self, w.generation, "follow aborted")
            return {"ok": False, "error": "follow aborted: daemon shutting down or interrupted"}

        self.touch_activity()
        self.log(f"follow worker={name} repo={repo_key} thread={thread_id} turn#{turns}")
        return {
            "ok": True,
            "thread_id": thread_id,
            "turns": turns,
            "mode": w.mode,
            "target": w.target,
            "runtime": w.runtime,
            "protocol_epoch": PROTOCOL_EPOCH,
        }

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
            if w.target == "desktop" and w.backend is not None:
                w.backend.send_control("steer", text=req["text"])
            elif w.handle is None:
                return {"ok": False, "error": f"worker '{name}' has no live turn handle"}
            else:
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
            if w.target == "desktop" and w.backend is not None:
                w.interrupt_requested = True
                w.backend.send_control("interrupt")
                w.log_event("interrupt", "remote graceful interrupt requested by client")
            elif w.handle is None:
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
                # ACTIVE with no live handle = the SDK phase of start/follow (or a tool
                # wait without a handle). Record the interrupt instead of dropping it;
                # the atomic post-SDK commit honors the flag and aborts the turn.
                w.interrupt_requested = True
                w.log_event("interrupt", "recorded during SDK phase — starting turn will be aborted")
                self.touch_activity()
                return {"ok": True, "note": "interrupt recorded — starting turn will be aborted"}
            else:
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
                      if w.has_live_turn()]
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
    timestamp = now_iso()
    lost["updated_at"] = timestamp
    if not lost.get("terminal_at"):
        lost["terminal_at"] = timestamp
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


def repo_home_for_cli(home: Path, cwd: str | Path | None = None) -> Path:
    return Path(repo_context(home, cwd)["repo_home"])


def request_repo_context(home: Path, cwd: str | Path | None = None) -> dict:
    return repo_context(home, cwd)


def load_statuses(repo_home: Path) -> list[dict]:
    out = []
    workers_dir = repo_home / "workers"
    if not workers_dir.is_dir():
        return out
    for d in sorted(workers_dir.iterdir()):
        sj = d / "status.json"
        if sj.is_file():
            try:
                status = json.loads(sj.read_text(encoding="utf-8"))
                if isinstance(status, dict):
                    status.pop("report", None)
                    status.pop("output_schema", None)
                    out.append(status)
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


def filter_statuses(statuses: list[dict], view: str,
                    cutoff_now: datetime | None = None) -> list[dict]:
    """Split terminal disk rows into recent and archived status views."""
    if view == "all":
        return statuses
    cutoff_now = cutoff_now or now_kst()
    selected: list[dict] = []
    for status in statuses:
        archived = False
        if status.get("state") in TERMINAL_STATES:
            timestamp_value = (
                status.get("terminal_at")
                if "terminal_at" in status
                else status.get("updated_at")
            )
            terminal_at = parse_aware_timestamp(timestamp_value)
            if terminal_at is not None:
                archived = (
                    cutoff_now - terminal_at
                ).total_seconds() >= STATUS_ARCHIVE_AFTER_SEC
        if (view == "archived") == archived:
            selected.append(status)
    return selected


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
    mode = normalize_mode(str(mode_full)) or str(mode_full)
    return (f"{repo}{st.get('name', '?'):<14} {st.get('state', '?'):<12} {mode[:8]:<9} "
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
    if normalize_mode(getattr(args, "mode", None)) is None:
        print(MODE_TEACHING_ERROR, file=sys.stderr)
        raise SystemExit(2)


def require_protocol_capability(home: Path) -> dict:
    """Fail closed when the live daemon predates the current protocol epoch."""
    resp = send_request(home, {"cmd": "ping"}, timeout=10)
    if not resp.get("ok"):
        return resp
    capabilities = resp.get("capabilities")
    if not isinstance(capabilities, list) or PROTOCOL_EPOCH not in capabilities:
        return {"ok": False, "error": f"daemon predates protocol {PROTOCOL_EPOCH}; restart required"}
    return {"ok": True}


def protocol_echo_matches(resp: dict, expected_mode: str | None,
                          expected_target: str = "mac", expected_runtime: str = "codex") -> bool:
    """Validate the atomic mode, target, runtime, and epoch success response."""
    return (
        expected_mode is not None
        and resp.get("mode") == expected_mode
        and (resp.get("target") or "mac") == expected_target
        and (resp.get("runtime") or "codex") == expected_runtime
        and resp.get("protocol_epoch") == PROTOCOL_EPOCH
    )


def best_effort_interrupt(home: Path, req: dict, name: str) -> None:
    cleanup = {"cmd": "interrupt", "name": name}
    cleanup.update({key: req[key] for key in ("repo_root", "repo_key", "repo_home")})
    try:
        send_request(home, cleanup)
    except (Exception, SystemExit):
        pass


def resolve_start_options(args) -> tuple[dict, dict]:
    """Resolve mode-derived start settings and retain their CLI provenance."""
    mode = normalize_mode(getattr(args, "mode", None))
    if mode is None:
        raise ValueError("start options require a valid mode")
    defaults = MODE_START_DEFAULTS[mode]
    values = {}
    provenance = {}
    for key, default in defaults.items():
        raw = getattr(args, key, OMITTED_START_SETTING)
        if raw is OMITTED_START_SETTING:
            values[key] = default
            provenance[key] = "default"
        else:
            values[key] = raw
            provenance[key] = "set"
    if provenance["effort"] == "default":
        values["effort"] = MODEL_DEFAULT_EFFORTS.get(
            normalize_model(values["model"]), values["effort"],
        )
    if provenance["fast"] == "default":
        values["fast"] = MODEL_DEFAULT_FASTS.get(
            normalize_model(values["model"]), values["fast"],
        )
    return values, provenance


def start_resolution_echo(args, mode: str | None = None) -> str:
    values, provenance = resolve_start_options(args)
    canonical_mode = normalize_mode(mode) or normalize_mode(args.mode)
    fast = "on" if values["fast"] else "off"
    return (
        f"mode={canonical_mode} "
        f"model={values['model']}({provenance['model']}) "
        f"effort={values['effort']}({provenance['effort']}) "
        f"fast={fast}({provenance['fast']}) "
        f"sandbox={values['sandbox']}({provenance['sandbox']})"
    )


def start_request(args, home: Path) -> dict:
    require_mode(args)
    validate_worker_name(args.name)
    capability = require_protocol_capability(home)
    if not capability.get("ok"):
        return capability
    resolved, _provenance = resolve_start_options(args)
    # --fast/--no-fast is the user-facing knob; map it to a codex service tier.
    # priority = Fast; default = a non-priority tier.
    fast = resolved["fast"]
    service_tier = "priority" if fast else "default"
    req = {
        "cmd": "start", "name": args.name, "brief": read_brief(args),
        "cwd": str(Path(args.cwd).resolve()) if args.cwd else os.getcwd(),
        "sandbox": resolved["sandbox"], "model": normalize_model(resolved["model"]),
        "effort": resolved["effort"],
        "service_tier": service_tier,
        "capacity_retry_budget_sec": capacity_retry_budget_for_timeout(
            getattr(args, "timeout", None)
        ),
        "no_preamble": args.no_preamble,
        "mode": normalize_mode(args.mode),
        "target": getattr(args, "target", "mac"),
        "runtime": "codex",
        "protocol_epoch": PROTOCOL_EPOCH,
    }
    req.update(request_repo_context(home, args.cwd))
    resp = send_request(home, req)
    expected_mode = normalize_mode(args.mode)
    if resp.get("ok") and not protocol_echo_matches(
        resp, expected_mode, req["target"], req["runtime"],
    ):
        best_effort_interrupt(home, req, args.name)
        return {"ok": False, "error": (
            f"start protocol mismatch: expected mode={expected_mode} "
            f"target={req['target']} runtime={req['runtime']} epoch={PROTOCOL_EPOCH}"
        )}
    return resp


def follow_request(args, home: Path) -> dict:
    """Send follow and fail closed if the daemon does not echo inherited mode."""
    validate_worker_name(args.name)
    repo_home = repo_home_for_cli(home)
    status_path = repo_home / "workers" / args.name / "status.json"
    expected_mode = None
    if status_path.is_file():
        try:
            expected_mode = normalize_mode(json.loads(status_path.read_text(encoding="utf-8")).get("mode"))
        except (OSError, json.JSONDecodeError):
            pass
    req = {
        "cmd": "follow", "name": args.name, "brief": read_brief(args),
        "no_preamble": args.no_preamble,
        "protocol_epoch": PROTOCOL_EPOCH,
    }
    model = getattr(args, "model", INHERIT_TURN_SETTING)
    effort = getattr(args, "effort", INHERIT_TURN_SETTING)
    fast = getattr(args, "fast", INHERIT_TURN_SETTING)
    if model is not INHERIT_TURN_SETTING:
        req["model"] = normalize_model(model)
    if effort is not INHERIT_TURN_SETTING:
        req["effort"] = effort
    if fast is not INHERIT_TURN_SETTING:
        req["service_tier"] = "priority" if fast else "default"
    req.update(request_repo_context(home))
    resp = send_request(home, req)
    expected_target = "mac"
    expected_runtime = "codex"
    if status_path.is_file():
        try:
            recorded = json.loads(status_path.read_text(encoding="utf-8"))
            expected_target = recorded.get("target") or "mac"
            expected_runtime = recorded.get("runtime") or "codex"
        except (OSError, json.JSONDecodeError):
            pass
    if resp.get("ok") and not protocol_echo_matches(
        resp, expected_mode, expected_target, expected_runtime,
    ):
        best_effort_interrupt(home, req, args.name)
        return {"ok": False, "error": (
            f"follow protocol mismatch: expected mode={expected_mode} target={expected_target} "
            f"runtime={expected_runtime} epoch={PROTOCOL_EPOCH}"
        )}
    return resp


def cmd_follow(args, home: Path) -> int:
    resp = expect_ok(follow_request(args, home))
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
    resp = expect_ok(send_request(home, req))
    note = resp.get("note")
    print(f"interrupt requested for '{args.name}'" + (f" — {note}" if note else ""))
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
        if isinstance(st, dict):
            st.pop("report", None)
            st.pop("output_schema", None)
        if getattr(args, "json", False):
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            print(summary_line(st))
            for key in ("thread_id", "turn_id", "repo_root", "repo_key", "cwd",
                        "sandbox", "model", "effort", "service_tier", "thread_source",
                        "thread_ephemeral", "daemon_pid", "started_at", "updated_at",
                        "terminal_at", "turns", "mode", "needs_input_source",
                        "needs_input_target", "needs_input_kind", "needs_input_detail",
                        "runtime_lost_detail", "error_detail", "capacity_retries",
                        "capacity_retry_budget_sec", "capacity_retry", "capacity_retry_summary",
                        "target", "runtime", "host_id", "dispatch_id", "remote_state",
                        "remote_event_seq", "attempt_id", "lease_epoch", "source_revision"):
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
    view = (
        "all" if getattr(args, "show_all", False)
        else "archived" if getattr(args, "archived", False)
        else "recent"
    )
    statuses = filter_statuses(statuses, view)
    if getattr(args, "json", False):
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
    else:
        print_status_table(statuses, show_repo=all_repos)
    return 0


def cmd_result(args, home: Path) -> int:
    worker_dir = repo_home_for_cli(home) / "workers" / args.name
    result = worker_dir / "result.md"
    if not result.is_file():
        print(f"no result for worker '{args.name}'", file=sys.stderr)
        return 1
    print(result.read_text(encoding="utf-8"), end="")
    return 0


def read_status_file(worker_dir: Path) -> dict | None:
    """Read one worker's status digest, tolerating an absent or half-written file."""
    try:
        status = json.loads((worker_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return status if isinstance(status, dict) else None


def watch_stop_state(st: dict) -> str | None:
    """Return the state that ends a watch session: terminal, or a dormant question."""
    state = st.get("state")
    if state in TERMINAL_STATES:
        return state
    if state == "needs_input" and st.get("needs_input_source") == "question":
        return state
    return None


def watchable_statuses(repo_home: Path) -> list[dict]:
    """Worker rows a watch session would keep streaming."""
    return [st for st in load_statuses(repo_home)
            if st.get("name") and watch_stop_state(st) is None]


def watch_candidates(repo_home: Path, include_archived: bool = False) -> list[tuple[str, dict]]:
    """Group selectable workers, reusing the `status` recent/archived split.

    Live work comes first because that is what a watcher is usually looking
    for; finished workers stay selectable since their messages remain on disk."""
    named = [st for st in load_statuses(repo_home) if st.get("name")]
    recent = filter_statuses(named, "recent")
    rows = [("active", st) for st in recent if watch_stop_state(st) is None]
    idle = [st for st in recent if watch_stop_state(st) is not None]
    # A question is blocked on the reader; a finished worker asks for nothing.
    idle.sort(key=lambda st: watch_stop_state(st) != "needs_input")
    rows += [("idle", st) for st in idle]
    if include_archived:
        rows += [("archived", st) for st in filter_statuses(named, "archived")]
    return rows


WATCH_GROUP_TITLES = {
    "active": "active",
    "idle": "idle — finished, or waiting on you",
    "archived": "archived — terminal for over 6 hours",
}


def print_watch_menu(rows: list[tuple[str, dict]], stream=None) -> None:
    """Number the candidates so a reader can pick without knowing any name."""
    out = stream or sys.stdout
    print(f"  {'#':>2}  {'NAME':<14} {'STATE':<12} {'MODE':<9} {'ELAPSED':>8} "
          f"{'FILES':<9} {'TOKENS':<22} CURRENT", file=out)
    shown = None
    for number, (group, st) in enumerate(rows, 1):
        if group != shown:
            print(f"  ── {WATCH_GROUP_TITLES[group]} ──", file=out)
            shown = group
        print(f"  {number:>2}  {summary_line(st)}", file=out)


def watch_can_prompt() -> bool:
    """A menu needs a readable stdin and a visible stdout; a pipe has neither."""
    return bool(getattr(sys.stdin, "isatty", lambda: False)()
                and getattr(sys.stdout, "isatty", lambda: False)())


def prompt_watch_choice(rows: list[tuple[str, dict]], stream=None) -> str | None:
    """Return the chosen worker name, or None when the reader leaves."""
    out = stream or sys.stdout
    print_watch_menu(rows, out)
    while True:
        print(f"select 1-{len(rows)} (enter to quit): ", end="", file=out)
        out.flush()
        try:
            raw = sys.stdin.readline()
        except KeyboardInterrupt:
            print(file=out)
            return None
        if not raw:  # EOF
            print(file=out)
            return None
        raw = raw.strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(rows):
            return rows[int(raw) - 1][1]["name"]
        print(f"  '{truncate(raw, 40)}' is not a number between 1 and {len(rows)}", file=out)


class MessageLogFollower:
    """Tail one worker's messages.log as text, across creation and replacement."""

    def __init__(self, path: Path, from_start: bool = False,
                 tail_chars: int = WATCH_TAIL_CHARS):
        self.path = path
        self.from_start = from_start
        self.tail_chars = tail_chars
        self.identity: tuple[int, int] | None = None
        self.offset = 0
        # A delta boundary can split a multi-byte character, so decoding is
        # incremental instead of per-chunk.
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def poll(self) -> str:
        """Return the text appended since the previous poll."""
        try:
            info = os.stat(self.path)
        except OSError:
            return ""  # not created yet, or pruned mid-watch
        identity = (info.st_dev, info.st_ino)
        attached = identity == self.identity and info.st_size >= self.offset
        if not attached:
            self.identity = identity
            self.offset = 0
            self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        if info.st_size <= self.offset:
            return ""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
                self.offset = f.tell()
        except OSError:
            return ""
        text = self.decoder.decode(chunk)
        if attached or self.from_start:
            return text
        if self.tail_chars <= 0:
            return ""
        if len(text) > self.tail_chars:
            # Resume at a line boundary rather than mid-sentence.
            text = text[-self.tail_chars:].split("\n", 1)[-1]
        return text


class WatchSession:
    """Live view state for one worker: its message stream plus its status."""

    def __init__(self, name: str, worker_dir: Path, from_start: bool = False,
                 tail_chars: int = WATCH_TAIL_CHARS):
        self.name = name
        self.dir = worker_dir
        self.follower = MessageLogFollower(worker_dir / MESSAGE_LOG_NAME, from_start, tail_chars)
        self.status: dict = {}
        self.pending = ""  # text after the last newline, for the prefixed view
        self._item_label: str | None = None
        self._item_base = 0
        self._item_seen = 0.0

    def poll_text(self) -> str:
        return self.follower.poll()

    def poll_lines(self) -> list[str]:
        """Complete lines only: an interleaved view needs a name on every line.

        Blank separator lines are dropped here; prefixed, they would be noise."""
        self.pending += self.follower.poll()
        *lines, self.pending = self.pending.split("\n")
        return [line for line in lines if line.strip()]

    def poll_status(self) -> dict:
        status = read_status_file(self.dir)
        if status is not None:
            self.status = status
        return self.status

    def footer(self) -> str:
        """Keep the elapsed seconds moving on the viewer's own clock.

        status.json is throttled, and a command that prints nothing stops
        refreshing it entirely — exactly the silence this footer exists for."""
        current = self.status.get("current_item")
        if not current:
            self._item_label = None
            return self.status.get("state") or "waiting"
        m = WATCH_ELAPSED_RE.match(current)
        if not m:
            return current
        label, seconds = m.group("label"), int(m.group("seconds"))
        if label != self._item_label or seconds < self._item_base:
            self._item_label, self._item_base = label, seconds
            self._item_seen = time.monotonic()
        return f"{label} ({self._item_base + int(time.monotonic() - self._item_seen)}s)"


class WatchRenderer:
    """A raw text stream with an in-place footer on a TTY, plain text elsewhere."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.live = bool(getattr(self.stream, "isatty", lambda: False)())
        self.footer = ""
        self.at_line_start = True

    def write(self, text: str) -> None:
        """Write worker text exactly as it was spoken."""
        if not text:
            return
        self._erase()
        self.stream.write(text)
        self.stream.flush()
        self.at_line_start = text.endswith("\n")

    def line(self, text: str) -> None:
        if not self.at_line_start:
            self.write("\n")
        self.write(text + "\n")

    def set_footer(self, text: str) -> None:
        # Only on a line boundary: mid-line the worker's own text is already
        # moving, and a footer would land inside its sentence.
        if not self.live or not self.at_line_start or text == self.footer:
            return
        width = max(20, shutil.get_terminal_size((80, 24)).columns - 1)
        self.stream.write("\r\x1b[2K" + truncate(text, width))
        self.stream.flush()
        self.footer = text

    def close(self) -> None:
        self._erase()

    def _erase(self) -> None:
        if self.live and self.footer:
            self.stream.write("\r\x1b[2K")
            self.footer = ""
        self.stream.flush()


def watch_footer_text(sessions: list[WatchSession], show_names: bool) -> str:
    if not show_names:
        return f"▸ {sessions[0].footer()}"
    return "▸ " + "  |  ".join(f"{s.name}: {truncate(s.footer(), 40)}" for s in sessions)


def run_watch(repo_home: Path, names: list[str], from_start: bool = False,
              tail_chars: int = WATCH_TAIL_CHARS, poll_sec: float = WATCH_POLL_SEC,
              stream=None) -> int:
    """Stream what workers say, from disk, until every watched worker stops.

    Read-only by construction: no daemon RPC, no writes to worker state."""
    renderer = WatchRenderer(stream)
    show_names = len(names) > 1
    prefixes = {name: (f"{truncate(name, 14):<14} " if show_names else "") for name in names}
    pending = [WatchSession(name, repo_home / "workers" / name, from_start, tail_chars)
               for name in names]
    for session in pending:
        if not (session.dir / MESSAGE_LOG_NAME).is_file():
            renderer.line(f"(waiting for '{session.name}' to speak)")

    def drain(session: WatchSession) -> None:
        prefix = prefixes[session.name]
        if show_names:
            for line in session.poll_lines():
                renderer.line(f"{prefix}{line}")
        else:
            renderer.write(session.poll_text())

    try:
        while pending:
            for session in list(pending):
                drain(session)
                stop = watch_stop_state(session.poll_status())
                if stop is None:
                    continue
                # The worker's closing message reaches disk before its terminal
                # status, so one more read cannot cut the last sentence off.
                drain(session)
                if session.pending:
                    renderer.line(f"{prefixes[session.name]}{session.pending}")
                    session.pending = ""
                renderer.line(summary_line(session.status))
                if session.status.get("error_detail"):
                    renderer.line(f"  error: {format_failure_detail(session.status['error_detail'])}")
                if stop == "needs_input":
                    renderer.line(f"  question: {truncate(session.status.get('needs_input_detail') or '', 200)}")
                pending.remove(session)
            if pending:
                renderer.set_footer(watch_footer_text(pending, show_names))
                time.sleep(poll_sec)
    except KeyboardInterrupt:
        renderer.line("watch stopped; the worker keeps running")
        return 130
    renderer.close()
    return 0


def cmd_watch(args, home: Path) -> int:
    repo_home = repo_home_for_cli(home)
    name = getattr(args, "name", None)
    if getattr(args, "all_workers", False):
        if name:
            print("watch --all takes no worker name", file=sys.stderr)
            return 1
        names = [st["name"] for st in watchable_statuses(repo_home)]
        if not names:
            print("no active workers in this repo", file=sys.stderr)
            return 1
    elif name:
        names = [name]
    else:
        include_archived = getattr(args, "include_archived", False)
        rows = watch_candidates(repo_home, include_archived)
        if not rows:
            hint = "" if include_archived else " (add --include-archived for older ones)"
            print(f"no workers in this repo{hint}", file=sys.stderr)
            return 1
        active = [st for group, st in rows if group == "active"]
        if len(active) == 1:
            names = [active[0]["name"]]
            print(f"watching '{names[0]}' — the only active worker")
        elif not watch_can_prompt():
            print("pick a worker by name, or use --all", file=sys.stderr)
            print_watch_menu(rows)
            return 1
        else:
            chosen = prompt_watch_choice(rows)
            if chosen is None:
                return 0
            names = [chosen]
    return run_watch(repo_home, names,
                     from_start=getattr(args, "from_start", False),
                     tail_chars=getattr(args, "tail", WATCH_TAIL_CHARS))


def classify_wait_state(st: dict) -> int | None:
    """Map a status dict to a wait exit code. None means keep polling.
    needs_input exits 3 when source=="question" (a durable dormant state), and
    when a tool/approval wait persists past the grace window — those used to be
    invisible to the dispatcher until timeout even though nobody would ever
    answer them. A short grace period absorbs waits the SDK resolves itself."""
    state = st.get("state")
    if state in TERMINAL_STATES:
        return 0 if state == "completed" else 2
    if state == "needs_input":
        source = st.get("needs_input_source")
        if source == "question":
            return 3
        if source == "tool":
            updated = parse_aware_timestamp(st.get("updated_at"))
            if updated is None or (now_kst() - updated).total_seconds() >= TOOL_WAIT_GRACE_SEC:
                return 3
    return None


def wait_for_worker(home: Path, repo_home: Path, name: str, timeout: float | None,
                    progress: float = 300.0, narrate: bool = False) -> int:
    sj = repo_home / "workers" / name / "status.json"
    now = time.monotonic()
    deadline = now + timeout if timeout else None
    next_progress = now + progress if progress and progress > 0 else None
    dead_strikes = 0  # avoid false positives from transient ping failures while the daemon is busy
    last_plan_note = None  # --narrate: surface each newly active worker plan step once
    while True:
        st = None
        if sj.is_file():
            try:
                st = json.loads(sj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                st = None
        if st is not None:
            # The worker's own plan steps are the only mid-turn text it authors.
            # Printing each transition is for a human watching a terminal; a
            # backgrounded dispatcher reads the result on wake-up instead, so
            # narration is opt-in to keep task output files quiet.
            if narrate:
                active_step = next(
                    (s for s in (st.get("plan") or []) if s.startswith("[active]")), None)
                if active_step and active_step != last_plan_note:
                    print(f"  [{time.strftime('%H:%M:%S')}] {name} ▶ {active_step[len('[active] '):]}",
                          flush=True)
                    last_plan_note = active_step
            code = classify_wait_state(st)
            if code is not None:
                print(summary_line(st))
                return code
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


def ensure_daemon(home: Path) -> bool:
    """Auto-start through launchd when loaded; detach only with no installed job."""
    if probe_daemon_socket(home / "meight.sock"):
        return True
    ensure_private_dir(home)
    ensure_private_dir(home / "repos")
    launchd_loaded = launchd_service_loaded()
    if launchd_loaded is None:
        return False
    if launchd_loaded:
        proc = subprocess.run(
            ["launchctl", "kickstart", f"{launchctl_domain()}/{LAUNCHD_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=LAUNCHD_TRANSFER_TIMEOUT_SEC,
        )
        if proc.returncode != 0:
            return False
    else:
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


def dispatch_active_status(home: Path, repo_home: Path, name: str) -> dict | None:
    """Return an existing live dispatch target without treating terminal rows as live."""
    status_path = repo_home / "workers" / name / "status.json"
    if status_path.is_symlink() or not status_path.is_file():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(status, dict) or status.get("state") not in ACTIVE_STATES:
        return None
    # Keep the same disk-plus-daemon ownership check as wait_for_worker. If the
    # daemon no longer knows this row, still attach and let the normal wait path
    # mark runtime loss; starting over here would overwrite the evidence. A
    # dormant QUESTION is also attached so dispatch never overwrites it; wait
    # returns 3 and the dispatcher can use reply/follow.
    query_runtime_status(home, repo_home, name, status)
    if status.get("state") == "needs_input" and classify_wait_state(status) == 3:
        return status
    return status


def cmd_dispatch(args, home: Path) -> int:
    """One-shot: auto-start/reattach -> wait -> print full result.md."""
    require_mode(args)  # before ensure_daemon: a rejected call must not auto-start a daemon
    if not ensure_daemon(home):
        print("error: daemon auto-start failed — check daemon.log", file=sys.stderr)
        return 4
    repo_home = repo_home_for_cli(home, args.cwd)
    existing = dispatch_active_status(home, repo_home, args.name)
    if existing is not None:
        print(
            f"reattached to worker '{args.name}' (state={existing.get('state')})",
            flush=True,
        )
    else:
        resp = start_request(args, home)
        if not resp.get("ok"):
            print(f"error: {resp.get('error', 'unknown')}", file=sys.stderr)
            return 1
        print(
            f"started worker '{args.name}' thread={resp.get('thread_id')} "
            f"{start_resolution_echo(args, resp.get('mode'))}",
            flush=True,
        )
    code = wait_for_worker(home, repo_home, args.name, args.timeout, args.progress,
                           narrate=getattr(args, "narrate", False))
    worker_dir = repo_home / "workers" / args.name
    rp = worker_dir / "result.md"
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
    resp = expect_ok(follow_request(args, home))
    print(f"reply turn #{resp.get('turns')} on worker '{args.name}'", flush=True)
    repo_home = repo_home_for_cli(home)
    code = wait_for_worker(home, repo_home, args.name, args.timeout, args.progress,
                           narrate=getattr(args, "narrate", False))
    worker_dir = repo_home / "workers" / args.name
    rp = worker_dir / "result.md"
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
    capabilities = ",".join(resp.get("capabilities") or []) or "none"
    print(f"pong (daemon pid {resp.get('pid')}, idle_timeout_sec={resp.get('idle_timeout_sec')}, "
          f"session_retention_sec={resp.get('session_retention_sec')}, capabilities={capabilities})")
    return 0


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_payload(home: Path) -> dict:
    ensure_private_dir(home)
    ensure_private_dir(home / "repos")
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
        # Restart only after an abnormal exit. Intentional shutdown exits zero and
        # remains stopped until the next explicit kickstart/ownership transfer.
        "KeepAlive": {"SuccessfulExit": False},
        "EnvironmentVariables": {
            **({"PATH": os.environ["PATH"]} if os.environ.get("PATH") else {}),
            **({"MEIGHT_CODEX_BIN": os.environ["MEIGHT_CODEX_BIN"]}
               if os.environ.get("MEIGHT_CODEX_BIN") else {}),
            "MEIGHT_HOME": str(home),
            "MEIGHT_IDLE_TIMEOUT_SEC": MANAGED_DAEMON_IDLE_TIMEOUT_SEC,
        },
        "StandardOutPath": str(home / "launchd.out.log"),
        "StandardErrorPath": str(home / "launchd.err.log"),
    }


def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def launchd_service_loaded() -> bool | None:
    """Return loaded state, or None when launchctl cannot establish ownership safely."""
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"{launchctl_domain()}/{LAUNCHD_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return True
    # macOS launchctl uses EX_NOTFOUND (113) plus this diagnostic when the
    # service is definitively absent. Every other failure is ambiguous and must
    # not authorize an unmanaged fallback daemon or ownership transfer.
    if proc.returncode == 113 and "Could not find service" in (proc.stderr or ""):
        return False
    return None


def daemon_ping(home: Path, timeout: float = 3.0) -> dict | None:
    try:
        response = send_request(home, {"cmd": "ping"}, timeout=timeout)
    except SystemExit:
        return None
    return response if response.get("ok") else None


def wait_for_daemon_departure(home: Path, old_pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        socket_gone = not (home / "meight.sock").exists()
        if socket_gone and not pid_alive(old_pid):
            return True
        time.sleep(0.05)
    return False


def socket_path_identity(path: Path) -> tuple[int, int] | None:
    try:
        current = os.lstat(path)
    except OSError:
        return None
    return current.st_dev, current.st_ino


def daemon_singleton_lock_available(home: Path) -> bool | None:
    """Probe singleton ownership without trusting a missing or corrupt pid file."""
    try:
        lock_file = open(home / "daemon.lock", "a+")
    except OSError:
        return None
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        except OSError:
            return None
        return True
    finally:
        lock_file.close()


def launchd_running_pid(timeout: float = 5.0) -> int | None:
    """Return the PID launchd currently attributes to the managed job."""
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"{launchctl_domain()}/{LAUNCHD_LABEL}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"^\s*pid = ([0-9]+)\s*$", proc.stdout or "", re.MULTILINE)
    return int(match.group(1)) if match else None


def wait_for_fresh_daemon(home: Path, old_pid: int | None,
                          old_socket_identity: tuple[int, int] | None,
                          timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = daemon_ping(home, timeout=min(1.0, max(0.1, deadline - time.monotonic())))
        pid = response.get("pid") if response else None
        current_socket_identity = socket_path_identity(home / "meight.sock")
        pid_is_fresh = old_pid is None or pid != old_pid
        socket_is_fresh = (
            current_socket_identity is not None
            and (old_socket_identity is None or current_socket_identity != old_socket_identity)
        )
        if isinstance(pid, int) and pid_is_fresh and socket_is_fresh:
            remaining = max(0.1, deadline - time.monotonic())
            if launchd_running_pid(timeout=min(1.0, remaining)) == pid:
                return response
        time.sleep(0.05)
    return None


def drain_existing_daemon(home: Path, timeout: float) -> tuple[int | None, str | None]:
    """Acknowledge non-force shutdown, then wait for both old PID and socket ownership to end."""
    response = daemon_ping(home)
    if response is None:
        stale_pid = read_daemon_pid(home)
        if stale_pid is not None and pid_alive(stale_pid):
            return stale_pid, "daemon ownership is present but not healthy enough to drain safely"
        lock_available = daemon_singleton_lock_available(home)
        if lock_available is False:
            return stale_pid, "daemon singleton lock is held but its socket is not healthy enough to drain safely"
        if lock_available is None:
            return stale_pid, "could not establish daemon singleton ownership safely"
        return stale_pid, None
    old_pid = response.get("pid")
    if not isinstance(old_pid, int):
        return None, "live daemon ping did not return a valid pid"
    shutdown = send_request(home, {"cmd": "shutdown", "force": False}, timeout=timeout)
    if not shutdown.get("ok"):
        return old_pid, shutdown.get("error") or "daemon refused non-force shutdown"
    if not wait_for_daemon_departure(home, old_pid, timeout):
        return old_pid, f"timed out waiting for acknowledged daemon pid {old_pid} and socket to disappear"
    return old_pid, None


def load_launchagent_with_ownership_transfer(home: Path, path: Path, payload: dict,
                                             timeout: float = LAUNCHD_TRANSFER_TIMEOUT_SEC) -> int:
    loaded = launchd_service_loaded()
    if loaded is None:
        print("error: could not determine LaunchAgent ownership", file=sys.stderr)
        return 1
    old_socket_identity = socket_path_identity(home / "meight.sock")
    old_pid, error = drain_existing_daemon(home, timeout)
    if error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    if loaded:
        try:
            bootout = subprocess.run(
                ["launchctl", "bootout", "--wait", f"{launchctl_domain()}/{LAUNCHD_LABEL}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            print("error: launchctl bootout timed out", file=sys.stderr)
            return 1
        if bootout.returncode != 0:
            print(f"error: launchctl bootout failed ({bootout.returncode})", file=sys.stderr)
            return 1
    path.write_bytes(plistlib.dumps(payload, sort_keys=False))
    try:
        subprocess.run(
            ["launchctl", "bootstrap", launchctl_domain(), str(path)],
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print("error: launchctl bootstrap timed out", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: launchctl bootstrap failed ({e.returncode})", file=sys.stderr)
        return 1
    fresh = wait_for_fresh_daemon(home, old_pid, old_socket_identity, timeout)
    if fresh is None:
        print("error: LaunchAgent loaded but no fresh daemon pid became ready", file=sys.stderr)
        return 1
    print(f"loaded {LAUNCHD_LABEL} (daemon pid {fresh['pid']})")
    return 0


def cmd_launchd_install(args, home: Path) -> int:
    path = launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = launchd_payload(home)
    if not args.load:
        path.write_bytes(plistlib.dumps(payload, sort_keys=False))
        print(f"wrote {path}")
        return 0
    result = load_launchagent_with_ownership_transfer(home, path, payload)
    if result == 0:
        print(f"wrote {path}")
    return result


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
        sp.add_argument("--target", choices=sorted(TARGETS), default="mac",
                        help="execution target; default mac preserves local behavior")
        # No argparse `choices`: require_mode() is the single CLI validation source for
        # missing AND invalid values, so both cases print the same teaching error.
        sp.add_argument(
            "--mode",
            help=("required: mate|worker (legacy aliases: "
                  "design|collab|collaborative|review → mate; delegate|delegated → worker)"),
        )
        sp.add_argument("--sandbox", choices=sorted(SANDBOX_MAP.keys()),
                        default=OMITTED_START_SETTING,
                        help="sandbox posture; omitted uses the mode default")
        sp.add_argument("--model", default=OMITTED_START_SETTING,
                        help="model or alias; omitted uses the mode default")
        sp.add_argument("--effort", choices=EFFORT_CHOICES,
                        default=OMITTED_START_SETTING,
                        help="reasoning effort; omitted uses the selected model default")
        sp.add_argument("--fast", action=argparse.BooleanOptionalAction,
                        default=OMITTED_START_SETTING,
                        help="select or disable Fast; omitted uses the mode default")
        sp.add_argument("--no-preamble", action="store_true", help="disable injecting runtime contract context")

    sp = sub.add_parser("dispatch", help="one-shot: auto-launch or reattach + poll + print result")
    sp.add_argument("name", type=worker_name_arg)
    add_start_options(sp)
    sp.add_argument("--timeout", type=float, default=1800)
    sp.add_argument("--progress", type=float, default=300.0,
                    help="seconds between status heartbeats while waiting; 0=off")
    sp.add_argument("--narrate", action="store_true",
                    help="print worker plan-step transitions live (for a human watching a terminal)")
    sp.add_argument("--shutdown-when-idle", action="store_true",
                    help="after a terminal result, ask the global daemon to stop if no workers are active")
    sp.set_defaults(fn=cmd_dispatch)

    sp = sub.add_parser("follow", help="new turn on the same thread for a terminal/QUESTION worker")
    sp.add_argument("name", type=worker_name_arg)
    sp.add_argument("--brief-file", help="read from stdin when '-'")
    sp.add_argument("--brief")
    sp.add_argument("--model", default=INHERIT_TURN_SETTING,
                    help="override the model for this and later turns; omitted inherits")
    sp.add_argument("--effort", choices=EFFORT_CHOICES, default=INHERIT_TURN_SETTING,
                    help="override reasoning effort for this and later turns; omitted inherits")
    sp.add_argument("--fast", action=argparse.BooleanOptionalAction,
                    default=INHERIT_TURN_SETTING,
                    help="override Fast tier for this and later turns; omitted inherits")
    sp.add_argument("--no-preamble", action="store_true")
    sp.set_defaults(fn=cmd_follow)

    sp = sub.add_parser("reply", help="one-shot reply: follow + poll + print latest turn result (for QUESTION)")
    sp.add_argument("name", type=worker_name_arg)
    sp.add_argument("--brief-file", help="read from stdin when '-'")
    sp.add_argument("--brief")
    sp.add_argument("--model", default=INHERIT_TURN_SETTING,
                    help="override the model for this and later turns; omitted inherits")
    sp.add_argument("--effort", choices=EFFORT_CHOICES, default=INHERIT_TURN_SETTING,
                    help="override reasoning effort for this and later turns; omitted inherits")
    sp.add_argument("--fast", action=argparse.BooleanOptionalAction,
                    default=INHERIT_TURN_SETTING,
                    help="override Fast tier for this and later turns; omitted inherits")
    sp.add_argument("--no-preamble", action="store_true")
    sp.add_argument("--timeout", type=float, default=1800)
    sp.add_argument("--progress", type=float, default=300.0,
                    help="seconds between status heartbeats while waiting; 0=off")
    sp.add_argument("--narrate", action="store_true",
                    help="print worker plan-step transitions live (for a human watching a terminal)")
    sp.add_argument("--shutdown-when-idle", action="store_true",
                    help="after a terminal result, ask the global daemon to stop if no workers are active")
    sp.set_defaults(fn=cmd_reply)

    sp = sub.add_parser("steer", help="inject mid-turn text into a running turn")
    sp.add_argument("name", type=worker_name_arg)
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_steer)

    sp = sub.add_parser("interrupt", help="interrupt a turn")
    sp.add_argument("name", type=worker_name_arg)
    sp.set_defaults(fn=cmd_interrupt)

    sp = sub.add_parser("status", help="worker status (daemon not required)")
    sp.add_argument("name", nargs="?", type=worker_name_arg)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--all-repos", action="store_true", help="show workers from every repo namespace")
    status_view = sp.add_mutually_exclusive_group()
    status_view.add_argument("--archived", action="store_true",
                             help="show terminal workers older than 6 hours")
    status_view.add_argument("--all", dest="show_all", action="store_true",
                             help="show recent and archived workers")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("list", help="status alias")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--all-repos", action="store_true", help="show workers from every repo namespace")
    list_view = sp.add_mutually_exclusive_group()
    list_view.add_argument("--archived", action="store_true",
                           help="show terminal workers older than 6 hours")
    list_view.add_argument("--all", dest="show_all", action="store_true",
                           help="show recent and archived workers")
    sp.set_defaults(fn=cmd_status, name=None)

    sp = sub.add_parser("result", help="print result.md")
    sp.add_argument("name", type=worker_name_arg)
    sp.set_defaults(fn=cmd_result)

    sp = sub.add_parser("watch", help="stream what a worker says, live (daemon not required)")
    sp.add_argument("name", nargs="?", type=worker_name_arg,
                    help="omitted selects the only active worker in this repo")
    sp.add_argument("--all", dest="all_workers", action="store_true",
                    help="interleave every active worker in this repo")
    sp.add_argument("--include-archived", action="store_true",
                    help="also offer workers terminal for over 6 hours in the menu")
    sp.add_argument("--from-start", action="store_true",
                    help="replay every message before following")
    sp.add_argument("--tail", type=int, default=WATCH_TAIL_CHARS,
                    help="characters of existing messages to show before following")
    sp.set_defaults(fn=cmd_watch)

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
