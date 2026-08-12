#!/usr/bin/env python3
"""Versioned node facade over the installed wy-server transport.

This source is intentionally not installed by repository tests. It preserves
existing job/lease identity by delegating status/control to the transport instead of
moving ~/.local/state/mac-worker or rewriting active attempts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from meight_remote_protocol import SCHEMA_VERSION, spec_hash, validate_spec

CAPABILITIES = ["generic_jobs", "artifact_get", "job_control"]
JOB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
REMOTE_SKILLS_ROOT = "~/.local/lib/meight/skills"
TRANSPORT_COMMANDS = {
    "wake", "wait", "ensure", "status", "health", "run", "job", "job-stop", "sleep",
}
USAGE = """usage: wy-server COMMAND [ARGS]

Desktop control:
  wake | wait | ensure | status | health | run CMD
  job ID CWD CMD | job-status ID | job-stop ID ATTEMPT EPOCH | sleep

Meight node API:
  ensure-ready | job-start | job-status --id ID | job-events
  job-control | artifact-get
"""


class WyServerError(RuntimeError):
    def __init__(self, reason: str, message: str, exit_code: int = 2):
        super().__init__(message)
        self.reason = reason
        self.exit_code = exit_code


def transport_bin() -> str:
    return os.environ.get(
        "WY_SERVER_TRANSPORT_BIN", str(Path.home() / ".local/bin/wy-server-transport")
    )


def transport(*args: str, timeout: float = 60.0, check: bool = True) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [transport_bin(), *args], text=True, capture_output=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise WyServerError("NODE_NOT_READY", "wy-server transport is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise WyServerError("NODE_UNREACHABLE", f"wy-server transport timed out: {args[0]}") from e
    if check and proc.returncode != 0:
        raise WyServerError("NODE_NOT_READY", proc.stdout.strip() or proc.stderr.strip(), proc.returncode)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_object(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise WyServerError("NODE_NOT_READY", "legacy transport returned non-JSON output") from e
    if not isinstance(value, dict):
        raise WyServerError("NODE_NOT_READY", "legacy transport response is not an object")
    return value


def repo_registry() -> dict:
    path = Path(os.environ.get("WY_SERVER_REPO_CONFIG", Path.home() / ".config/wy-server/repos.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise WyServerError("REPO_NOT_CONFIGURED", f"repo registry not found: {path}") from e
    if not isinstance(value, dict) or not isinstance(value.get("repos"), dict):
        raise WyServerError("REPO_NOT_CONFIGURED", f"invalid repo registry: {path}")
    return value["repos"]


def wsl_runner() -> str:
    return os.environ.get("WY_SERVER_MEIGHT_RUNNER", "~/.local/lib/meight/meight_remote_runner.py")


def wsl_runner_python() -> str:
    return os.environ.get("WY_SERVER_MEIGHT_PYTHON", "~/.local/lib/meight/.venv/bin/python")


def remote_shell_path(path: str) -> str:
    """Quote a remote path while preserving a leading WSL-home expansion."""
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


def remote_contract_brief(brief: str) -> str:
    """Translate harness-owned Mac contract paths at the remote wire boundary."""
    import meight

    translated = brief
    for mode, local_path in meight.MODE_SKILL_PATHS.items():
        translated = translated.replace(
            str(local_path), f"{REMOTE_SKILLS_ROOT}/meight-{mode}/SKILL.md",
        )
    return translated.replace(
        str(meight.COMMON_CONTRACT_PATH),
        f"{REMOTE_SKILLS_ROOT}/meight-common/CONTRACT.md",
    )


def ensure_ready(request_id: str, deadline: int) -> dict:
    code, out, _ = transport("ensure", timeout=deadline + 5, check=False)
    legacy = parse_object(out)
    if code != 0 or legacy.get("state") not in ("READY", "WORKER_READY"):
        raise WyServerError("NODE_NOT_READY", str(legacy.get("reason") or "worker not ready"), code or 2)
    return {
        "schema_version": SCHEMA_VERSION, "ok": True, "node_id": "wy-desktop-wsl",
        "state": "READY", "observed_at": time.time(), "expires_at": time.time() + 10,
        "readiness_generation": legacy.get("control_nonce") or request_id,
        "capabilities": CAPABILITIES, "capacity": legacy.get("capacity") or {},
        "legacy_receipt": legacy,
    }


def job_start(job_id: str, spec_path: Path) -> dict:
    if not JOB_ID_RE.fullmatch(job_id):
        raise WyServerError("JOB_START_FAILED", "invalid job id")
    spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8")))
    if spec["dispatch_id"] != job_id:
        raise WyServerError("JOB_START_FAILED", "job id and dispatch id differ")
    repo = repo_registry().get(spec["repo_key"])
    if not isinstance(repo, dict):
        raise WyServerError("REPO_NOT_CONFIGURED", f"no desktop mapping for {spec['repo_key']}")
    mirror = str(repo.get("desktop_mirror") or "")
    worktree_root = str(repo.get("worktree_root") or "")
    if not mirror or not worktree_root:
        raise WyServerError("REPO_NOT_CONFIGURED", "desktop_mirror and worktree_root are required")
    worktree = f"{worktree_root.rstrip('/')}/{job_id}"
    relative = str((spec.get("repo") or {}).get("relative_cwd") or ".")
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise WyServerError("JOB_START_FAILED", "relative cwd escapes the worktree")
    remote_spec = dict(spec)
    remote_spec["request_spec_hash"] = spec_hash(spec)
    remote_spec["brief"] = remote_contract_brief(spec["brief"])
    remote_spec["cwd"] = worktree if relative == "." else f"{worktree}/{relative}"
    encoded = base64.b64encode(json.dumps(remote_spec, sort_keys=True).encode()).decode()
    prep = " && ".join((
        f"git --git-dir={shlex.quote(mirror)} fetch --prune origin",
        f"mkdir -p {shlex.quote(worktree_root)}",
        f"git --git-dir={shlex.quote(mirror)} worktree add --detach {shlex.quote(worktree)} {shlex.quote(spec['source_revision'])}",
        f"mkdir -p {remote_spec['spool_dir']}",
        f"printf %s {shlex.quote(encoded)} | base64 -d > {remote_spec['spool_dir']}/launch-spec.json",
    ))
    transport("run", prep, timeout=180)
    command = (
        f"{remote_shell_path(wsl_runner_python())} {remote_shell_path(wsl_runner())} run --spec "
        f"{remote_spec['spool_dir']}/launch-spec.json"
    )
    _, out, _ = transport("job", job_id, worktree, command, timeout=60)
    receipt = parse_object(out)
    state = receipt.get("state")
    if state not in ("RUNNING", "STARTED"):
        raise WyServerError("JOB_START_FAILED", f"legacy job did not start: {state}")
    return {
        "schema_version": SCHEMA_VERSION, "ok": True, "state": "RUNNING",
        "dispatch_id": job_id, "attempt_id": receipt.get("attempt_id"),
        "lease_epoch": receipt.get("lease_epoch"), "spec_hash": spec_hash(spec),
        "legacy_receipt": receipt,
    }


def job_status(job_id: str) -> dict:
    # Compatibility rule: never migrate or rewrite legacy job state. Query it in
    # place through the installed helper and preserve attempt/lease fields.
    _, out, _ = transport("job-status", job_id)
    receipt = parse_object(out)
    return {**receipt, "schema_version": SCHEMA_VERSION, "ok": True, "legacy_receipt": receipt}


def remote_json(command: str) -> dict:
    _, out, _ = transport("run", command)
    return parse_object(out)


def job_events(job_id: str, after: int, wait: int) -> dict:
    spool = f"~/.local/state/meight-worker/runs/{job_id}"
    command = (f"{remote_shell_path(wsl_runner_python())} {remote_shell_path(wsl_runner())} events --spool {remote_shell_path(spool)} "
               f"--after {after}")
    return remote_json(command)


def job_control(job_id: str, attempt: str, epoch: int, action: str, generation: int,
                text: str | None) -> dict:
    # Validate the authoritative legacy attempt/epoch before writing the runner inbox.
    status = job_status(job_id)
    if status.get("attempt_id") != attempt or int(status.get("lease_epoch", -1)) != epoch:
        raise WyServerError("STALE_LEASE", "attempt or lease epoch mismatch")
    spool = f"~/.local/state/meight-worker/runs/{job_id}"
    command = (f"{remote_shell_path(wsl_runner_python())} {remote_shell_path(wsl_runner())} control --spool {remote_shell_path(spool)} "
               f"--generation {generation} --action {action}")
    if text is not None:
        command += f" --text {shlex.quote(text)}"
    ack = remote_json(command)
    if not ack.get("accepted"):
        raise WyServerError("CONTROL_REJECTED", str(ack.get("error") or "runner rejected control"))
    return {"schema_version": SCHEMA_VERSION, "ok": True, "dispatch_id": job_id, **ack}


def artifact_get(job_id: str, relative: str) -> dict:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise WyServerError("INVALID_ARTIFACT", "artifact path must stay inside the spool")
    spool = f"~/.local/state/meight-worker/runs/{job_id}"
    _, out, _ = transport("run", f"base64 -w0 {spool}/{shlex.quote(relative)}")
    try:
        data = base64.b64decode(out, validate=True)
    except ValueError as e:
        raise WyServerError("INVALID_ARTIFACT", "remote artifact was not valid base64") from e
    return {"schema_version": SCHEMA_VERSION, "ok": True, "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(), "hex": data.hex()}


def main() -> int:
    if len(sys.argv) == 1 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE.rstrip())
        return 0
    direct_transport = len(sys.argv) > 1 and (
        sys.argv[1] in TRANSPORT_COMMANDS
        or sys.argv[1] == "--human"
        or (sys.argv[1] == "job-status" and len(sys.argv) > 2 and sys.argv[2] != "--id")
    )
    if direct_transport:
        try:
            return subprocess.run([transport_bin(), *sys.argv[1:]]).returncode
        except FileNotFoundError:
            print(json.dumps({"schema_version": SCHEMA_VERSION, "ok": False,
                              "reason": "NODE_NOT_READY",
                              "error": "wy-server transport is not installed"}, separators=(",", ":")))
            return 2
    parser = argparse.ArgumentParser(prog="wy-server")
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("ensure-ready"); ready.add_argument("--request-id", required=True); ready.add_argument("--deadline", type=int, default=180); ready.add_argument("--json", action="store_true")
    start = sub.add_parser("job-start"); start.add_argument("--id", required=True); start.add_argument("--spec", required=True, type=Path); start.add_argument("--json", action="store_true")
    status = sub.add_parser("job-status"); status.add_argument("--id", required=True); status.add_argument("--json", action="store_true")
    events = sub.add_parser("job-events"); events.add_argument("--id", required=True); events.add_argument("--after", type=int, default=0); events.add_argument("--wait", type=int, default=20); events.add_argument("--json", action="store_true")
    control = sub.add_parser("job-control"); control.add_argument("--id", required=True); control.add_argument("--attempt", required=True); control.add_argument("--epoch", required=True, type=int); control.add_argument("--action", choices=("steer", "interrupt"), required=True); control.add_argument("--generation", type=int, required=True); control.add_argument("--text"); control.add_argument("--json", action="store_true")
    artifact = sub.add_parser("artifact-get"); artifact.add_argument("--id", required=True); artifact.add_argument("--path", required=True); artifact.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "ensure-ready": result = ensure_ready(args.request_id, args.deadline)
        elif args.command == "job-start": result = job_start(args.id, args.spec)
        elif args.command == "job-status": result = job_status(args.id)
        elif args.command == "job-events": result = job_events(args.id, args.after, args.wait)
        elif args.command == "job-control": result = job_control(args.id, args.attempt, args.epoch, args.action, args.generation, args.text)
        else: result = artifact_get(args.id, args.path)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except WyServerError as e:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "ok": False,
                          "reason": e.reason, "error": str(e)}, separators=(",", ":")))
        return e.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
