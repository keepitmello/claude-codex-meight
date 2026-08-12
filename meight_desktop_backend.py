"""Desktop execution backend over the versioned wy-server CLI contract."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from meight_remote_protocol import SCHEMA_VERSION, ProtocolError, spec_hash, validate_event, validate_receipt

HOST_ID = "wy-desktop-wsl"
REQUIRED_NODE_CAPABILITIES = {"generic_jobs", "artifact_get", "job_control"}
TERMINAL_REMOTE_STATES = {"COMPLETED", "FAILED", "INTERRUPTED"}


class DesktopBackendError(RuntimeError):
    def __init__(self, reason: str, detail: str, receipt: dict | None = None):
        super().__init__(detail)
        self.reason = reason
        self.receipt = receipt


class WyServerClient:
    def __init__(self, executable: str | None = None):
        self.executable = executable or os.environ.get("MEIGHT_WY_SERVER_BIN", "wy-server")

    def call(self, *args: str, timeout: float = 60.0) -> dict:
        try:
            proc = subprocess.run(
                [self.executable, *args], text=True, capture_output=True, timeout=timeout,
            )
        except FileNotFoundError as e:
            raise DesktopBackendError("target_not_ready", f"wy-server is not installed: {self.executable}") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopBackendError("target_unreachable", f"wy-server timed out: {' '.join(args)}") from e
        try:
            value = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise DesktopBackendError(
                "target_not_ready", f"wy-server returned non-JSON output (exit {proc.returncode})"
            ) from e
        if not isinstance(value, dict):
            raise DesktopBackendError("target_not_ready", "wy-server response is not an object")
        if proc.returncode != 0 or value.get("ok") is False:
            raise DesktopBackendError(
                str(value.get("reason") or "target_not_ready"),
                str(value.get("error") or value.get("reason") or f"wy-server exit {proc.returncode}"),
                value,
            )
        return value

    def ensure_ready(self, request_id: str, deadline_sec: int = 180) -> dict:
        receipt = self.call("ensure-ready", "--request-id", request_id, "--deadline", str(deadline_sec), "--json",
                            timeout=deadline_sec + 10)
        expires_at = receipt.get("expires_at")
        if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("state") != "READY":
            raise DesktopBackendError("target_not_ready", "wy-server did not return READY", receipt)
        if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
            raise DesktopBackendError("target_not_ready", "wy-server READY receipt is stale", receipt)
        missing = REQUIRED_NODE_CAPABILITIES - set(receipt.get("capabilities") or [])
        if missing:
            raise DesktopBackendError("target_not_ready", f"wy-server lacks capabilities: {sorted(missing)}", receipt)
        return receipt


def git_repo_spec(cwd: str, expected_root: str) -> dict:
    root = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"], check=True, text=True,
        capture_output=True,
    ).stdout.strip()
    if Path(root).resolve() != Path(expected_root).resolve():
        raise DesktopBackendError("remote_spawn_failed", "cwd does not belong to the recorded repository")
    dirty = subprocess.run(
        ["git", "-C", root, "status", "--porcelain", "--untracked-files=normal"],
        check=True, text=True, capture_output=True,
    ).stdout
    if dirty:
        raise DesktopBackendError("remote_spawn_failed", "desktop target requires a clean local git checkout")
    revision = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"], check=True, text=True, capture_output=True,
    ).stdout.strip()
    remote = subprocess.run(
        ["git", "-C", root, "remote", "get-url", "origin"], text=True, capture_output=True,
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        raise DesktopBackendError("remote_spawn_failed", "desktop target requires an origin remote")
    relative_cwd = str(Path(cwd).resolve().relative_to(Path(root).resolve()))
    return {"root": root, "remote_url": remote.stdout.strip(), "revision": revision,
            "relative_cwd": "." if relative_cwd == "." else relative_cwd}


class DesktopBackend:
    def __init__(self, worker, *, client: WyServerClient | None = None):
        self.worker = worker
        self.client = client or WyServerClient()

    def prepare_and_start(self, brief: str) -> dict:
        dispatch_id = str(uuid.uuid4())
        generation = self.worker.generation or 1
        with self.worker.lock:
            self.worker.status.update({
                "state": "target_preparing", "host_id": HOST_ID, "dispatch_id": dispatch_id,
                "remote_state": "PREPARING", "remote_event_seq": 0, "attempt_id": None,
            })
            self.worker.write_status(force=True)
        node = self.client.ensure_ready(dispatch_id)
        repo = git_repo_spec(self.worker.cwd, self.worker.repo_root)
        spec = {
            "schema_version": SCHEMA_VERSION, "dispatch_id": dispatch_id,
            "repo_key": self.worker.repo_key, "worker_name": self.worker.name,
            "generation": generation, "runtime": "codex", "source_revision": repo["revision"],
            "cwd": repo["relative_cwd"], "spool_dir": f"~/.local/state/meight-worker/runs/{dispatch_id}",
            "brief": brief,
            "runtime_config": {"model": self.worker.model, "effort": self.worker.effort,
                               "service_tier": self.worker.service_tier, "sandbox": self.worker.sandbox},
            "repo": {"remote_url": repo["remote_url"], "relative_cwd": repo["relative_cwd"]},
            "required_capabilities": ["event_stream", "interrupt"],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
            json.dump(spec, f, ensure_ascii=False, sort_keys=True)
            spec_path = f.name
        try:
            receipt = self.client.call(
                "job-start", "--id", dispatch_id, "--spec", spec_path, "--json", timeout=120,
            )
        finally:
            Path(spec_path).unlink(missing_ok=True)
        if receipt.get("state") != "RUNNING" or receipt.get("spec_hash") != spec_hash(spec):
            raise DesktopBackendError("remote_spawn_failed", "wy-server did not confirm matching RUNNING job", receipt)
        with self.worker.lock:
            self.worker.status.update({
                "state": "running", "remote_state": "RUNNING",
                "attempt_id": receipt.get("attempt_id"), "lease_epoch": receipt.get("lease_epoch"),
                "node_receipt": node, "source_revision": repo["revision"],
            })
            self.worker.write_status(force=True)
        return spec

    def monitor(self, spec: dict) -> None:
        dispatch_id = spec["dispatch_id"]
        generation = spec["generation"]
        after = int(self.worker.status.get("remote_event_seq") or 0)
        while True:
            response = self.client.call(
                "job-events", "--id", dispatch_id, "--after", str(after), "--wait", "20", "--json",
                timeout=30,
            )
            for event in response.get("events") or []:
                validate_event(event, dispatch_id=dispatch_id, generation=generation, after_seq=after)
                after = event["seq"]
                payload = event["payload"]
                if event["type"] == "runtime_event":
                    with self.worker.lock:
                        self.worker._handle_event(payload["method"], payload.get("payload") or {})
                with self.worker.lock:
                    self.worker.status["remote_event_seq"] = after
                    self.worker.write_status(force=True)
            receipt = validate_receipt(response["receipt"], dispatch_id=dispatch_id)
            with self.worker.lock:
                self.worker.status["remote_state"] = receipt["state"]
                self.worker.write_status(force=True)
            if receipt["state"] in TERMINAL_REMOTE_STATES:
                self._collect_terminal(dispatch_id, receipt)
                return

    def _collect_terminal(self, dispatch_id: str, receipt: dict) -> None:
        if receipt["state"] == "COMPLETED":
            result = self.client.call("artifact-get", "--id", dispatch_id, "--path", "result.md", "--json")
            data = bytes.fromhex(result["hex"])
            digest = hashlib.sha256(data).hexdigest()
            if digest != receipt.get("result_sha256"):
                raise DesktopBackendError("remote_result_corrupt", "remote result hash mismatch", receipt)
            local_result = self.worker.dir / "result.md"
            if not local_result.is_file() or not local_result.read_bytes().endswith(data):
                raise DesktopBackendError(
                    "remote_result_corrupt", "Mac result.md does not match remote result bytes", receipt,
                )
            remote_dir = self.worker.dir / "remote-artifacts" / dispatch_id
            remote_dir.mkdir(parents=True, exist_ok=True)
            (remote_dir / "result.md").write_bytes(data)
            for artifact in (receipt.get("artifacts") or {}).values():
                fetched = self.client.call("artifact-get", "--id", dispatch_id,
                                           "--path", artifact["path"], "--json")
                body = bytes.fromhex(fetched["hex"])
                if hashlib.sha256(body).hexdigest() != artifact["sha256"]:
                    raise DesktopBackendError("remote_result_corrupt", f"artifact hash mismatch: {artifact['path']}")
                path = remote_dir / artifact["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)

    def send_control(self, action: str, *, text: str | None = None) -> dict:
        status = self.worker.status
        args = ["job-control", "--id", status["dispatch_id"], "--attempt", status["attempt_id"],
                "--epoch", str(status["lease_epoch"]), "--action", action,
                "--generation", str(self.worker.generation), "--json"]
        if text is not None:
            args.extend(["--text", text])
        return self.client.call(*args)
