#!/usr/bin/env python3
"""Turn-scoped remote runner with durable, sequenced spool output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import threading
import time
from pathlib import Path

from meight_remote_protocol import (
    SCHEMA_VERSION, canonical_json, read_json, sha256_bytes, spec_hash, validate_spec,
)
from meight_runtime_codex import CodexRuntimeDriver


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(canonical_json(value) + b"\n")
    os.replace(tmp, path)


class Spool:
    def __init__(self, spec: dict):
        self.spec = validate_spec(spec)
        self.root = Path(spec["spool_dir"]).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = self.root / "events.jsonl"
        self.status = self.root / "status.json"
        self.lock = threading.Lock()
        self.seq = 0
        if self.events.is_file():
            for line in self.events.read_text(encoding="utf-8").splitlines():
                try:
                    self.seq = max(self.seq, int(json.loads(line).get("seq", 0)))
                except (ValueError, json.JSONDecodeError):
                    pass

    def receipt(self, state: str, **extra) -> dict:
        value = {
            "schema_version": SCHEMA_VERSION,
            "dispatch_id": self.spec["dispatch_id"],
            "generation": self.spec["generation"],
            "state": state,
            "spec_hash": self.spec.get("request_spec_hash") or spec_hash(self.spec),
            "last_seq": self.seq,
            "updated_at": time.time(),
            **extra,
        }
        atomic_json(self.status, value)
        return value

    def append(self, event_type: str, payload: dict) -> int:
        with self.lock:
            self.seq += 1
            row = {
                "schema_version": SCHEMA_VERSION,
                "dispatch_id": self.spec["dispatch_id"],
                "generation": self.spec["generation"],
                "seq": self.seq,
                "type": event_type,
                "payload": payload,
            }
            with open(self.events, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return self.seq


def build_artifacts(spec: dict, spool: Spool) -> dict:
    cwd = Path(spec["cwd"])
    artifact_dir = spool.root / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    patch_path = artifact_dir / "changes.patch"
    diff = subprocess.run(
        ["git", "-C", str(cwd), "diff", "--binary", spec["source_revision"], "--"],
        check=True, stdout=subprocess.PIPE,
    ).stdout
    patch_path.write_bytes(diff)
    untracked = subprocess.run(
        ["git", "-C", str(cwd), "ls-files", "--others", "--exclude-standard", "-z"],
        check=True, stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    paths = [p.decode("utf-8") for p in untracked if p]
    manifest = []
    bundle = artifact_dir / "untracked.tar"
    with tarfile.open(bundle, "w") as tar:
        for relative in paths:
            source = (cwd / relative).resolve()
            source.relative_to(cwd.resolve())
            if source.is_file():
                data = source.read_bytes()
                manifest.append({"path": relative, "sha256": sha256_bytes(data), "size": len(data)})
                tar.add(source, arcname=relative, recursive=False)
    manifest_path = artifact_dir / "untracked.json"
    atomic_json(manifest_path, {"files": manifest})
    return {
        "patch": {"path": "artifacts/changes.patch", "sha256": sha256_bytes(diff)},
        "untracked": {"path": "artifacts/untracked.tar", "sha256": sha256_bytes(bundle.read_bytes())},
        "manifest": {"path": "artifacts/untracked.json", "sha256": sha256_bytes(manifest_path.read_bytes())},
    }


def control_loop(spool: Spool, driver, stop: threading.Event) -> None:
    inbox = spool.root / "control.jsonl"
    ack = spool.root / "control-acks.jsonl"
    offset = 0
    while not stop.wait(0.2):
        try:
            with open(inbox, encoding="utf-8") as f:
                f.seek(offset)
                lines = f.readlines()
                offset = f.tell()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                command = json.loads(line)
                if command.get("generation") != spool.spec["generation"]:
                    raise ValueError("stale generation")
                action = command.get("action")
                if action == "steer":
                    driver.steer(str(command.get("text") or ""))
                elif action == "interrupt":
                    driver.interrupt()
                else:
                    raise ValueError(f"unsupported action: {action}")
                result = {"control_id": command.get("control_id"), "accepted": True}
            except Exception as e:
                result = {"control_id": command.get("control_id") if isinstance(command, dict) else None,
                          "accepted": False, "error": f"{type(e).__name__}: {e}"}
            with open(ack, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, separators=(",", ":")) + "\n")


def run(spec_path: Path) -> int:
    spec = validate_spec(read_json(spec_path))
    spool = Spool(spec)
    stored = spool.root / "spec.json"
    if stored.exists():
        if spec_hash(read_json(stored)) != spec_hash(spec):
            raise RuntimeError("dispatch id already exists with a different spec")
    else:
        atomic_json(stored, spec)
    driver = CodexRuntimeDriver(
        cwd=spec["cwd"], sandbox=spec["runtime_config"]["sandbox"],
        runtime_config={**spec["runtime_config"], "worker_name": spec["worker_name"]},
    )
    stop = threading.Event()
    controls = threading.Thread(target=control_loop, args=(spool, driver, stop), daemon=True)
    controls.start()
    messages: list[str] = []
    terminal_state = "FAILED"
    spool.receipt("RUNNING", provider_state=driver.provider_state, pid=os.getpid())
    try:
        for event in driver.start(spec["brief"]):
            spool.append("runtime_event", event)
            if event["method"] == "item/completed":
                item = event["payload"].get("item") or {}
                if item.get("type") == "agentMessage":
                    messages.append(str(item.get("text") or ""))
            elif event["method"] == "turn/completed":
                status = (event["payload"].get("turn") or {}).get("status")
                terminal_state = {"completed": "COMPLETED", "interrupted": "INTERRUPTED"}.get(status, "FAILED")
        result = (messages[-1] if messages else "(no agent message)") + "\n"
        result_path = spool.root / "result.md"
        result_path.write_text(result, encoding="utf-8")
        digest = sha256_bytes(result.encode("utf-8"))
        (spool.root / "result.sha256").write_text(digest + "\n", encoding="ascii")
        artifacts = build_artifacts(spec, spool)
        spool.append("terminal", {"state": terminal_state, "result_sha256": digest, "artifacts": artifacts})
        spool.receipt(terminal_state, result_sha256=digest, artifacts=artifacts, provider_state=driver.provider_state)
        return 0 if terminal_state == "COMPLETED" else 2
    except Exception as e:
        spool.append("terminal", {"state": "FAILED", "error": f"{type(e).__name__}: {e}"})
        spool.receipt("FAILED", error=f"{type(e).__name__}: {e}")
        return 2
    finally:
        stop.set()
        driver.close()


def events(spool: Path, after: int) -> int:
    spool = spool.expanduser().resolve()
    rows = []
    path = spool / "events.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if int(row.get("seq", 0)) > after:
                rows.append(row)
    status = read_json(spool / "status.json") if (spool / "status.json").is_file() else None
    print(json.dumps({"schema_version": SCHEMA_VERSION, "events": rows, "receipt": status}, separators=(",", ":")))
    return 0


def control(spool: Path, generation: int, action: str, text: str | None, timeout: float) -> int:
    spool = spool.expanduser().resolve()
    control_id = os.urandom(12).hex()
    command = {"control_id": control_id, "generation": generation, "action": action}
    if text is not None:
        command["text"] = text
    inbox = spool / "control.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "a", encoding="utf-8") as f:
        f.write(json.dumps(command, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    deadline = time.monotonic() + timeout
    ack_path = spool / "control-acks.jsonl"
    while time.monotonic() < deadline:
        if ack_path.is_file():
            for line in ack_path.read_text(encoding="utf-8").splitlines():
                ack = json.loads(line)
                if ack.get("control_id") == control_id:
                    print(json.dumps({"schema_version": SCHEMA_VERSION, **ack}, separators=(",", ":")))
                    return 0 if ack.get("accepted") else 2
        time.sleep(0.1)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "control_id": control_id,
                      "accepted": False, "error": "control ack timeout"}, separators=(",", ":")))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--spec", required=True, type=Path)
    events_parser = sub.add_parser("events")
    events_parser.add_argument("--spool", required=True, type=Path)
    events_parser.add_argument("--after", type=int, default=0)
    control_parser = sub.add_parser("control")
    control_parser.add_argument("--spool", required=True, type=Path)
    control_parser.add_argument("--generation", required=True, type=int)
    control_parser.add_argument("--action", choices=("steer", "interrupt"), required=True)
    control_parser.add_argument("--text")
    control_parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.command == "run":
        return run(args.spec)
    if args.command == "events":
        return events(args.spool, args.after)
    return control(args.spool, args.generation, args.action, args.text, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
