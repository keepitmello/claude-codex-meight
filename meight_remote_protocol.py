"""Versioned, provider-neutral protocol shared by meight and remote runners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
RUNNER_CAPABILITIES = ("event_stream", "interrupt", "steer", "artifact_bundle")
RUNNER_STATES = {"PREPARING", "RUNNING", "NEEDS_INPUT", "COMPLETED", "FAILED", "INTERRUPTED"}


class ProtocolError(ValueError):
    pass


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def spec_hash(spec: dict) -> str:
    return sha256_bytes(canonical_json(spec))


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported remote spec schema")
    required = {
        "dispatch_id", "repo_key", "worker_name", "generation", "runtime",
        "source_revision", "cwd", "spool_dir", "brief", "runtime_config",
    }
    missing = sorted(required - set(spec))
    if missing:
        raise ProtocolError(f"remote spec missing: {', '.join(missing)}")
    if spec["runtime"] != "codex":
        raise ProtocolError(f"unsupported runtime: {spec['runtime']!r}")
    if not isinstance(spec["generation"], int) or spec["generation"] < 1:
        raise ProtocolError("generation must be a positive integer")
    for key in ("dispatch_id", "repo_key", "worker_name", "source_revision", "cwd", "spool_dir"):
        if not isinstance(spec[key], str) or not spec[key]:
            raise ProtocolError(f"{key} must be a non-empty string")
    return spec


def validate_event(event: dict, *, dispatch_id: str, generation: int, after_seq: int = 0) -> dict:
    if not isinstance(event, dict) or event.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported remote event schema")
    if event.get("dispatch_id") != dispatch_id or event.get("generation") != generation:
        raise ProtocolError("remote event identity mismatch")
    seq = event.get("seq")
    if not isinstance(seq, int) or seq <= after_seq:
        raise ProtocolError("remote event sequence is stale or invalid")
    if event.get("type") not in {"runtime_event", "terminal"}:
        raise ProtocolError(f"unsupported remote event type: {event.get('type')!r}")
    if not isinstance(event.get("payload"), dict):
        raise ProtocolError("remote event payload must be an object")
    return event


def validate_receipt(receipt: dict, *, dispatch_id: str | None = None) -> dict:
    if not isinstance(receipt, dict) or receipt.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported runner receipt schema")
    if dispatch_id is not None and receipt.get("dispatch_id") != dispatch_id:
        raise ProtocolError("runner receipt dispatch mismatch")
    if receipt.get("state") not in RUNNER_STATES:
        raise ProtocolError(f"invalid runner state: {receipt.get('state')!r}")
    return receipt


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProtocolError(f"expected JSON object: {path}")
    return value
