"""Codex implementation of the provider-neutral runtime driver."""

from __future__ import annotations

from meight_runtime import normalize_sdk_event


class CodexRuntimeDriver:
    provider = "codex"
    capabilities = ("event_stream", "interrupt", "steer")

    def __init__(self, *, cwd: str, sandbox: str, runtime_config: dict):
        from openai_codex import Codex, CodexConfig, Sandbox
        from openai_codex.types import ThreadSource

        import meight

        self._runtime_config = runtime_config
        self._codex = Codex(config=CodexConfig(codex_bin=meight.system_codex_bin()))
        meight.install_computer_use_approval_bridge(self._codex, runtime_config.get("worker_name", "remote"))
        meight.relax_sdk_effort_echo()
        self._thread = self._codex.thread_start(
            cwd=cwd,
            ephemeral=True,
            sandbox=getattr(Sandbox, sandbox),
            thread_source=ThreadSource.subagent,
        )
        self._handle = None

    @property
    def provider_state(self) -> dict:
        return {"codex": {"thread_id": self._thread.id}}

    def start(self, brief: str):
        import meight

        meight.relax_sdk_effort_field()
        self._handle = self._thread.turn(
            brief,
            model=self._runtime_config.get("model"),
            effort=self._runtime_config.get("effort"),
            service_tier=self._runtime_config.get("service_tier"),
        )
        for note in self._handle.stream():
            yield normalize_sdk_event(note)

    def steer(self, text: str) -> None:
        if self._handle is None:
            raise RuntimeError("runtime has no live turn")
        self._handle.steer(text)

    def interrupt(self) -> None:
        if self._handle is not None:
            self._handle.interrupt()

    def close(self) -> None:
        self._handle = None
        self._thread = None
        self._codex.close()
