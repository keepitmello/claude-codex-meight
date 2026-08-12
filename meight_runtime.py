"""Small runtime boundary used inside both local and remote execution."""

from __future__ import annotations

from typing import Protocol


class RuntimeDriver(Protocol):
    capabilities: tuple[str, ...]
    provider: str

    @property
    def provider_state(self) -> dict: ...
    def start(self, brief: str): ...
    def steer(self, text: str) -> None: ...
    def interrupt(self) -> None: ...
    def close(self) -> None: ...


def normalize_sdk_event(note) -> dict:
    """Convert an SDK note to JSON without leaking SDK classes into the protocol."""
    payload = note.payload
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else (
        payload if isinstance(payload, dict) else {}
    )
    return {"method": str(note.method), "payload": value}
