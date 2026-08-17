import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import meight
import meight_desktop_backend
import meight_remote_protocol
import wy_server


class ModelAliasTests(unittest.TestCase):
    def test_known_aliases_and_custom_model_pass_through(self):
        self.assertEqual(meight.normalize_model("sol"), "gpt-5.6-sol")
        self.assertEqual(meight.normalize_model("terra"), "gpt-5.6-terra")
        self.assertEqual(meight.normalize_model("luna"), "gpt-5.6-luna")
        self.assertEqual(meight.normalize_model("grok"), "xai/grok-4.6")
        self.assertEqual(meight.normalize_model("xai/grok-4.6"), "xai/grok-4.6")
        self.assertEqual(meight.normalize_model("vendor/custom-model"), "vendor/custom-model")
        self.assertIsNone(meight.normalize_model(None))


class StartDefaultsTests(unittest.TestCase):
    EXPECTED = {
        "mate": ("gpt-5.6-sol", "medium", "default", "full"),
        "worker": ("xai/grok-4.6", "high", "default", "full"),
    }

    def _args(self, command: str, mode: str, *options: str):
        return meight.build_parser().parse_args([
            command, f"defaults-{mode}", "--mode", mode,
            "--brief", "Exercise start defaults.", *options,
        ])

    def _start_request(self, args):
        responses = (
            {"ok": True, "capabilities": [meight.PROTOCOL_EPOCH]},
            {"ok": True, "thread_id": "thread-defaults",
             "mode": meight.normalize_mode(args.mode),
             "target": args.target, "runtime": "codex",
             "protocol_epoch": meight.PROTOCOL_EPOCH},
        )
        with patch.object(meight, "send_request", side_effect=responses) as send:
            response = meight.start_request(args, Path("/tmp/meight-defaults"))
        self.assertTrue(response["ok"])
        return send.call_args_list[1].args[1]

    def test_each_mode_resolves_omitted_start_flags_on_the_cli_wire(self):
        for mode, expected in self.EXPECTED.items():
            with self.subTest(mode=mode):
                request = self._start_request(self._args("dispatch", mode))
                model, effort, tier, sandbox = expected
                self.assertEqual(
                    (request["model"], request["effort"], request["service_tier"],
                     request["sandbox"]),
                    (model, effort, tier, sandbox),
                )
                self.assertEqual(request["mode"], mode)
                self.assertEqual(request["target"], "mac")
                self.assertEqual(request["runtime"], "codex")

    def test_desktop_target_is_explicit_on_the_cli_wire(self):
        request = self._start_request(self._args("dispatch", "worker", "--target", "desktop"))
        self.assertEqual(request["target"], "desktop")

    def test_explicit_cwd_selects_the_recorded_repository_namespace(self):
        args = self._args("dispatch", "worker", "--cwd", "/tmp/target-repo")
        with patch.object(meight, "request_repo_context", return_value={
            "repo_root": "/tmp/target-repo",
            "repo_key": "target-repo-key",
            "repo_home": "/tmp/meight/repos/target-repo-key",
        }) as context:
            request = self._start_request(args)
        context.assert_called_once_with(Path("/tmp/meight-defaults"), "/tmp/target-repo")
        self.assertEqual(request["repo_root"], "/tmp/target-repo")

    def test_legacy_alias_modes_resolve_to_posture_defaults_on_the_wire(self):
        for alias, canonical in (("design", "mate"), ("review", "mate"), ("delegate", "worker")):
            with self.subTest(alias=alias):
                request = self._start_request(self._args("dispatch", alias))
                model, effort, tier, sandbox = self.EXPECTED[canonical]
                self.assertEqual(
                    (request["model"], request["effort"], request["service_tier"],
                     request["sandbox"]),
                    (model, effort, tier, sandbox),
                )
                self.assertEqual(request["mode"], canonical)

    def test_explicit_flags_override_every_mode_default(self):
        args = self._args(
            "dispatch", "mate", "--model", "terra", "--effort", "max",
            "--fast", "--sandbox", "ro",
        )
        request = self._start_request(args)
        self.assertEqual(
            (request["model"], request["effort"], request["service_tier"],
             request["sandbox"]),
            ("gpt-5.6-terra", "max", "priority", "ro"),
        )

    def test_explicit_known_model_reselects_its_effort_default(self):
        cases = (
            ("worker", "sol", "medium"),
            ("worker", "gpt-5.6-sol", "medium"),
            ("worker", "grok", "high"),
            ("worker", "xai/grok-4.6", "high"),
            ("mate", "luna", "max"),
            ("mate", "gpt-5.6-luna", "max"),
            ("mate", "grok", "high"),
            ("mate", "xai/grok-4.6", "high"),
        )
        for mode, model, effort in cases:
            with self.subTest(mode=mode, model=model):
                request = self._start_request(
                    self._args("dispatch", mode, "--model", model),
                )
                self.assertEqual(request["effort"], effort)

    def test_explicit_luna_reselects_max_effort_and_fast_defaults(self):
        for mode in ("worker", "mate"):
            with self.subTest(mode=mode):
                request = self._start_request(
                    self._args("dispatch", mode, "--model", "luna"),
                )
                self.assertEqual(
                    (request["model"], request["effort"], request["service_tier"]),
                    ("gpt-5.6-luna", "max", "priority"),
                )

    def test_model_fast_defaults_reselect_only_when_fast_is_omitted(self):
        cases = (
            ("worker", ("--model", "luna"), True, "default"),
            ("mate", ("--model", "luna"), True, "default"),
            ("worker", ("--model", "luna", "--no-fast"), False, "set"),
            ("mate", ("--model", "sol", "--fast"), True, "set"),
        )
        for mode, options, expected_fast, expected_provenance in cases:
            with self.subTest(mode=mode, options=options):
                args = self._args("dispatch", mode, *options)
                values, provenance = meight.resolve_start_options(args)
                self.assertEqual(values["fast"], expected_fast)
                self.assertEqual(provenance["fast"], expected_provenance)

    def test_dispatch_uses_the_same_resolution_and_start_path(self):
        start_args = self._args("dispatch", "worker", "--model", "sol", "--fast")
        dispatch_args = self._args("dispatch", "worker", "--model", "sol", "--fast")
        self.assertEqual(meight.resolve_start_options(start_args),
                         meight.resolve_start_options(dispatch_args))
        response = {
            "ok": True, "thread_id": "thread-dispatch", "mode": "worker",
            "protocol_epoch": meight.PROTOCOL_EPOCH,
        }
        output = io.StringIO()
        with (
            patch.object(meight, "ensure_daemon", return_value=True),
            patch.object(meight, "start_request", return_value=response) as start,
            patch.object(meight, "wait_for_worker", return_value=1),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(meight.cmd_dispatch(dispatch_args, Path("/tmp/meight-defaults")), 1)
        start.assert_called_once_with(dispatch_args, Path("/tmp/meight-defaults"))
        self.assertIn(
            "mode=worker model=sol(set) "
            "effort=medium(default) fast=on(set) sandbox=full(default)",
            output.getvalue(),
        )

    def test_dispatch_timeout_caps_capacity_retry_budget_on_wire(self):
        args = meight.build_parser().parse_args([
            "dispatch", "budget-test", "--mode", "worker", "--brief", "brief",
            "--timeout", "120",
        ])
        request = self._start_request(args)
        self.assertEqual(request["capacity_retry_budget_sec"], 120.0)


class RemoteProtocolTests(unittest.TestCase):
    def _spec(self):
        return {
            "schema_version": 1, "dispatch_id": "dispatch-1", "repo_key": "repo-key",
            "worker_name": "worker", "generation": 1, "runtime": "codex",
            "source_revision": "a" * 40, "cwd": ".", "spool_dir": "/tmp/spool",
            "brief": "Do the work.", "runtime_config": {},
        }

    def test_spec_hash_is_stable_and_provider_neutral(self):
        spec = self._spec()
        meight_remote_protocol.validate_spec(spec)
        self.assertEqual(meight_remote_protocol.spec_hash(spec),
                         meight_remote_protocol.spec_hash(dict(reversed(list(spec.items())))))
        body = meight_remote_protocol.canonical_json(spec).decode()
        self.assertNotIn("thread_id", body)
        self.assertNotIn("openai_codex", body)

    def test_event_sequence_and_generation_fail_closed(self):
        event = {"schema_version": 1, "dispatch_id": "dispatch-1", "generation": 1,
                 "seq": 2, "type": "runtime_event", "payload": {"method": "turn/started"}}
        meight_remote_protocol.validate_event(
            event, dispatch_id="dispatch-1", generation=1, after_seq=1,
        )
        with self.assertRaises(meight_remote_protocol.ProtocolError):
            meight_remote_protocol.validate_event(
                event, dispatch_id="dispatch-1", generation=2, after_seq=1,
            )
        with self.assertRaises(meight_remote_protocol.ProtocolError):
            meight_remote_protocol.validate_event(
                event, dispatch_id="dispatch-1", generation=1, after_seq=2,
            )


class DesktopBackendTests(unittest.TestCase):
    class _FakeClient:
        def __init__(self, result: bytes = b"remote result\n"):
            self.result = result

        def call(self, *args, timeout=60.0):
            if args[0] == "artifact-get":
                return {"hex": self.result.hex()}
            raise AssertionError(args)

    def _worker(self, root: Path):
        worker = meight.Worker(
            "remote", root, str(root), "repo-key", str(root), "full_access",
            "gpt-5.6-sol", "medium", "default", target="desktop",
        )
        worker.dir.mkdir(parents=True)
        worker.init_status(None)
        worker.generation = 1
        worker.status.update({"dispatch_id": "dispatch-1", "attempt_id": "attempt-1", "lease_epoch": 3})
        (worker.dir / "result.md").write_bytes(b"remote result\n")
        return worker

    def test_remote_result_hash_is_verified_and_collected_without_applying(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(Path(tmp))
            client = self._FakeClient()
            backend = meight_desktop_backend.DesktopBackend(worker, client=client)
            digest = __import__("hashlib").sha256(client.result).hexdigest()
            backend._collect_terminal("dispatch-1", {
                "state": "COMPLETED", "result_sha256": digest, "artifacts": {},
            })
            collected = worker.dir / "remote-artifacts" / "dispatch-1" / "result.md"
            self.assertEqual(collected.read_bytes(), client.result)
            self.assertFalse((Path(tmp) / "result.md").exists())

    def test_remote_result_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(Path(tmp))
            backend = meight_desktop_backend.DesktopBackend(worker, client=self._FakeClient())
            with self.assertRaises(meight_desktop_backend.DesktopBackendError) as caught:
                backend._collect_terminal("dispatch-1", {
                    "state": "COMPLETED", "result_sha256": "0" * 64, "artifacts": {},
                })
            self.assertEqual(caught.exception.reason, "remote_result_corrupt")

    def test_control_is_fenced_by_attempt_epoch_and_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(Path(tmp))
            client = self._FakeClient()
            client.call = Mock(return_value={"accepted": True})
            backend = meight_desktop_backend.DesktopBackend(worker, client=client)
            backend.send_control("interrupt")
            args = client.call.call_args.args
            self.assertIn("attempt-1", args)
            self.assertIn("3", args)
            self.assertIn("1", args)


class WyServerCompatibilityTests(unittest.TestCase):
    def test_current_worker_ready_receipt_is_accepted(self):
        legacy = {
            "state": "WORKER_READY", "control_nonce": "nonce-1",
            "capacity": {"running_jobs": 0},
        }
        with patch.object(wy_server, "transport", return_value=(0, json.dumps(legacy), "")):
            receipt = wy_server.ensure_ready("request-1", 30)
        self.assertEqual(receipt["state"], "READY")
        self.assertEqual(receipt["readiness_generation"], "nonce-1")

    def test_remote_shell_path_preserves_wsl_home_expansion(self):
        rendered = wy_server.remote_shell_path("~/.local/lib/meight runner.py")
        self.assertEqual(rendered, '"$HOME"/\'.local/lib/meight runner.py\'')
        self.assertNotIn("'~", rendered)

    def test_remote_runner_uses_its_pinned_virtualenv(self):
        self.assertEqual(
            wy_server.wsl_runner_python(),
            "~/.local/lib/meight/.venv/bin/python",
        )

    def test_wire_translates_contract_paths_for_wsl(self):
        translated = wy_server.remote_contract_brief(meight.build_preamble("worker"))
        self.assertIn("~/.local/lib/meight/skills/meight-worker/SKILL.md", translated)
        self.assertIn("~/.local/lib/meight/skills/meight-common/CONTRACT.md", translated)

    def test_legacy_job_status_preserves_attempt_and_lease_without_state_move(self):
        legacy = {"state": "RUNNING", "attempt_id": "old-attempt", "lease_epoch": 17,
                  "state_dir": "/home/keepi/.local/state/mac-worker/jobs/old-job"}
        with patch.object(wy_server, "transport", return_value=(0, json.dumps(legacy), "")) as call:
            receipt = wy_server.job_status("old-job")
        call.assert_called_once_with("job-status", "old-job")
        self.assertEqual(receipt["attempt_id"], "old-attempt")
        self.assertEqual(receipt["lease_epoch"], 17)
        self.assertEqual(receipt["state_dir"], legacy["state_dir"])
        self.assertEqual(receipt["legacy_receipt"], legacy)


class DispatchSurfaceTests(unittest.TestCase):
    def _args(self, name="dispatch-test"):
        return meight.build_parser().parse_args([
            "dispatch", name, "--mode", "worker", "--brief", "new brief", "--timeout", "12",
        ])

    def test_cli_surface_has_no_start_or_wait_subcommands(self):
        parser = meight.build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"
        )
        self.assertNotIn("start", subparsers.choices)
        self.assertNotIn("wait", subparsers.choices)
        for removed in ("start", "wait"):
            with self.subTest(removed=removed), self.assertRaises(SystemExit) as error:
                parser.parse_args([removed, "worker-1"])
            self.assertEqual(error.exception.code, 2)

    def test_dispatch_reattaches_to_active_disk_row_without_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo_home = Path(tmp) / "repo"
            worker_dir = repo_home / "workers" / "reattach-test"
            worker_dir.mkdir(parents=True)
            status = {
                "name": "reattach-test",
                "state": "running",
                "repo_key": "repo-key",
                "repo_root": "/repo",
                "started_at": meight.now_iso(),
                "updated_at": meight.now_iso(),
            }
            (worker_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
            output = io.StringIO()
            with (
                patch.object(meight, "ensure_daemon", return_value=True),
                patch.object(meight, "repo_home_for_cli", return_value=repo_home),
                patch.object(meight, "query_runtime_status", return_value={
                    "ok": True, "known": True, "has_live_turn": True,
                }) as runtime,
                patch.object(meight, "start_request") as start,
                patch.object(meight, "wait_for_worker", return_value=1) as wait,
                contextlib.redirect_stdout(output),
            ):
                code = meight.cmd_dispatch(self._args("reattach-test"), home)

            self.assertEqual(code, 1)
            start.assert_not_called()
            runtime.assert_called_once()
            wait.assert_called_once_with(home, repo_home, "reattach-test", 12.0, 300.0,
                                         narrate=False)
            self.assertIn("reattached to worker 'reattach-test' (state=running)", output.getvalue())

    def test_dispatch_keeps_terminal_row_on_new_start_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo_home = Path(tmp) / "repo"
            worker_dir = repo_home / "workers" / "terminal-test"
            worker_dir.mkdir(parents=True)
            (worker_dir / "status.json").write_text(json.dumps({
                "name": "terminal-test",
                "state": "completed",
                "started_at": meight.now_iso(),
                "updated_at": meight.now_iso(),
            }), encoding="utf-8")
            response = {
                "ok": True, "thread_id": "new-thread", "mode": "worker",
                "protocol_epoch": meight.PROTOCOL_EPOCH,
            }
            output = io.StringIO()
            with (
                patch.object(meight, "ensure_daemon", return_value=True),
                patch.object(meight, "repo_home_for_cli", return_value=repo_home),
                patch.object(meight, "start_request", return_value=response) as start,
                patch.object(meight, "wait_for_worker", return_value=1),
                contextlib.redirect_stdout(output),
            ):
                code = meight.cmd_dispatch(self._args("terminal-test"), home)

            self.assertEqual(code, 1)
            start.assert_called_once()
            self.assertIn("started worker 'terminal-test'", output.getvalue())


class WaitClassificationTests(unittest.TestCase):
    def test_question_wait_exits_3_immediately(self):
        st = {"state": "needs_input", "needs_input_source": "question",
              "updated_at": meight.now_iso()}
        self.assertEqual(meight.classify_wait_state(st), 3)

    def test_fresh_tool_wait_keeps_polling_but_stale_tool_wait_exits_3(self):
        fresh = {"state": "needs_input", "needs_input_source": "tool",
                 "updated_at": meight.now_iso()}
        self.assertIsNone(meight.classify_wait_state(fresh))
        stale_at = (meight.now_kst()
                    - timedelta(seconds=meight.TOOL_WAIT_GRACE_SEC + 1)).isoformat(timespec="seconds")
        stale = {"state": "needs_input", "needs_input_source": "tool", "updated_at": stale_at}
        self.assertEqual(meight.classify_wait_state(stale), 3)
        unparsable = {"state": "needs_input", "needs_input_source": "tool", "updated_at": None}
        self.assertEqual(meight.classify_wait_state(unparsable), 3)


class WaitNarrationTests(unittest.TestCase):
    def _repo_home_with_status(self, tmp):
        repo_home = Path(tmp)
        wdir = repo_home / "workers" / "narrate-1"
        wdir.mkdir(parents=True)
        (wdir / "status.json").write_text(json.dumps({
            "name": "narrate-1", "state": "completed",
            "plan": ["[done] read code", "[active] write fix"],
            "started_at": meight.now_iso(), "updated_at": meight.now_iso(),
        }), encoding="utf-8")
        return repo_home

    def test_plan_step_narration_is_opt_in(self):
        for narrate, expect in ((False, False), (True, True)):
            with self.subTest(narrate=narrate), tempfile.TemporaryDirectory() as tmp:
                repo_home = self._repo_home_with_status(tmp)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = meight.wait_for_worker(
                        Path(tmp), repo_home, "narrate-1", timeout=5, narrate=narrate)
                self.assertEqual(code, 0)
                self.assertEqual("▶" in output.getvalue(), expect)


class EffortTests(unittest.TestCase):
    def test_ultra_and_max_parse_and_reach_start_request(self):
        parser = meight.build_parser()
        for effort in ("ultra", "max"):
            args = parser.parse_args([
                "dispatch", f"effort-{effort}", "--mode", "worker",
                "--brief", "Say OK", "--effort", effort,
            ])
            responses = ({"ok": True, "capabilities": [meight.PROTOCOL_EPOCH]},
                         {"ok": True, "mode": "worker",
                          "protocol_epoch": meight.PROTOCOL_EPOCH})
            with patch.object(meight, "send_request", side_effect=responses) as send:
                meight.start_request(args, Path("/tmp/meight-test"))
            self.assertEqual(send.call_args.args[1]["effort"], effort)

    def _stub_sdk_params(self):
        """Stand in for the SDK's generated TurnStartParams with a closed enum."""
        class Field:
            annotation = str

        class TurnStartParams:
            model_fields = {"effort": Field()}
            rebuilds = 0

            @classmethod
            def model_rebuild(cls, force=False):
                cls.rebuilds += 1

        module = types.ModuleType("openai_codex.generated.v2_all")
        module.TurnStartParams = TurnStartParams
        parents = {
            "openai_codex": types.ModuleType("openai_codex"),
            "openai_codex.generated": types.ModuleType("openai_codex.generated"),
            "openai_codex.generated.v2_all": module,
        }
        return TurnStartParams, patch.dict(sys.modules, parents)

    def test_effort_field_widens_once_for_every_server_side_tier(self):
        params, patched = self._stub_sdk_params()
        with patched, patch.object(meight, "_sdk_effort_field_relaxed", False):
            meight.relax_sdk_effort_field()
            self.assertEqual(params.model_fields["effort"].annotation, str | None)
            self.assertEqual(params.rebuilds, 1)

            # Widening is by value, not by an allowlist, so a tier the harness
            # has never heard of needs no code change — and repeat turns must
            # not rebuild the model again.
            meight.relax_sdk_effort_field()
            self.assertEqual(params.rebuilds, 1)

    def test_already_widened_field_is_left_alone(self):
        params, patched = self._stub_sdk_params()
        params.model_fields["effort"].annotation = str | None
        with patched, patch.object(meight, "_sdk_effort_field_relaxed", False):
            meight.relax_sdk_effort_field()
        self.assertEqual(params.rebuilds, 0)

    @unittest.skipUnless(
        importlib.util.find_spec("openai_codex"), "openai-codex SDK not installed"
    )
    def test_installed_sdk_accepts_dynamic_efforts_after_widening(self):
        from openai_codex.generated.v2_all import TurnStartParams

        meight.relax_sdk_effort_field()
        for effort in ("ultra", "max", "unknown-future-tier"):
            params = TurnStartParams(thread_id="thread", input=[], effort=effort)
            self.assertEqual(params.model_dump(mode="json")["effort"], effort)

    @unittest.skipUnless(
        importlib.util.find_spec("openai_codex"), "openai-codex SDK not installed"
    )
    def test_installed_sdk_accepts_nested_agent_thread_history(self):
        from openai_codex.generated.v2_all import ThreadItem

        item = ThreadItem.model_validate({
            "type": "subAgentActivity",
            "id": "activity",
            "agentPath": "reviewer",
            "agentThreadId": "review-thread",
            "kind": "started",
        })
        self.assertEqual(item.root.type, "subAgentActivity")


class TerminalErrorTests(unittest.TestCase):
    @staticmethod
    def _capacity_handle():
        return types.SimpleNamespace(stream=lambda: iter((
            types.SimpleNamespace(
                method="error",
                payload={
                    "error": {
                        "message": "Selected model is at capacity. Please try a different model."
                    },
                    "will_retry": False,
                },
            ),
            types.SimpleNamespace(
                method="turn/completed",
                payload={"turn": {"status": "failed"}},
            ),
        )))

    @staticmethod
    def _completed_handle(message="OK"):
        return types.SimpleNamespace(stream=lambda: iter((
            types.SimpleNamespace(
                method="item/completed",
                payload={"item": {"type": "agentMessage", "text": message}},
            ),
            types.SimpleNamespace(
                method="turn/completed",
                payload={"turn": {"status": "completed"}},
            ),
        )))

    def test_error_without_http_status_stays_null(self):
        detail = meight.failure_detail({
            "error": {"message": "Selected model is at capacity. Please try a different model."},
        })

        self.assertEqual(detail, {
            "message": "Selected model is at capacity. Please try a different model.",
            "status": None,
            "type": None,
        })
        self.assertEqual(
            meight.format_failure_detail(detail),
            "Selected model is at capacity. Please try a different model.",
        )

    def test_non_retry_error_is_visible_and_late_completion_does_not_duplicate_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            worker = meight.Worker(
                "error-test", repo_home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "medium",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")

            provider_message = "The 'sol' model is not supported when using Codex with a ChatGPT account."
            worker._handle_event("error", {
                "error": {
                    "message": json.dumps({
                        "type": "error",
                        "status": 400,
                        "error": {
                            "type": "invalid_request_error",
                            "message": provider_message,
                        },
                    }),
                },
                "will_retry": False,
            })
            worker._handle_event("turn/completed", {"turn": {"status": "completed"}})

            status = json.loads((worker.dir / "status.json").read_text(encoding="utf-8"))
            result = (worker.dir / "result.md").read_text(encoding="utf-8")
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error_detail"], {
                "message": provider_message,
                "status": 400,
                "type": "invalid_request_error",
            })
            self.assertIn(f"HTTP 400 invalid_request_error: {provider_message}", result)
            self.assertNotIn("(no agent message)", result)
            self.assertEqual(result.count(provider_message), 1)

    def test_runtime_detach_logs_terminal_state_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            worker = meight.Worker(
                "error-log-test", home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "medium",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")
            worker.status["state"] = "failed"
            worker.status["error_detail"] = {
                "message": "Selected model is at capacity. Please try a different model.",
                "status": None,
                "type": None,
            }
            worker.thread = object()

            worker.detach_runtime_refs_if_idle(
                meight.Daemon(home), worker.generation, "stream ended"
            )

            log = (home / "daemon.log").read_text(encoding="utf-8")
            self.assertIn(
                "state=failed error='Selected model is at capacity. "
                "Please try a different model.' reason=stream ended",
                log,
            )

    def test_capacity_failure_retries_same_thread_then_completes(self):
        class RetryThread:
            def __init__(self, handles):
                self.handles = list(handles)
                self.calls = []

            def turn(self, turn_input, **kwargs):
                self.calls.append((turn_input, kwargs))
                return self.handles.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            worker = meight.Worker(
                "capacity-retry", home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "medium", "default",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")
            worker.generation = 1
            thread = RetryThread([self._completed_handle()])
            worker.thread = thread

            with patch.object(meight, "capacity_retry_delay", return_value=0):
                worker.consume_stream(
                    meight.Daemon(home), worker.generation, self._capacity_handle()
                )

            result = (worker.dir / "result.md").read_text(encoding="utf-8")
            self.assertEqual(worker.status["state"], "completed")
            self.assertEqual(worker.status["capacity_retries"], 1)
            self.assertEqual(result.strip(), "OK")
            self.assertEqual(len(thread.calls), 1)
            self.assertEqual(thread.calls[0][0], meight.CAPACITY_RETRY_PROMPT)
            self.assertEqual(thread.calls[0][1]["model"], "gpt-5.6-sol")
            self.assertEqual(thread.calls[0][1]["effort"], "medium")
            self.assertEqual(thread.calls[0][1]["service_tier"], "default")
            self.assertEqual(worker.status["capacity_retry"]["state"], "completed")

    def test_capacity_failure_stops_when_time_budget_is_exhausted(self):
        class RetryThread:
            def __init__(self, handles):
                self.handles = list(handles)
                self.calls = 0

            def turn(self, turn_input, **kwargs):
                self.calls += 1
                return self.handles.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            worker = meight.Worker(
                "capacity-exhausted", home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "high", "default",
                capacity_retry_budget_sec=0,
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")
            worker.generation = 1
            thread = RetryThread([])
            worker.thread = thread

            with patch.object(meight, "capacity_retry_delay", return_value=0):
                worker.consume_stream(
                    meight.Daemon(home), worker.generation, self._capacity_handle()
                )

            result = (worker.dir / "result.md").read_text(encoding="utf-8")
            events = (worker.dir / "events.log").read_text(encoding="utf-8")
            self.assertEqual(worker.status["state"], "failed")
            self.assertEqual(worker.status["capacity_retries"], 0)
            self.assertEqual(thread.calls, 0)
            self.assertIn("Selected model is at capacity", result)
            self.assertIn("[capacity/exhausted] capacity retries stopped after 0 retries", events)
            self.assertIn("## Capacity retry", result)

    def test_capacity_retry_uses_capped_exponential_schedule_and_timeout_budget(self):
        self.assertEqual(meight.capacity_retry_delay(1), 5)
        self.assertEqual(meight.capacity_retry_delay(2), 10)
        self.assertEqual(meight.capacity_retry_delay(5), 60)
        self.assertEqual(meight.capacity_retry_delay(50), 60)
        self.assertEqual(
            meight.capacity_retry_budget_for_timeout(120),
            120,
        )
        self.assertEqual(
            meight.capacity_retry_budget_for_timeout(1800),
            meight.CAPACITY_RETRY_BUDGET_SEC,
        )

    def test_capacity_retry_status_surfaces_countdown_for_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            worker = meight.Worker(
                "capacity-status", home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "medium", "default",
                capacity_retry_budget_sec=120,
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")
            worker._capacity_retry_started_monotonic = 10
            worker._capacity_retry_deadline = 20
            worker.status["capacity_retries"] = 2
            worker.status["capacity_retry"] = {
                "state": "waiting", "attempt": 3, "budget_sec": 120,
            }
            with patch.object(meight.time, "monotonic", return_value=15):
                worker.write_status(force=True)
            status = json.loads((worker.dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["capacity_retry"]["attempt"], 3)
            self.assertEqual(status["capacity_retry"]["elapsed_sec"], 5.0)
            self.assertEqual(status["capacity_retry"]["next_retry_in_sec"], 5.0)
            self.assertIn("capacity retry #3 in 5s", status["current_item"])


class QuestionRoutingTests(unittest.TestCase):
    def test_question_metadata_routes_user_entry_before_dispatcher_fallback(self):
        cases = (
            (
                "dispatcher-first-user-later",
                "TARGET: dispatcher\nKIND: technical\n"
                "TARGET: user\nKIND: scope",
                "user",
                "scope",
            ),
            (
                "all-dispatcher",
                "TARGET: dispatcher\nKIND: technical",
                "dispatcher",
                "technical",
            ),
            (
                "single-user",
                "TARGET: user\nKIND: acceptance",
                "user",
                "acceptance",
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            for name, question, expected_target, expected_kind in cases:
                with self.subTest(name=name):
                    worker = meight.Worker(
                        name, repo_home, "/repo", "repo-key", "/repo",
                        "workspace_write", "gpt-5.6-sol", "medium",
                        mode="worker",
                    )
                    worker.dir.mkdir(parents=True)
                    worker.init_status(thread_id="thread-1")
                    worker._last_agent_msg = "The current implementation needs a decision.\n\nQUESTION:\n" + question

                    worker._on_turn_completed({"status": "completed"})

                    self.assertEqual(worker.status["state"], "needs_input")
                    self.assertEqual(worker.status["needs_input_source"], "question")
                    self.assertEqual(worker.status["needs_input_target"], expected_target)
                    self.assertEqual(worker.status["needs_input_kind"], expected_kind)


class DaemonHardeningTests(unittest.TestCase):
    def _context(self, home: Path, source: Path) -> dict:
        return meight.repo_context(home, source)

    def test_worker_name_cli_and_daemon_boundaries_reject_path_syntax(self):
        parser = meight.build_parser()
        for name in ("../escape", ".hidden", "a/b", "a\\b", "", "x" * 129):
            with self.subTest(name=name), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["status", name])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = meight.Daemon(Path(tmp))
            response = daemon._dispatch({"cmd": "runtime_status", "name": "../escape"})
            self.assertFalse(response["ok"])
            self.assertIn("invalid worker name", response["error"])

    def test_repo_context_is_daemon_derived_and_forged_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "state"
            source = Path(tmp) / "repo"
            source.mkdir()
            context = self._context(home, source)
            daemon = meight.Daemon(home)
            self.assertEqual(daemon._repo_from_req({**context, "cwd": str(source)}), (
                context["repo_key"], context["repo_root"], Path(context["repo_home"]),
            ))
            for field, value in (
                ("repo_key", "forged"),
                ("repo_home", str(Path(tmp) / "outside")),
                ("repo_root", str(Path(tmp) / "other")),
            ):
                forged = {**context, "cwd": str(source), field: value}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    daemon._repo_from_req(forged)

    def test_private_directories_and_symlink_worker_state_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "state"
            source = base / "repo"
            source.mkdir()
            context = self._context(home, source)
            repo_home = Path(context["repo_home"])
            worker_dir = meight.ensure_worker_state_dir(home, repo_home, "safe-worker")
            for path in (home, home / "repos", repo_home, repo_home / "workers", worker_dir):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

            outside = base / "outside"
            outside.mkdir()
            linked = repo_home / "workers" / "linked-worker"
            linked.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                meight.ensure_worker_state_dir(home, repo_home, "linked-worker")
            self.assertTrue(outside.is_dir())

    def test_socket_request_framing_rejects_oversize_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = meight.Daemon(Path(tmp))
            server, client = meight.socket.socketpair()
            thread = threading.Thread(target=daemon._handle_conn, args=(server,))
            thread.start()
            client.sendall(b'{"cmd":"ping","padding":"' + b"x" * meight.MAX_SOCKET_REQUEST_BYTES + b'"}\n')
            response = b""
            while b"\n" not in response:
                response += client.recv(65536)
            thread.join(timeout=2)
            client.close()
            payload = json.loads(response.split(b"\n", 1)[0])
            self.assertFalse(payload["ok"])
            self.assertIn("request exceeds", payload["error"])

    def test_terminal_at_is_set_once_per_terminal_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = meight.Worker(
                "terminal-time", Path(tmp), "/repo", "repo-key", "/repo",
                "workspace_write", None, "medium",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status("thread")
            worker.status["state"] = "completed"
            with patch.object(meight, "now_iso", return_value="2026-01-01T00:00:00+09:00"):
                worker.write_status(force=True)
            terminal_at = worker.status["terminal_at"]
            with patch.object(meight, "now_iso", return_value="2026-01-02T00:00:00+09:00"):
                worker.write_status(force=True)
            self.assertEqual(worker.status["terminal_at"], terminal_at)
            worker.reset_for_follow("again")
            self.assertIsNone(worker.status["terminal_at"])

    def test_startup_reconciliation_marks_only_orphaned_active_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            workers = home / "repos" / "repo-key" / "workers"
            workers.mkdir(parents=True)
            for state in ("starting", "running", "needs_input", "completed"):
                worker_dir = workers / state
                worker_dir.mkdir()
                (worker_dir / "status.json").write_text(json.dumps({
                    "name": state, "state": state, "daemon_pid": 123,
                    "updated_at": "2026-01-01T00:00:00+09:00",
                }), encoding="utf-8")
            question_dir = workers / "dormant-question"
            question_dir.mkdir()
            (question_dir / "status.json").write_text(json.dumps({
                "name": "dormant-question",
                "state": "needs_input",
                "needs_input_source": "question",
                "thread_id": "thread-question",
                "daemon_pid": 123,
                "updated_at": "2026-01-01T00:00:00+09:00",
            }), encoding="utf-8")
            daemon = meight.Daemon(home)
            with patch.object(meight, "read_bounded_json", wraps=meight.read_bounded_json) as read:
                daemon._reconcile_startup_orphans()
            self.assertEqual(read.call_count, 5)
            for state in ("starting", "running", "needs_input"):
                row = json.loads((workers / state / "status.json").read_text())
                self.assertEqual(row["state"], "failed")
                self.assertIn(f"orphaned {state}", row["runtime_lost_detail"])
                self.assertIsNotNone(row["terminal_at"])
                self.assertIn("[runtime/lost]", (workers / state / "events.log").read_text())
            dormant = json.loads((question_dir / "status.json").read_text())
            self.assertEqual(dormant["state"], "needs_input")
            self.assertEqual(dormant["thread_id"], "thread-question")
            self.assertFalse((question_dir / "events.log").exists())
            completed = json.loads((workers / "completed" / "status.json").read_text())
            self.assertEqual(completed["state"], "completed")
            self.assertNotIn("runtime_lost_detail", completed)

    def _write_retention_row(self, workers: Path, name: str, state: str,
                             timestamp: str | None, *, legacy: bool = False) -> Path:
        worker_dir = workers / name
        worker_dir.mkdir()
        row = {"name": name, "state": state}
        if legacy:
            row["updated_at"] = timestamp
        else:
            row["terminal_at"] = timestamp
            row["updated_at"] = "2025-01-01T00:00:00+09:00"
        (worker_dir / "status.json").write_text(json.dumps(row), encoding="utf-8")
        return worker_dir

    def test_retention_threshold_legacy_invalid_active_registered_and_race_safe_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            workers = home / "repos" / "repo-key" / "workers"
            workers.mkdir(parents=True)
            now = meight.now_kst()
            expired = self._write_retention_row(
                workers, "expired", "completed", (now - timedelta(seconds=100)).isoformat()
            )
            fresh = self._write_retention_row(
                workers, "fresh", "failed", (now - timedelta(seconds=99)).isoformat()
            )
            legacy = self._write_retention_row(
                workers, "legacy", "interrupted", (now - timedelta(seconds=101)).isoformat(), legacy=True
            )
            invalid = self._write_retention_row(workers, "invalid", "completed", "not-a-time")
            active = self._write_retention_row(
                workers, "active", "running", (now - timedelta(seconds=1000)).isoformat()
            )
            registered = self._write_retention_row(
                workers, "registered", "completed", (now - timedelta(seconds=1000)).isoformat()
            )
            daemon = meight.Daemon(home)
            daemon.session_retention_sec = 100
            daemon.workers[meight.registry_key("repo-key", "registered")] = object()
            real_rmtree = meight.shutil.rmtree
            deleted = []

            def checked_delete(path):
                self.assertFalse(daemon.reg_lock.locked())
                self.assertTrue(path.name.startswith(meight.PRUNE_TOMBSTONE_PREFIX))
                deleted.append(path)
                real_rmtree(path)

            with patch.object(meight.shutil, "rmtree", side_effect=checked_delete):
                daemon._prune_expired_sessions(now)
            self.assertFalse(expired.exists())
            self.assertFalse(legacy.exists())
            self.assertEqual(len(deleted), 2)
            for path in (fresh, invalid, active, registered):
                self.assertTrue(path.exists())

    def test_retention_disable_symlink_skip_and_tombstone_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            workers = home / "repos" / "repo-key" / "workers"
            workers.mkdir(parents=True)
            now = meight.now_kst()
            disabled = self._write_retention_row(
                workers, "disabled", "completed", (now - timedelta(days=10)).isoformat()
            )
            tombstone = workers / f"{meight.PRUNE_TOMBSTONE_PREFIX}old-1"
            tombstone.mkdir()
            (tombstone / "status.json").write_text(json.dumps({
                "state": "completed",
                "terminal_at": (now - timedelta(days=10)).isoformat(),
            }), encoding="utf-8")
            legacy_active = workers / f"{meight.PRUNE_TOMBSTONE_PREFIX}legacy-active"
            legacy_active.mkdir()
            (legacy_active / "status.json").write_text(json.dumps({
                "state": "needs_input",
                "terminal_at": (now - timedelta(days=10)).isoformat(),
            }), encoding="utf-8")
            legacy_fresh = workers / f"{meight.PRUNE_TOMBSTONE_PREFIX}legacy-fresh"
            legacy_fresh.mkdir()
            (legacy_fresh / "status.json").write_text(json.dumps({
                "state": "completed",
                "terminal_at": now.isoformat(),
            }), encoding="utf-8")
            outside = Path(tmp) / "outside"
            outside.mkdir()
            symlink = workers / "linked"
            symlink.symlink_to(outside, target_is_directory=True)
            daemon = meight.Daemon(home)
            daemon.session_retention_sec = 0
            daemon._prune_expired_sessions(now)
            self.assertTrue(disabled.exists())
            self.assertTrue(tombstone.exists())
            daemon.session_retention_sec = 1
            daemon._prune_expired_sessions(now)
            self.assertFalse(tombstone.exists())
            self.assertTrue(legacy_active.exists())
            self.assertTrue(legacy_fresh.exists())
            self.assertTrue(symlink.is_symlink())
            self.assertTrue(outside.exists())

    def test_retention_skips_missing_timestamps_and_symlink_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            workers = home / "repos" / "repo-key" / "workers"
            workers.mkdir(parents=True)
            missing = workers / "missing"
            missing.mkdir()
            (missing / "status.json").write_text(
                json.dumps({"name": "missing", "state": "completed"}), encoding="utf-8"
            )
            linked_status = workers / "linked-status"
            linked_status.mkdir()
            target = Path(tmp) / "external-status.json"
            target.write_text(json.dumps({
                "state": "completed", "terminal_at": "2020-01-01T00:00:00+09:00",
            }), encoding="utf-8")
            (linked_status / "status.json").symlink_to(target)
            daemon = meight.Daemon(home)
            daemon.session_retention_sec = 1
            daemon._prune_expired_sessions(meight.now_kst())
            self.assertTrue(missing.exists())
            self.assertTrue(linked_status.exists())
            self.assertTrue(target.exists())

    def test_retention_scheduler_is_off_thread_and_hourly_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = meight.Daemon(Path(tmp))
            daemon.session_retention_sec = 1
            entered = threading.Event()
            release = threading.Event()
            caller_ident = threading.get_ident()
            worker_idents = []

            def cleanup():
                worker_idents.append(threading.get_ident())
                entered.set()
                release.wait(timeout=2)

            with patch.object(daemon, "_prune_expired_sessions", side_effect=cleanup):
                self.assertTrue(daemon._schedule_retention_cleanup(now=10_000))
                self.assertTrue(entered.wait(timeout=1))
                self.assertFalse(daemon._schedule_retention_cleanup(now=20_000))
                release.set()
                daemon.retention_thread.join(timeout=2)
                self.assertFalse(daemon._schedule_retention_cleanup(
                    now=10_000 + meight.RETENTION_CLEANUP_INTERVAL_SEC - 1
                ))
                self.assertTrue(daemon._schedule_retention_cleanup(
                    now=10_000 + meight.RETENTION_CLEANUP_INTERVAL_SEC
                ))
                daemon.retention_thread.join(timeout=2)
            self.assertTrue(all(ident != caller_ident for ident in worker_idents))

    class _FailingServer:
        def __init__(self, daemon, intentional):
            self.daemon = daemon
            self.intentional = intentional
            self.bound_path = None
            self.socket_mode = None

        def bind(self, path):
            self.bound_path = Path(path)
            self.bound_path.touch()

        def listen(self, backlog):
            self.socket_mode = stat.S_IMODE(os.stat(self.bound_path).st_mode)

        def settimeout(self, timeout):
            return None

        def accept(self):
            if self.intentional:
                self.daemon.shutting_down.set()
            raise OSError("accept failed")

        def close(self):
            return None

    class _SocketLossServer(_FailingServer):
        def __init__(self, daemon, replace):
            super().__init__(daemon, intentional=False)
            self.replace = replace

        def accept(self):
            self.bound_path.unlink()
            if self.replace:
                self.bound_path.touch()
            raise meight.socket.timeout("poll")

    def test_intentional_and_unexpected_accept_failures_have_distinct_exit_codes(self):
        for intentional, expected in ((True, 0), (False, 1)):
            with self.subTest(intentional=intentional), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                daemon = meight.Daemon(home)
                server = self._FailingServer(daemon, intentional)
                with (
                    patch.object(meight.socket, "socket", return_value=server),
                    patch.object(meight.signal, "signal"),
                    patch.object(meight, "probe_daemon_socket", return_value=False),
                    patch.object(daemon, "_schedule_retention_cleanup", return_value=False),
                ):
                    code = daemon.run()
                self.assertEqual(code, expected)
                self.assertEqual(stat.S_IMODE(os.stat(home).st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.stat(home / "repos").st_mode), 0o700)
                self.assertEqual(server.socket_mode, 0o600)

    def test_deleted_or_replaced_socket_path_exits_nonzero_for_launchd_restart(self):
        for replace in (False, True):
            with self.subTest(replace=replace), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                daemon = meight.Daemon(home)
                server = self._SocketLossServer(daemon, replace)
                with (
                    patch.object(meight.socket, "socket", return_value=server),
                    patch.object(meight.signal, "signal"),
                    patch.object(meight, "probe_daemon_socket", return_value=False),
                    patch.object(daemon, "_schedule_retention_cleanup", return_value=False),
                ):
                    self.assertEqual(daemon.run(), 1)
                self.assertIn("socket pathname ownership lost", (home / "daemon.log").read_text())

    def test_startup_reconciliation_requires_singleton_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = meight.Daemon(Path(tmp))
            reconcile = Mock()
            with (
                patch.object(meight.fcntl, "flock", side_effect=OSError("held")),
                patch.object(daemon, "_reconcile_startup_orphans", reconcile),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(daemon.run(), 1)
            reconcile.assert_not_called()


class LaunchdHardeningTests(unittest.TestCase):
    def test_launchd_payload_is_crash_only_and_has_no_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = meight.launchd_payload(Path(tmp))
            self.assertTrue(payload["RunAtLoad"])
            self.assertEqual(payload["KeepAlive"], {"SuccessfulExit": False})
            self.assertNotIn("Umask", payload)

    def test_auto_start_routes_to_loaded_launchd_without_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            completed = types.SimpleNamespace(returncode=0)
            with (
                patch.object(meight, "probe_daemon_socket", side_effect=[False, True]),
                patch.object(meight, "launchd_service_loaded", return_value=True),
                patch.object(meight.subprocess, "run", return_value=completed) as run,
                patch.object(meight.subprocess, "Popen") as popen,
            ):
                self.assertTrue(meight.ensure_daemon(home))
            command = run.call_args.args[0]
            self.assertEqual(command[:2], ["launchctl", "kickstart"])
            self.assertNotIn("-k", command)
            popen.assert_not_called()

    def test_auto_start_detaches_only_when_launchd_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with (
                patch.object(meight, "probe_daemon_socket", side_effect=[False, True]),
                patch.object(meight, "launchd_service_loaded", return_value=False),
                patch.object(meight.subprocess, "Popen") as popen,
            ):
                self.assertTrue(meight.ensure_daemon(home))
            popen.assert_called_once()

    def test_unknown_launchd_ownership_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "agent.plist"
            with (
                patch.object(meight, "probe_daemon_socket", return_value=False),
                patch.object(meight, "launchd_service_loaded", return_value=None),
                patch.object(meight.subprocess, "Popen") as popen,
            ):
                self.assertFalse(meight.ensure_daemon(home))
            popen.assert_not_called()

            with (
                patch.object(meight, "launchd_service_loaded", return_value=None),
                patch.object(meight, "drain_existing_daemon") as drain,
                patch.object(meight.subprocess, "run") as run,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = meight.load_launchagent_with_ownership_transfer(home, path, {}, timeout=1)
            self.assertEqual(code, 1)
            self.assertFalse(path.exists())
            drain.assert_not_called()
            run.assert_not_called()

    def test_launchctl_only_classifies_explicit_service_not_found_as_unloaded(self):
        cases = (
            (types.SimpleNamespace(returncode=0, stderr=""), True),
            (
                types.SimpleNamespace(
                    returncode=113,
                    stderr='Could not find service "com.keepitmello.meight" in domain',
                ),
                False,
            ),
            (types.SimpleNamespace(returncode=113, stderr="Bad request"), None),
            (types.SimpleNamespace(returncode=1, stderr="Operation not permitted"), None),
        )
        for result, expected in cases:
            with self.subTest(returncode=result.returncode, stderr=result.stderr), patch.object(
                meight.subprocess, "run", return_value=result
            ):
                self.assertIs(meight.launchd_service_loaded(), expected)

    def test_launchd_running_pid_requires_a_loaded_job_pid_field(self):
        cases = (
            (types.SimpleNamespace(returncode=0, stdout="\tpid = 4242\n"), 4242),
            (types.SimpleNamespace(returncode=0, stdout="\tstate = exited\n"), None),
            (types.SimpleNamespace(returncode=1, stdout="\tpid = 4242\n"), None),
        )
        for result, expected in cases:
            with self.subTest(result=result), patch.object(
                meight.subprocess, "run", return_value=result
            ):
                self.assertEqual(meight.launchd_running_pid(), expected)

    def test_drain_acknowledgement_precedes_wait_and_active_refusal_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            events = []

            def shutdown(*args, **kwargs):
                events.append("ack")
                return {"ok": True}

            def depart(*args, **kwargs):
                events.append("wait")
                return True

            with (
                patch.object(meight, "daemon_ping", return_value={"ok": True, "pid": 42}),
                patch.object(meight, "send_request", side_effect=shutdown),
                patch.object(meight, "wait_for_daemon_departure", side_effect=depart),
            ):
                self.assertEqual(meight.drain_existing_daemon(home, 1), (42, None))
            self.assertEqual(events, ["ack", "wait"])

            with (
                patch.object(meight, "daemon_ping", return_value={"ok": True, "pid": 42}),
                patch.object(meight, "send_request", return_value={"ok": False, "error": "active workers"}),
                patch.object(meight, "wait_for_daemon_departure") as wait,
            ):
                self.assertEqual(meight.drain_existing_daemon(home, 1), (42, "active workers"))
            wait.assert_not_called()

    def test_drain_allows_dead_owner_stale_socket_but_refuses_live_unhealthy_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "meight.sock").touch()
            with patch.object(meight, "daemon_ping", return_value=None):
                self.assertEqual(meight.drain_existing_daemon(home, 1), (None, None))

            (home / "daemon.pid").write_text("4242\n")
            with (
                patch.object(meight, "daemon_ping", return_value=None),
                patch.object(meight, "pid_alive", return_value=False),
            ):
                self.assertEqual(meight.drain_existing_daemon(home, 1), (4242, None))
            with (
                patch.object(meight, "daemon_ping", return_value=None),
                patch.object(meight, "pid_alive", return_value=True),
            ):
                pid, error = meight.drain_existing_daemon(home, 1)
            self.assertEqual(pid, 4242)
            self.assertIn("not healthy enough", error)

    def test_drain_refuses_unhealthy_owner_when_singleton_lock_is_held_or_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "meight.sock").touch()
            for lock_state, expected in ((False, "singleton lock is held"), (None, "could not establish")):
                with (
                    self.subTest(lock_state=lock_state),
                    patch.object(meight, "daemon_ping", return_value=None),
                    patch.object(meight, "read_daemon_pid", return_value=None),
                    patch.object(meight, "daemon_singleton_lock_available", return_value=lock_state),
                ):
                    pid, error = meight.drain_existing_daemon(home, 1)
                self.assertIsNone(pid)
                self.assertIn(expected, error)

    def test_drain_timeout_and_load_refusal_never_bootout_or_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "agent.plist"
            with (
                patch.object(meight, "daemon_ping", return_value={"ok": True, "pid": 42}),
                patch.object(meight, "send_request", return_value={"ok": True}),
                patch.object(meight, "wait_for_daemon_departure", return_value=False),
            ):
                pid, error = meight.drain_existing_daemon(home, 0.01)
            self.assertEqual(pid, 42)
            self.assertIn("timed out", error)

            with (
                patch.object(meight, "launchd_service_loaded", return_value=True),
                patch.object(meight, "drain_existing_daemon", return_value=(42, "active workers")),
                patch.object(meight.subprocess, "run") as run,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = meight.load_launchagent_with_ownership_transfer(home, path, {}, timeout=1)
            self.assertEqual(code, 1)
            self.assertFalse(path.exists())
            run.assert_not_called()

    def test_first_load_and_reload_use_bounded_ordered_ownership_transfer(self):
        completed = types.SimpleNamespace(returncode=0)
        for loaded, expected_commands in ((False, ["bootstrap"]), (True, ["bootout", "bootstrap"])):
            with self.subTest(loaded=loaded), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                path = home / "agent.plist"
                events = []
                commands = []

                def drain(*args):
                    events.append("drain")
                    return 111, None

                def run(command, **kwargs):
                    events.append(command[1])
                    commands.append(command)
                    self.assertEqual(kwargs.get("timeout"), 2)
                    return completed

                with (
                    patch.object(meight, "launchd_service_loaded", return_value=loaded),
                    patch.object(meight, "drain_existing_daemon", side_effect=drain),
                    patch.object(meight.subprocess, "run", side_effect=run),
                    patch.object(meight, "wait_for_fresh_daemon", return_value={"pid": 222}),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    code = meight.load_launchagent_with_ownership_transfer(
                        home, path, {"Label": meight.LAUNCHD_LABEL}, timeout=2
                    )
                self.assertEqual(code, 0)
                self.assertEqual(events, ["drain", *expected_commands])
                if loaded:
                    self.assertEqual(commands[0], [
                        "launchctl", "bootout", "--wait",
                        f"{meight.launchctl_domain()}/{meight.LAUNCHD_LABEL}",
                    ])
                self.assertTrue(path.is_file())

    def test_bootout_timeout_stops_before_plist_write_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "agent.plist"
            with (
                patch.object(meight, "launchd_service_loaded", return_value=True),
                patch.object(meight, "drain_existing_daemon", return_value=(111, None)),
                patch.object(
                    meight.subprocess, "run",
                    side_effect=meight.subprocess.TimeoutExpired(["launchctl", "bootout"], 1),
                ) as run,
                patch.object(meight, "wait_for_fresh_daemon") as fresh,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = meight.load_launchagent_with_ownership_transfer(home, path, {}, timeout=1)
            self.assertEqual(code, 1)
            self.assertFalse(path.exists())
            self.assertEqual(run.call_count, 1)
            fresh.assert_not_called()

    def test_fresh_daemon_wait_rejects_old_pid_until_new_owner_responds(self):
        responses = [
            {"ok": True, "pid": 111},
            {"ok": True, "pid": 111},
            {"ok": True, "pid": 222},
        ]
        with (
            patch.object(meight, "daemon_ping", side_effect=responses),
            patch.object(meight, "socket_path_identity", return_value=(2, 2)),
            patch.object(meight, "launchd_running_pid", side_effect=[222, 222, 222]),
            patch.object(meight.time, "sleep"),
        ):
            response = meight.wait_for_fresh_daemon(Path("/tmp/unused"), 111, (1, 1), 1)
        self.assertEqual(response["pid"], 222)

    def test_fresh_daemon_wait_rejects_unchanged_socket_when_old_pid_is_unknown(self):
        with (
            patch.object(meight, "daemon_ping", return_value={"ok": True, "pid": 222}),
            patch.object(meight, "socket_path_identity", side_effect=[(1, 1), (2, 2)]),
            patch.object(meight, "launchd_running_pid", return_value=222),
            patch.object(meight.time, "sleep"),
        ):
            response = meight.wait_for_fresh_daemon(Path("/tmp/unused"), None, (1, 1), 1)
        self.assertEqual(response["pid"], 222)

    def test_fresh_daemon_wait_rejects_concurrent_detached_responder(self):
        responses = (
            {"ok": True, "pid": 222},  # detached contender owns the socket first
            {"ok": True, "pid": 333},  # launchd-owned daemon wins after retry
        )
        with (
            patch.object(meight, "daemon_ping", side_effect=responses),
            patch.object(meight, "socket_path_identity", side_effect=[(2, 2), (3, 3)]),
            patch.object(meight, "launchd_running_pid", return_value=333),
            patch.object(meight.time, "sleep"),
        ):
            response = meight.wait_for_fresh_daemon(Path("/tmp/unused"), None, None, 1)
        self.assertEqual(response["pid"], 333)


class ModeLifecycleTests(unittest.TestCase):
    class _EmptyHandle:
        def stream(self):
            return iter(())

        def interrupt(self):
            return None

    class _CaptureThread:
        def __init__(self):
            self.id = "thread-mode-test"
            self.inputs = []
            self.turn_kwargs = []

        def turn(self, turn_input, **kwargs):
            self.inputs.append(turn_input)
            self.turn_kwargs.append(kwargs)
            return ModeLifecycleTests._EmptyHandle()

    class _DormantConsumer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    def _start_args(self, cwd: str, mode: str = "review"):
        return meight.build_parser().parse_args([
            "dispatch", "mode-test", "--mode", mode,
            "--brief", "Review the contract.", "--cwd", cwd,
        ])

    def test_final_question_releases_runtime_but_preserves_handoff_status(self):
        class ClosableCodex:
            def __init__(self):
                self.closed = 0

            def close(self):
                self.closed += 1

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            worker = meight.Worker(
                "dormant-question",
                Path(context["repo_home"]),
                context["repo_root"],
                context["repo_key"],
                "/repo",
                "workspace_write",
                "gpt-5.6-sol",
                "high",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status("thread-question")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            worker.generation = 1
            worker.thread = self._CaptureThread()
            worker.handle = self._EmptyHandle()
            codex = ClosableCodex()
            worker.codex = codex

            worker.detach_runtime_refs_if_idle(
                meight.Daemon(home), worker.generation, "question complete"
            )

            self.assertEqual(codex.closed, 1)
            self.assertIsNone(worker.codex)
            self.assertIsNone(worker.thread)
            self.assertIsNone(worker.handle)
            self.assertEqual(worker.status["state"], "needs_input")
            self.assertEqual(worker.status["thread_id"], "thread-question")

    def test_follow_rehydrates_dormant_worker_into_ephemeral_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            repo_home = Path(context["repo_home"])
            worker = meight.Worker(
                "rehydrate",
                repo_home,
                context["repo_root"],
                context["repo_key"],
                "/repo",
                "workspace_write",
                "gpt-5.6-sol",
                "high",
                thread_ephemeral=False,
                mode="review",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status("thread-resume")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)

            capture_thread = self._CaptureThread()
            started = []

            class FakeCodex:
                def __init__(self, config):
                    self.config = config

                def thread_start(self, **kwargs):
                    started.append(kwargs)
                    return capture_thread

                def thread_resume(self, *_args, **_kwargs):
                    raise AssertionError("follow must not resume a persisted app thread")

                def close(self):
                    return None

            fake_codex = types.ModuleType("openai_codex")
            fake_codex.Codex = FakeCodex
            fake_codex.CodexConfig = lambda **kwargs: kwargs
            fake_codex.Sandbox = types.SimpleNamespace(
                workspace_write="workspace_write",
                read_only="read_only",
                full_access="full_access",
            )
            fake_types = types.ModuleType("openai_codex.types")
            fake_types.ThreadSource = types.SimpleNamespace(subagent="subagent")
            (worker.dir / "brief.md").write_text("Original persistent brief.\n")
            (worker.dir / "result.md").write_text("Prior answer.\n")
            (worker.dir / "events.log").write_text("[turn/completed] prior\n")

            daemon = meight.Daemon(home)
            with (
                patch.dict(sys.modules, {
                    "openai_codex": fake_codex,
                    "openai_codex.types": fake_types,
                }),
                patch.object(meight.threading, "Thread", self._DormantConsumer),
                patch.object(meight, "system_codex_bin", return_value="/usr/bin/true"),
                patch.object(meight, "install_computer_use_approval_bridge"),
                patch.object(meight, "relax_sdk_effort_echo"),
                patch.object(meight, "relax_sdk_effort_field"),
            ):
                response = daemon.cmd_follow({
                    "name": worker.name,
                    "brief": "Continue from the saved question.",
                    **context,
                })

            self.assertTrue(response["ok"], response)
            self.assertEqual(response["thread_id"], "thread-mode-test")
            self.assertEqual(started, [{
                "cwd": "/repo",
                "ephemeral": True,
                "sandbox": "workspace_write",
                "service_tier": None,
                "thread_source": "subagent",
            }])
            self.assertIn("Original persistent brief.", capture_thread.inputs[0])
            self.assertIn("Prior answer.", capture_thread.inputs[0])
            self.assertIn("Continue from the saved question.", capture_thread.inputs[0])
            restored = daemon.workers[
                meight.registry_key(context["repo_key"], worker.name)
            ]
            self.assertEqual(restored.status["turns"], 2)
            self.assertEqual(restored.status["state"], "starting")
            self.assertTrue(restored.status["thread_ephemeral"])
            self.assertEqual(
                restored.status["continued_from_thread_id"], "thread-resume"
            )
            self.assertEqual(capture_thread.turn_kwargs[0]["model"], "gpt-5.6-sol")

    def test_follow_continues_ephemeral_worker_with_bounded_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            repo_home = Path(context["repo_home"])
            worker = meight.Worker(
                "legacy",
                repo_home,
                context["repo_root"],
                context["repo_key"],
                "/repo",
                "workspace_write",
                "gpt-5.6-sol",
                "high",
                thread_ephemeral=True,
                mode="worker",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status("thread-legacy")
            worker.status["state"] = "interrupted"
            worker.write_status(force=True)
            (worker.dir / "brief.md").write_text("Original legacy brief.\n")
            (worker.dir / "result.md").write_text("Work stopped after schema changes.\n")
            (worker.dir / "events.log").write_text("[fileChange] schema.sql\n")

            capture_thread = self._CaptureThread()
            started = []

            class FakeCodex:
                def __init__(self, config):
                    self.config = config

                def thread_start(self, **kwargs):
                    started.append(kwargs)
                    return capture_thread

                def thread_resume(self, *_args, **_kwargs):
                    raise AssertionError("ephemeral worker must not call thread_resume")

                def close(self):
                    return None

            fake_codex = types.ModuleType("openai_codex")
            fake_codex.Codex = FakeCodex
            fake_codex.CodexConfig = lambda **kwargs: kwargs
            fake_codex.Sandbox = types.SimpleNamespace(
                workspace_write="workspace_write",
                read_only="read_only",
                full_access="full_access",
            )
            fake_types = types.ModuleType("openai_codex.types")
            fake_types.ThreadSource = types.SimpleNamespace(subagent="subagent")

            daemon = meight.Daemon(home)
            with (
                patch.dict(sys.modules, {
                    "openai_codex": fake_codex,
                    "openai_codex.types": fake_types,
                }),
                patch.object(meight.threading, "Thread", self._DormantConsumer),
                patch.object(meight, "system_codex_bin", return_value="/usr/bin/true"),
                patch.object(meight, "install_computer_use_approval_bridge"),
                patch.object(meight, "relax_sdk_effort_echo"),
                patch.object(meight, "relax_sdk_effort_field"),
            ):
                response = daemon.cmd_follow({
                    "name": worker.name,
                    "brief": "Finish the implementation.",
                    **context,
                })

            self.assertTrue(response["ok"])
            self.assertEqual(started[0]["ephemeral"], True)
            self.assertEqual(started[0]["thread_source"], "subagent")
            self.assertIn("Original legacy brief.", capture_thread.inputs[0])
            self.assertIn("Work stopped after schema changes.", capture_thread.inputs[0])
            self.assertIn("Finish the implementation.", capture_thread.inputs[0])
            restored = daemon.workers[
                meight.registry_key(context["repo_key"], worker.name)
            ]
            self.assertEqual(restored.status["thread_id"], "thread-mode-test")
            self.assertEqual(
                restored.status["continued_from_thread_id"], "thread-legacy"
            )
            self.assertTrue(restored.status["thread_ephemeral"])

    def test_wait_returns_dormant_question_without_live_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo_home = home / "repos" / "repo-key"
            worker_dir = repo_home / "workers" / "dormant"
            worker_dir.mkdir(parents=True)
            (worker_dir / "status.json").write_text(json.dumps({
                "name": "dormant",
                "state": "needs_input",
                "needs_input_source": "question",
                "thread_id": "thread-dormant",
            }), encoding="utf-8")
            with (
                patch.object(meight, "query_runtime_status") as runtime,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = meight.wait_for_worker(home, repo_home, "dormant", timeout=1)
            self.assertEqual(result, 3)
            runtime.assert_not_called()

    def test_dormant_question_does_not_block_shutdown_and_is_registry_gc_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            worker = meight.Worker(
                "dormant",
                Path(context["repo_home"]),
                context["repo_root"],
                context["repo_key"],
                "/repo",
                "workspace_write",
                "gpt-5.6-sol",
                "high",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status("thread-dormant")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            self.assertIsNotNone(worker.terminal_since)

            daemon = meight.Daemon(home)
            daemon.worker_gc_ttl_sec = 1
            key = meight.registry_key(context["repo_key"], worker.name)
            daemon.workers[key] = worker
            response = daemon.cmd_shutdown({"force": False})
            self.assertTrue(response["ok"])
            self.assertEqual(response["interrupted"], [])

            daemon._shutdown_now()
            self.assertEqual(worker.status["state"], "needs_input")
            self.assertEqual(worker.status["thread_id"], "thread-dormant")

            daemon.shutting_down.clear()
            worker.terminal_since = time.monotonic() - 2
            with patch.object(daemon, "_schedule_retention_cleanup"):
                daemon._maintenance()
            self.assertNotIn(key, daemon.workers)

    def test_each_mode_maps_to_expected_skill_and_common_contract(self):
        for mode, directory in (
            ("mate", "meight-mate"),
            ("design", "meight-mate"),
            ("review", "meight-mate"),
            ("worker", "meight-worker"),
            ("delegate", "meight-worker"),
        ):
            with self.subTest(mode=mode):
                preamble = meight.build_preamble(mode)
                self.assertIn(f"skills/{directory}/SKILL.md", preamble)
                self.assertIn("skills/meight-common/CONTRACT.md", preamble)
                self.assertIn(f"mode={meight.normalize_mode(mode)}", preamble)
                self.assertNotIn("Harness protocol", preamble)
                self.assertNotIn("role:", preamble)

    def test_mode_aliases_normalize_onto_the_two_postures(self):
        self.assertEqual(meight.normalize_mode("mate"), "mate")
        self.assertEqual(meight.normalize_mode("design"), "mate")
        self.assertEqual(meight.normalize_mode("collab"), "mate")
        self.assertEqual(meight.normalize_mode("collaborative"), "mate")
        self.assertEqual(meight.normalize_mode("review"), "mate")
        self.assertEqual(meight.normalize_mode("worker"), "worker")
        self.assertEqual(meight.normalize_mode("delegate"), "worker")
        self.assertEqual(meight.normalize_mode("delegated"), "worker")
        for rejected in (None, "", "reviewer", "workers", "mates"):
            self.assertIsNone(meight.normalize_mode(rejected))

    def test_daemon_rejects_missing_or_invalid_mode_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            for mode in (None, "reviewer"):
                with self.subTest(mode=mode):
                    req = {"cmd": "start", "protocol_epoch": meight.PROTOCOL_EPOCH}
                    if mode is not None:
                        req["mode"] = mode
                    response = daemon._dispatch(req)
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["error"], meight.MODE_TEACHING_ERROR.removeprefix("error: "))
                    self.assertEqual(daemon.workers, {})
                    self.assertFalse((home / "repos").exists())

    def test_daemon_rejects_missing_or_stale_epoch_before_any_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            with (
                patch.object(daemon, "cmd_start") as start,
                patch.object(daemon, "cmd_follow") as follow,
            ):
                for command, epoch in (("start", None), ("start", "mode3"),
                                       ("follow", None), ("follow", "mode3")):
                    with self.subTest(command=command, epoch=epoch):
                        req = {"cmd": command, "mode": "worker", "name": "epoch-test"}
                        if epoch is not None:
                            req["protocol_epoch"] = epoch
                        response = daemon._dispatch(req)
                        self.assertEqual(response, {
                            "ok": False,
                            "error": meight.PROTOCOL_EPOCH_ERROR,
                        })
                        self.assertEqual(daemon.workers, {})
                        self.assertFalse((home / "repos").exists())
                start.assert_not_called()
                follow.assert_not_called()

    def test_cli_missing_and_invalid_mode_share_teaching_error(self):
        parser = meight.build_parser()
        for mode_args in ([], ["--mode", "reviewer"]):
            with self.subTest(mode_args=mode_args):
                args = parser.parse_args([
                    "dispatch", "mode-teaching", "--brief", "No side effects.", *mode_args,
                ])
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    meight.start_request(args, Path("/tmp/meight-mode-teaching"))
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(stderr.getvalue().strip(), meight.MODE_TEACHING_ERROR)

    def test_single_axis_mode_validation_precedes_side_effects(self):
        parser = meight.build_parser()
        for command in ("dispatch",):
            for mode_args in ([], ["--mode", "invalid"]):
                with self.subTest(command=command, mode_args=mode_args):
                    args = parser.parse_args([
                        command, "mode-precedence", "--brief", "No side effects.", *mode_args,
                    ])
                    stderr = io.StringIO()
                    call = meight.cmd_dispatch
                    with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                        call(args, Path("/tmp/meight-mode-precedence"))
                    self.assertEqual(error.exception.code, 2)
                    self.assertEqual(stderr.getvalue().strip(), meight.MODE_TEACHING_ERROR)

    def test_follow_path_inherits_recorded_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            repo_home = Path(context["repo_home"])
            worker = meight.Worker(
                "inherit-mode", repo_home, context["repo_root"], context["repo_key"], "/repo",
                "workspace_write", "gpt-5.6-sol", "high",
                service_tier="priority",
                mode="review",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-mode-test")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            thread = self._CaptureThread()
            worker.thread = thread

            daemon = meight.Daemon(home)
            daemon.workers[meight.registry_key(context["repo_key"], "inherit-mode")] = worker
            response = daemon.cmd_follow({
                "name": "inherit-mode",
                "brief": "Use the recommended correction.",
                **context,
            })
            if worker.consumer is not None:
                worker.consumer.join(timeout=2)

            self.assertTrue(response["ok"])
            self.assertEqual(response["mode"], "mate")
            self.assertEqual(response["protocol_epoch"], meight.PROTOCOL_EPOCH)
            self.assertEqual(worker.status["mode"], "mate")
            self.assertEqual(thread.turn_kwargs[0], {
                "model": "gpt-5.6-sol",
                "effort": "high",
                "service_tier": "priority",
            })
            self.assertIn("skills/meight-mate/SKILL.md", thread.inputs[0])
            self.assertIn("skills/meight-common/CONTRACT.md", thread.inputs[0])

    def test_follow_preserves_each_canonical_mode_and_epoch(self):
        expected_skills = {
            "mate": "meight-mate",
            "worker": "meight-worker",
        }
        for mode, skill in expected_skills.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                context = meight.repo_context(home, "/repo")
                repo_home = Path(context["repo_home"])
                worker = meight.Worker(
                    f"follow-{mode}", repo_home, context["repo_root"], context["repo_key"],
                    "/repo", "workspace_write", "gpt-5.6-sol", "high", mode=mode,
                )
                worker.dir.mkdir(parents=True)
                worker.init_status(thread_id=f"thread-{mode}")
                worker.status["state"] = "completed"
                worker.write_status(force=True)
                thread = self._CaptureThread()
                worker.thread = thread
                daemon = meight.Daemon(home)
                daemon.workers[meight.registry_key(context["repo_key"], worker.name)] = worker

                with patch.object(meight.threading, "Thread", self._DormantConsumer):
                    response = daemon.cmd_follow({
                        "name": worker.name,
                        "brief": "Continue.",
                        **context,
                    })

                self.assertEqual(response["mode"], mode)
                self.assertEqual(response["protocol_epoch"], meight.PROTOCOL_EPOCH)
                self.assertIn(f"skills/{skill}/SKILL.md", thread.inputs[0])
                self.assertIn("skills/meight-common/CONTRACT.md", thread.inputs[0])

    def test_follow_overrides_reach_turn_persist_and_are_inherited_next_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            repo_home = Path(context["repo_home"])
            worker = meight.Worker(
                "turn-overrides", repo_home, context["repo_root"], context["repo_key"], "/repo",
                "workspace_write", "gpt-5.6-sol", "medium", service_tier="default",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-mode-test")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            thread = self._CaptureThread()
            worker.thread = thread

            daemon = meight.Daemon(home)
            daemon.workers[meight.registry_key(context["repo_key"], worker.name)] = worker
            with patch.object(meight.threading, "Thread", self._DormantConsumer):
                first = daemon.cmd_follow({
                    "name": worker.name,
                    "brief": "Use the stronger settings.",
                    "model": "luna",
                    "effort": "xhigh",
                    "service_tier": "priority",
                    **context,
                })

                self.assertTrue(first["ok"])
                expected = {
                    "model": "gpt-5.6-luna",
                    "effort": "xhigh",
                    "service_tier": "priority",
                }
                self.assertEqual(thread.turn_kwargs[0], expected)
                self.assertEqual(
                    {key: worker.status[key] for key in expected}, expected,
                )
                saved = json.loads((worker.dir / "status.json").read_text(encoding="utf-8"))
                self.assertEqual({key: saved[key] for key in expected}, expected)

                worker.status["state"] = "needs_input"
                worker.status["needs_input_source"] = "question"
                worker.write_status(force=True)
                second = daemon.cmd_follow({
                    "name": worker.name,
                    "brief": "Keep going without overrides.",
                    **context,
                })

            self.assertTrue(second["ok"])
            self.assertEqual(thread.turn_kwargs[1], expected)

    def test_invalid_raw_follow_overrides_fail_before_reset_or_turn(self):
        invalid_overrides = (
            {"effort": "impossible"},
            {"service_tier": "express"},
            {"model": ""},
            {"model": "   "},
            {"model": None},
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                context = meight.repo_context(home, "/repo")
                repo_home = Path(context["repo_home"])
                worker = meight.Worker(
                    "invalid-overrides", repo_home, context["repo_root"], context["repo_key"],
                    "/repo", "workspace_write", "gpt-5.6-sol", "high",
                    service_tier="default",
                )
                worker.dir.mkdir(parents=True)
                worker.init_status(thread_id="thread-mode-test")
                worker.status["state"] = "needs_input"
                worker.status["needs_input_source"] = "question"
                worker.write_status(force=True)
                thread = self._CaptureThread()
                worker.thread = thread
                daemon = meight.Daemon(home)
                daemon.workers[meight.registry_key(context["repo_key"], worker.name)] = worker

                before = (worker.generation, worker.status["turns"], worker.status["state"])
                response = daemon.cmd_follow({
                    "name": worker.name,
                    "brief": "This must not start.",
                    **overrides,
                    **context,
                })

                self.assertFalse(response["ok"])
                self.assertEqual(
                    (worker.generation, worker.status["turns"], worker.status["state"]), before,
                )
                self.assertEqual(thread.turn_kwargs, [])

    def test_failed_follow_turn_does_not_persist_requested_overrides(self):
        class FailingThread:
            def turn(self, turn_input, **kwargs):
                raise RuntimeError("turn start failed")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            context = meight.repo_context(home, "/repo")
            repo_home = Path(context["repo_home"])
            worker = meight.Worker(
                "failed-overrides", repo_home, context["repo_root"], context["repo_key"],
                "/repo", "workspace_write", "gpt-5.6-luna", "medium",
                service_tier="default",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-mode-test")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            worker.thread = FailingThread()
            daemon = meight.Daemon(home)
            daemon.workers[meight.registry_key(context["repo_key"], worker.name)] = worker

            response = daemon.cmd_follow({
                "name": worker.name,
                "brief": "This turn will fail to start.",
                "model": "sol",
                "effort": "high",
                "service_tier": "priority",
                **context,
            })

            self.assertFalse(response["ok"])
            self.assertEqual(worker.model, "gpt-5.6-luna")
            self.assertEqual(worker.effort, "medium")
            self.assertEqual(worker.service_tier, "default")
            self.assertEqual(worker.status["model"], "gpt-5.6-luna")
            self.assertEqual(worker.status["effort"], "medium")
            self.assertEqual(worker.status["service_tier"], "default")

    def test_follow_reply_cli_omission_inherits_and_explicit_fast_flags_map_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo_home = home / "repos" / "repo-key"
            status_dir = repo_home / "workers" / "follow-options"
            status_dir.mkdir(parents=True)
            (status_dir / "status.json").write_text(
                json.dumps({"mode": "delegate"}), encoding="utf-8",
            )
            context = {
                "repo_root": "/repo", "repo_key": "repo-key", "repo_home": str(repo_home),
            }
            parser = meight.build_parser()
            cases = (
                (
                    ["follow", "follow-options", "--brief", "inherit"],
                    {},
                ),
                (
                    ["follow", "follow-options", "--brief", "fast", "--fast"],
                    {"service_tier": "priority"},
                ),
                (
                    ["reply", "follow-options", "--brief", "override", "--model", "luna",
                     "--effort", "high", "--no-fast"],
                    {"model": "gpt-5.6-luna", "effort": "high", "service_tier": "default"},
                ),
            )
            for argv, expected in cases:
                with self.subTest(argv=argv):
                    args = parser.parse_args(argv)
                    with (
                        patch.object(meight, "repo_home_for_cli", return_value=repo_home),
                        patch.object(meight, "request_repo_context", return_value=context),
                        patch.object(
                            meight, "send_request",
                            return_value={
                                "ok": True,
                                "mode": "worker",
                                "protocol_epoch": meight.PROTOCOL_EPOCH,
                            },
                        ) as send,
                    ):
                        response = meight.follow_request(args, home)
                    self.assertTrue(response["ok"])
                    request = send.call_args.args[1]
                    self.assertEqual(request["protocol_epoch"], meight.PROTOCOL_EPOCH)
                    self.assertNotIn("mode", request)
                    for key in ("model", "effort", "service_tier"):
                        if key in expected:
                            self.assertEqual(request[key], expected[key])
                        else:
                            self.assertNotIn(key, request)

    def test_status_table_has_mode_cell_and_no_role_column(self):
        status = {
            "name": "review-1",
            "state": "running",
            "mode": "review",
            "started_at": meight.now_iso(),
            "updated_at": meight.now_iso(),
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            meight.print_status_table([status])
        self.assertNotIn("ROLE", output.getvalue().splitlines()[0])
        self.assertIn("MODE", output.getvalue().splitlines()[0])
        self.assertIn("mate", output.getvalue().splitlines()[1])

    def test_status_views_archive_terminal_rows_after_six_hours(self):
        now = datetime(2026, 8, 4, 18, 0, tzinfo=meight.KST)
        statuses = [
            {"name": "active", "state": "running", "updated_at": "2026-08-03T00:00:00+09:00"},
            {"name": "fresh", "state": "completed", "terminal_at": "2026-08-04T12:00:01+09:00"},
            {"name": "archived", "state": "failed", "terminal_at": "2026-08-04T12:00:00+09:00"},
            {"name": "legacy", "state": "interrupted", "updated_at": "2026-08-04T11:00:00+09:00"},
            {"name": "invalid", "state": "completed", "terminal_at": "not-a-time"},
        ]

        recent = meight.filter_statuses(statuses, "recent", cutoff_now=now)
        archived = meight.filter_statuses(statuses, "archived", cutoff_now=now)

        self.assertEqual([status["name"] for status in recent], ["active", "fresh", "invalid"])
        self.assertEqual([status["name"] for status in archived], ["archived", "legacy"])
        self.assertIs(meight.filter_statuses(statuses, "all", cutoff_now=now), statuses)

    def test_status_and_list_accept_archive_views(self):
        parser = meight.build_parser()

        self.assertTrue(parser.parse_args(["status", "--archived"]).archived)
        self.assertTrue(parser.parse_args(["status", "--all"]).show_all)
        self.assertTrue(parser.parse_args(["list", "--archived"]).archived)
        self.assertTrue(parser.parse_args(["list", "--all"]).show_all)

    def test_status_serializes_both_canonical_postures(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            for idx, mode in enumerate(("mate", "worker")):
                with self.subTest(mode=mode):
                    worker = meight.Worker(
                        f"status-{idx}", repo_home, "/repo", "repo-key", "/repo",
                        "workspace_write", "gpt-5.6-luna", "high", mode=mode,
                    )
                    worker.dir.mkdir(parents=True)
                    worker.init_status(thread_id=f"thread-{mode}")
                    saved = json.loads((worker.dir / "status.json").read_text(encoding="utf-8"))
                    self.assertEqual(saved["mode"], mode)
                    self.assertIn(mode, meight.summary_line(saved))

    def test_dispatch_output_echoes_resolved_defaults_and_provenance(self):
        cases = (
            ("worker",
             "model=grok(default) effort=high(default) fast=off(default) "
             "sandbox=full(default)"),
            ("mate",
             "model=sol(default) effort=medium(default) fast=off(default) "
             "sandbox=full(default)"),
        )
        for mode, settings in cases:
            with self.subTest(mode=mode):
                args = self._start_args("/repo", mode=mode)
                output = io.StringIO()
                response = {
                    "ok": True,
                    "thread_id": f"thread-{mode}",
                    "mode": mode,
                    "protocol_epoch": meight.PROTOCOL_EPOCH,
                }
                with (
                    patch.object(meight, "ensure_daemon", return_value=True),
                    patch.object(meight, "start_request", return_value=response),
                    patch.object(meight, "wait_for_worker", return_value=1),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(meight.cmd_dispatch(args, Path("/tmp/meight-output")), 1)
                self.assertIn(f"mode={mode} {settings}", output.getvalue())

    def test_dispatch_output_marks_explicit_flags_as_set(self):
        args = meight.build_parser().parse_args([
            "dispatch", "mode-test", "--mode", "worker", "--brief", "Implement.",
            "--model", "sol", "--effort", "high", "--fast",
            "--sandbox", "ro",
        ])
        response = {
            "ok": True, "thread_id": "thread-worker", "mode": "worker",
            "protocol_epoch": meight.PROTOCOL_EPOCH,
        }
        output = io.StringIO()
        with (
            patch.object(meight, "ensure_daemon", return_value=True),
            patch.object(meight, "start_request", return_value=response),
            patch.object(meight, "wait_for_worker", return_value=1),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(meight.cmd_dispatch(args, Path("/tmp/meight-output")), 1)
        self.assertIn(
            "model=sol(set) effort=high(set) fast=on(set) "
            "sandbox=ro(set)",
            output.getvalue(),
        )

    def test_legacy_rows_with_role_and_old_modes_render_without_crash(self):
        for old_mode, expected in (("collaborative", "mate"), ("delegated", "worker")):
            status = {
                "name": "legacy",
                "state": "completed",
                "role": "mate",
                "mode": old_mode,
                "started_at": meight.now_iso(),
                "updated_at": meight.now_iso(),
            }
            line = meight.summary_line(status)
            self.assertIn("legacy", line)
            self.assertEqual(line.split()[2], expected)
        role_only = {
            "name": "role-only",
            "state": "completed",
            "role": "mate",
            "started_at": meight.now_iso(),
            "updated_at": meight.now_iso(),
        }
        self.assertEqual(meight.summary_line(role_only).split()[2], "-")

    def test_missing_protocol_capability_fails_before_start_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            args = self._start_args(tmp)
            requests = []

            def old_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                requests.append(req)
                return {"ok": True, "pid": 1234, "capabilities": ["mode4"]}

            with patch.object(meight, "send_request", side_effect=old_daemon):
                response = meight.start_request(args, home)

            self.assertEqual(response, {
                "ok": False,
                "error": f"daemon predates protocol {meight.PROTOCOL_EPOCH}; restart required",
            })
            self.assertEqual(requests, [{"cmd": "ping"}])
            self.assertFalse((home / "repos").exists())

    def test_missing_or_mismatched_start_mode_epoch_echo_fails_and_interrupts(self):
        echoes = (
            {},
            {"mode": "worker", "protocol_epoch": meight.PROTOCOL_EPOCH},
            {"mode": "mate"},
            {"mode": "mate", "protocol_epoch": "mode4"},
        )
        for echo in echoes:
            with self.subTest(echo=echo), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                args = self._start_args(tmp, mode="review")
                requests = []

                def swapped_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                    requests.append(req)
                    if req["cmd"] == "ping":
                        return {"ok": True, "capabilities": [meight.PROTOCOL_EPOCH]}
                    if req["cmd"] == "start":
                        response = {"ok": True, "thread_id": "old-daemon-worker"}
                        response.update(echo)
                        return response
                    return {"ok": True}

                with patch.object(meight, "send_request", side_effect=swapped_daemon):
                    response = meight.start_request(args, home)

                self.assertEqual(response, {
                    "ok": False,
                    "error": "start protocol mismatch: "
                    f"expected mode=mate target=mac runtime=codex epoch={meight.PROTOCOL_EPOCH}",
                })
                self.assertEqual([req["cmd"] for req in requests], ["ping", "start", "interrupt"])
                self.assertEqual(requests[2]["name"], args.name)
                for key in ("repo_root", "repo_key", "repo_home"):
                    self.assertEqual(requests[2][key], requests[1][key])

    def test_swapped_daemon_same_token_epoch_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            args = self._start_args(tmp, mode="delegate")
            requests = []

            def swapped_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                requests.append(req)
                if req["cmd"] == "ping":
                    return {"ok": True, "capabilities": [meight.PROTOCOL_EPOCH]}
                if req["cmd"] == "start":
                    return {
                        "ok": True,
                        "thread_id": "same-token-old-contract",
                        "mode": "worker",
                        "protocol_epoch": "mode4",
                    }
                return {"ok": True}

            with patch.object(meight, "send_request", side_effect=swapped_daemon):
                response = meight.start_request(args, home)

            self.assertEqual(response, {
                "ok": False,
                "error": "start protocol mismatch: "
                f"expected mode=worker target=mac runtime=codex epoch={meight.PROTOCOL_EPOCH}",
            })
            self.assertEqual([req["cmd"] for req in requests], ["ping", "start", "interrupt"])
            self.assertEqual(requests[1]["protocol_epoch"], meight.PROTOCOL_EPOCH)

    def test_missing_or_mismatched_follow_mode_epoch_echo_fails_and_interrupts(self):
        echoes = (
            {},
            {"mode": "worker", "protocol_epoch": meight.PROTOCOL_EPOCH},
            {"mode": "mate"},
            {"mode": "mate", "protocol_epoch": "mode4"},
        )
        for echo in echoes:
            with self.subTest(echo=echo), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                repo_home = home / "repos" / "repo-key"
                status_dir = repo_home / "workers" / "follow-mode"
                status_dir.mkdir(parents=True)
                (status_dir / "status.json").write_text(
                    json.dumps({"mode": "review"}), encoding="utf-8",
                )
                args = meight.build_parser().parse_args([
                    "follow", "follow-mode", "--brief", "Re-review.",
                ])
                requests = []

                def swapped_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                    requests.append(req)
                    if req["cmd"] == "follow":
                        response = {"ok": True, "thread_id": "thread-mode", "turns": 2}
                        response.update(echo)
                        return response
                    return {"ok": True}

                with (
                    patch.object(meight, "repo_home_for_cli", return_value=repo_home),
                    patch.object(meight, "request_repo_context", return_value={
                        "repo_root": "/repo", "repo_key": "repo-key", "repo_home": str(repo_home),
                    }),
                    patch.object(meight, "send_request", side_effect=swapped_daemon),
                ):
                    response = meight.follow_request(args, home)

                self.assertEqual(response, {
                    "ok": False,
                    "error": "follow protocol mismatch: "
                    f"expected mode=mate target=mac runtime=codex epoch={meight.PROTOCOL_EPOCH}",
                })
                self.assertEqual([req["cmd"] for req in requests], ["follow", "interrupt"])
                self.assertEqual(requests[1]["name"], args.name)

    def test_ping_and_runtime_status_advertise_protocol_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            ping = daemon._dispatch({"cmd": "ping"})
            runtime = daemon.cmd_runtime_status({"name": "unknown", **meight.repo_context(home, "/repo")})
            self.assertEqual(ping["capabilities"], [meight.PROTOCOL_EPOCH])
            self.assertEqual(ping["session_retention_sec"], 30 * 24 * 60 * 60)
            self.assertEqual(runtime["capabilities"], [meight.PROTOCOL_EPOCH])

    def test_advertised_protocol_capability_starts_and_records_mode_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            args = self._start_args(tmp, mode="review")
            capture_thread = self._CaptureThread()

            class FakeCodex:
                def __init__(self, config):
                    self.config = config

                def thread_start(self, **kwargs):
                    return capture_thread

                def close(self):
                    return None

            fake_codex = types.ModuleType("openai_codex")
            fake_codex.Codex = FakeCodex
            fake_codex.CodexConfig = lambda **kwargs: kwargs
            fake_codex.Sandbox = types.SimpleNamespace(
                workspace_write="workspace_write", read_only="read_only", full_access="full_access",
            )
            fake_types = types.ModuleType("openai_codex.types")
            fake_types.ThreadSource = types.SimpleNamespace(user="user", subagent="subagent")

            def route_request(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                return daemon._dispatch(req)

            with (
                patch.dict(sys.modules, {
                    "openai_codex": fake_codex,
                    "openai_codex.types": fake_types,
                }),
                patch.object(meight, "send_request", side_effect=route_request),
                patch.object(meight, "system_codex_bin", return_value="/usr/bin/true"),
                patch.object(meight, "install_computer_use_approval_bridge"),
                patch.object(meight, "relax_sdk_effort_echo"),
                patch.object(meight, "relax_sdk_effort_field"),
            ):
                response = meight.start_request(args, home)

            self.assertTrue(response["ok"])
            self.assertEqual(response["mode"], "mate")
            self.assertEqual(response["protocol_epoch"], meight.PROTOCOL_EPOCH)
            repo_home = Path(meight.repo_context(home)["repo_home"])
            status_path = repo_home / "workers" / "mode-test" / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertNotIn("role", status)
            self.assertNotIn("report", status)
            self.assertEqual(status["mode"], "mate")
            self.assertEqual(status["thread_source"], "subagent")
            self.assertTrue(status["thread_ephemeral"])
            self.assertNotIn("output_schema", capture_thread.turn_kwargs[0])
            self.assertIn("skills/meight-mate/SKILL.md", capture_thread.inputs[0])


class MessageLogTests(unittest.TestCase):
    def _worker(self, tmp: str, name: str = "speaker") -> "meight.Worker":
        worker = meight.Worker(name, Path(tmp), "/repo", "repo-key", "/repo",
                               "workspace_write", "gpt-5.6-sol", "medium", "default")
        worker.dir.mkdir(parents=True)
        worker.init_status(thread_id="thread-1")
        self.addCleanup(worker.close_message_log)
        return worker

    def _messages(self, worker) -> str:
        return (worker.dir / meight.MESSAGE_LOG_NAME).read_text(encoding="utf-8")

    def test_deltas_reach_disk_immediately_and_unthrottled(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(tmp)
            path = worker.dir / meight.MESSAGE_LOG_NAME
            sizes = []
            for delta in ("계약을 ", "먼저 확인하겠습니다.", " 그다음 구현합니다."):
                worker._handle_event("item/agentMessage/delta", {"delta": delta})
                sizes.append(path.stat().st_size)
            self.assertEqual(sizes, sorted(sizes))
            self.assertEqual(len(set(sizes)), 3)  # every delta grew the file
            self.assertIn("계약을 먼저 확인하겠습니다. 그다음 구현합니다.", self._messages(worker))

    def test_message_blocks_are_separated_for_a_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(tmp)
            for text in ("첫 번째 메시지입니다.", "두 번째 메시지입니다."):
                worker._handle_event("item/started", {"item": {"type": "agentMessage"}})
                worker._handle_event("item/agentMessage/delta", {"delta": text})
                worker._on_item_completed({"type": "agentMessage", "text": text})
            body = self._messages(worker)
            self.assertEqual(body.count("──"), 4)  # one delimited header per message
            self.assertIn("첫 번째 메시지입니다.\n", body)
            self.assertIn("두 번째 메시지입니다.\n", body)
            self.assertNotIn("{", body)  # plain prose, not JSON lines

    def test_completion_writes_the_text_deltas_did_not_carry(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(tmp)
            worker._on_item_completed({"type": "agentMessage", "text": "델타 없이 도착한 전문"})
            self.assertIn("델타 없이 도착한 전문", self._messages(worker))

            worker._handle_event("item/agentMessage/delta", {"delta": "앞부분만 "})
            worker._on_item_completed({"type": "agentMessage", "text": "앞부분만 그리고 나머지"})
            body = self._messages(worker)
            self.assertIn("앞부분만 그리고 나머지", body)
            self.assertEqual(body.count("앞부분만"), 1)  # no duplicated prefix

    def test_only_agent_messages_stream_and_existing_digests_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(tmp)
            for method in ("item/reasoning/textDelta", "item/commandExecution/outputDelta",
                           "item/reasoning/summaryTextDelta"):
                worker._handle_event(method, {"delta": "noise"})
            self.assertFalse((worker.dir / meight.MESSAGE_LOG_NAME).exists())

            long_text = "가" * 900
            worker._handle_event("item/agentMessage/delta", {"delta": long_text})
            worker._on_item_completed({"type": "agentMessage", "text": long_text})
            self.assertEqual(worker.status["last_message_tail"], long_text[-500:])
            events = (worker.dir / "events.log").read_text(encoding="utf-8")
            self.assertIn("[item/completed] agentMessage: ", events)
            self.assertLessEqual(max(len(line) for line in events.splitlines()),
                                 meight.EVENT_LINE_MAX)
            self.assertIn(long_text, self._messages(worker))  # only the new file is complete

    def test_follow_turn_separates_messages_and_start_clears_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = self._worker(tmp)
            worker._handle_event("item/agentMessage/delta", {"delta": "턴 1 발언"})
            worker.status["state"] = "completed"
            worker.reset_for_follow("다음 지시")
            worker._handle_event("item/agentMessage/delta", {"delta": "턴 2 발언"})
            body = self._messages(worker)
            self.assertIn("=== turn 2 (", body)
            self.assertLess(body.index("턴 1 발언"), body.index("=== turn 2 ("))
            self.assertLess(body.index("=== turn 2 ("), body.index("턴 2 발언"))


class WatchTests(unittest.TestCase):
    def _worker(self, repo_home: Path, name: str, **status) -> Path:
        wdir = repo_home / "workers" / name
        wdir.mkdir(parents=True, exist_ok=True)
        self._status(wdir, name, **status)
        return wdir

    def _status(self, wdir: Path, name: str, **status) -> None:
        row = {"name": name, "state": "running", "mode": "worker",
               "started_at": meight.now_iso(), "updated_at": meight.now_iso(),
               "current_item": None, "files_changed": [], "tokens": {}}
        row.update(status)
        meight.atomic_write_json(wdir / "status.json", row)

    def _say(self, wdir: Path, text: str) -> None:
        with open(wdir / meight.MESSAGE_LOG_NAME, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()

    def test_follower_shows_a_recent_tail_then_follows_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / meight.MESSAGE_LOG_NAME
            path.write_text("버려질 첫 줄\n" + "이전 메시지\n" * 5, encoding="utf-8")
            follower = meight.MessageLogFollower(path, tail_chars=30)
            first = follower.poll()
            self.assertNotIn("버려질 첫 줄", first)
            self.assertIn("이전 메시지", first)
            self.assertEqual(follower.poll(), "")
            with open(path, "a", encoding="utf-8") as f:
                f.write("새로 하는 말")
            self.assertEqual(follower.poll(), "새로 하는 말")

    def test_follower_holds_a_split_multibyte_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / meight.MESSAGE_LOG_NAME
            path.write_bytes(b"")
            follower = meight.MessageLogFollower(path, from_start=True)
            self.assertEqual(follower.poll(), "")
            encoded = "한글".encode("utf-8")
            with open(path, "ab") as f:
                f.write(encoded[:4])  # splits the second character
            self.assertEqual(follower.poll(), "한")
            with open(path, "ab") as f:
                f.write(encoded[4:])
            self.assertEqual(follower.poll(), "글")

    def test_follower_waits_for_a_missing_file_and_replays_a_replaced_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / meight.MESSAGE_LOG_NAME
            follower = meight.MessageLogFollower(path, from_start=True)
            self.assertEqual(follower.poll(), "")
            path.write_text("첫 세션\n", encoding="utf-8")
            self.assertEqual(follower.poll(), "첫 세션\n")
            path.unlink()
            self.assertEqual(follower.poll(), "")
            path.write_text("새 세션\n", encoding="utf-8")
            self.assertEqual(follower.poll(), "새 세션\n")

    def test_renderer_keeps_the_footer_off_an_unfinished_line(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        stream = Tty()
        renderer = meight.WatchRenderer(stream)
        renderer.write("문장이 이어지는 중")
        renderer.set_footer("▸ running")
        self.assertNotIn("running", stream.getvalue())  # would land inside the sentence
        renderer.write("\n")
        renderer.set_footer("▸ running")
        self.assertIn("▸ running", stream.getvalue())

    def test_footer_advances_on_the_viewer_clock_when_status_stalls(self):
        session = meight.WatchSession("w1", Path("/nonexistent"))
        session.status = {"state": "running", "current_item": "commandExecution: sleep 600 (2s)"}
        with patch.object(meight.time, "monotonic", side_effect=[10.0, 10.0]):
            self.assertEqual(session.footer(), "commandExecution: sleep 600 (2s)")
        with patch.object(meight.time, "monotonic", return_value=25.0):
            self.assertEqual(session.footer(), "commandExecution: sleep 600 (17s)")
        # A repeat of the same command restarts the count instead of inheriting it.
        session.status["current_item"] = "commandExecution: sleep 600 (0s)"
        with patch.object(meight.time, "monotonic", side_effect=[40.0, 40.0]):
            self.assertEqual(session.footer(), "commandExecution: sleep 600 (0s)")
        session.status["current_item"] = None
        self.assertEqual(session.footer(), "running")
        session.status["current_item"] = "capacity retry #3 in 5s"
        self.assertEqual(session.footer(), "capacity retry #3 in 5s")

    def test_watch_stop_state_covers_terminal_and_dormant_question_only(self):
        self.assertEqual(meight.watch_stop_state({"state": "completed"}), "completed")
        self.assertEqual(meight.watch_stop_state({"state": "failed"}), "failed")
        self.assertIsNone(meight.watch_stop_state({"state": "running"}))
        self.assertIsNone(meight.watch_stop_state(
            {"state": "needs_input", "needs_input_source": "tool"}))
        self.assertEqual(meight.watch_stop_state(
            {"state": "needs_input", "needs_input_source": "question"}), "needs_input")

    def test_run_watch_streams_speech_verbatim_until_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            wdir = self._worker(repo_home, "w1")
            self._say(wdir, "\n── 01:00:00+09:00 ──\n오래된 메시지\n")

            def writer():
                time.sleep(0.05)
                self._say(wdir, "\n── 01:02:03+09:00 ──\n계약을 ")
                time.sleep(0.05)
                self._say(wdir, "먼저 확인하겠습니다.\n")
                self._status(wdir, "w1", state="completed", terminal_at=meight.now_iso(),
                             files_changed=["meight.py"])

            stream = io.StringIO()
            appender = threading.Thread(target=writer)
            appender.start()
            code = meight.run_watch(repo_home, ["w1"], tail_chars=200, poll_sec=0.01,
                                    stream=stream)
            appender.join()
            out = stream.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(code, 0)
            self.assertIn("계약을 먼저 확인하겠습니다.", out)  # verbatim, not reformatted
            self.assertIn("── 01:02:03+09:00 ──", out)
            self.assertIn("w1", out.splitlines()[-1])
            self.assertNotIn("\x1b", out)  # no escapes when stdout is not a TTY

    def test_run_watch_waits_for_a_worker_that_has_not_spoken_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            wdir = repo_home / "workers" / "late-1"

            def writer():
                time.sleep(0.05)
                self._worker(repo_home, "late-1")
                self._say(wdir, "빌드가 깨졌습니다.\n")
                self._status(wdir, "late-1", state="failed", terminal_at=meight.now_iso(),
                             error_detail={"message": "build broke", "status": 500,
                                           "type": "server_error"})

            stream = io.StringIO()
            appender = threading.Thread(target=writer)
            appender.start()
            code = meight.run_watch(repo_home, ["late-1"], poll_sec=0.01, stream=stream)
            appender.join()
            out = stream.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("(waiting for 'late-1' to speak)", out)
            self.assertIn("빌드가 깨졌습니다.", out)
            self.assertIn("error: HTTP 500 server_error: build broke", out)

    def test_run_watch_prefixes_every_line_when_interleaving(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            first = self._worker(repo_home, "impl-a")
            second = self._worker(repo_home, "mate-b")
            self._say(first, "\n── 01:00:00+09:00 ──\n구현을 시작합니다.\n")
            self._say(second, "\n── 01:00:01+09:00 ──\n설계를 검토합니다.\n")
            self._status(first, "impl-a", state="completed", terminal_at=meight.now_iso())
            self._status(second, "mate-b", state="needs_input",
                         needs_input_source="question",
                         needs_input_detail="QUESTION: TARGET: user KIND: scope 범위?")
            stream = io.StringIO()
            code = meight.run_watch(repo_home, ["impl-a", "mate-b"], from_start=True,
                                    poll_sec=0.01, stream=stream)
            out = stream.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("impl-a         구현을 시작합니다.", out)
            self.assertIn("mate-b         설계를 검토합니다.", out)
            self.assertNotIn("impl-a         \n", out)  # blank separators stay unprefixed
            self.assertIn("question: QUESTION: TARGET: user", out)

    def test_watch_selects_the_only_active_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            self._worker(repo_home, "active-1")
            self._worker(repo_home, "done-1", state="completed",
                         terminal_at=meight.now_iso())
            parser = meight.build_parser()
            with patch.object(meight, "repo_home_for_cli", return_value=repo_home), \
                    patch.object(meight, "run_watch", return_value=0) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(meight.cmd_watch(parser.parse_args(["watch"]), Path(tmp)), 0)
            self.assertEqual(run.call_args.args[1], ["active-1"])

    def test_watch_all_interleaves_every_active_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            self._worker(repo_home, "active-1")
            self._worker(repo_home, "active-2")
            parser = meight.build_parser()
            with patch.object(meight, "repo_home_for_cli", return_value=repo_home), \
                    patch.object(meight, "run_watch", return_value=0) as run:
                self.assertEqual(
                    meight.cmd_watch(parser.parse_args(["watch", "--all"]), Path(tmp)), 0)
            self.assertEqual(run.call_args.args[1], ["active-1", "active-2"])

    def test_candidates_group_active_before_idle_and_hide_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            stale = (meight.now_kst()
                     - timedelta(seconds=meight.STATUS_ARCHIVE_AFTER_SEC + 60)).isoformat()
            self._worker(repo_home, "done-1", state="completed", terminal_at=meight.now_iso())
            self._worker(repo_home, "run-1")
            self._worker(repo_home, "old-1", state="completed", terminal_at=stale,
                         updated_at=stale)
            self._worker(repo_home, "ask-1", state="needs_input",
                         needs_input_source="question")
            rows = meight.watch_candidates(repo_home)
            # ask-1 precedes done-1 despite sorting after it: it needs an answer.
            self.assertEqual([(group, st["name"]) for group, st in rows],
                             [("active", "run-1"), ("idle", "ask-1"), ("idle", "done-1")])
            with_old = meight.watch_candidates(repo_home, include_archived=True)
            self.assertEqual(with_old[-1], ("archived", with_old[-1][1]))
            self.assertEqual(with_old[-1][1]["name"], "old-1")

    def test_menu_numbers_rows_under_group_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            self._worker(repo_home, "run-1")
            self._worker(repo_home, "done-1", state="completed", terminal_at=meight.now_iso())
            stream = io.StringIO()
            meight.print_watch_menu(meight.watch_candidates(repo_home), stream)
            out = stream.getvalue()
            self.assertIn("── active ──", out)
            self.assertIn("── idle — finished, or waiting on you ──", out)
            self.assertRegex(out, r"\n   1  run-1")
            self.assertRegex(out, r"\n   2  done-1")

    def test_menu_choice_accepts_a_number_and_rejects_anything_else(self):
        rows = [("active", {"name": "run-1"}), ("idle", {"name": "done-1"})]
        for typed, expected in ((" 2 \n", "done-1"), ("1\n", "run-1"),
                                ("\n", None), ("", None), ("q\n", None)):
            with self.subTest(typed=typed):
                stream = io.StringIO()
                # "q" is rejected, then EOF ends the retry loop.
                with patch.object(meight.sys, "stdin", io.StringIO(typed)), \
                        patch.object(meight, "print_watch_menu"):
                    self.assertEqual(meight.prompt_watch_choice(rows, stream), expected)
                if typed == "q\n":
                    self.assertIn("is not a number between 1 and 2", stream.getvalue())

    def test_menu_choice_survives_an_out_of_range_number(self):
        rows = [("active", {"name": "run-1"})]
        stream = io.StringIO()
        with patch.object(meight.sys, "stdin", io.StringIO("9\n1\n")), \
                patch.object(meight, "print_watch_menu"):
            self.assertEqual(meight.prompt_watch_choice(rows, stream), "run-1")
        self.assertIn("is not a number between 1 and 1", stream.getvalue())

    def test_watch_prompts_on_a_tty_and_falls_back_to_a_listing_on_a_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            self._worker(repo_home, "run-1")
            self._worker(repo_home, "run-2")
            parser = meight.build_parser()
            args = parser.parse_args(["watch"])

            with patch.object(meight, "repo_home_for_cli", return_value=repo_home), \
                    patch.object(meight, "run_watch", return_value=0) as run, \
                    patch.object(meight, "watch_can_prompt", return_value=True), \
                    patch.object(meight, "prompt_watch_choice", return_value="run-2"):
                self.assertEqual(meight.cmd_watch(args, Path(tmp)), 0)
            self.assertEqual(run.call_args.args[1], ["run-2"])

            # Leaving the menu without choosing is not an error.
            with patch.object(meight, "repo_home_for_cli", return_value=repo_home), \
                    patch.object(meight, "run_watch", return_value=0) as run, \
                    patch.object(meight, "watch_can_prompt", return_value=True), \
                    patch.object(meight, "prompt_watch_choice", return_value=None):
                self.assertEqual(meight.cmd_watch(args, Path(tmp)), 0)
            run.assert_not_called()

            with patch.object(meight, "repo_home_for_cli", return_value=repo_home), \
                    patch.object(meight, "run_watch", return_value=0) as run, \
                    patch.object(meight, "watch_can_prompt", return_value=False), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(meight.cmd_watch(args, Path(tmp)), 1)
            run.assert_not_called()
            self.assertIn("pick a worker by name", err.getvalue())
            self.assertIn("run-1", out.getvalue())

    def test_watch_reports_an_empty_repo_with_the_archive_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            parser = meight.build_parser()
            with patch.object(meight, "repo_home_for_cli", return_value=Path(tmp)), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(meight.cmd_watch(parser.parse_args(["watch"]), Path(tmp)), 1)
            self.assertIn("--include-archived", err.getvalue())


if __name__ == "__main__":
    unittest.main()
