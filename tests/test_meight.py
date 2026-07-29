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
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import meight


class ModelAliasTests(unittest.TestCase):
    def test_known_aliases_and_custom_model_pass_through(self):
        self.assertEqual(meight.normalize_model("sol"), "gpt-5.6-sol")
        self.assertEqual(meight.normalize_model("terra"), "gpt-5.6-terra")
        self.assertEqual(meight.normalize_model("luna"), "gpt-5.6-luna")
        self.assertEqual(meight.normalize_model("vendor/custom-model"), "vendor/custom-model")
        self.assertIsNone(meight.normalize_model(None))


class StartDefaultsTests(unittest.TestCase):
    EXPECTED = {
        "mate": ("gpt-5.6-sol", "medium", "default", "full"),
        "worker": ("gpt-5.6-luna", "max", "default", "full"),
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
             "protocol_epoch": meight.PROTOCOL_EPOCH},
        )
        with patch.object(meight, "send_request", side_effect=responses) as send:
            response = meight.start_request(args, Path("/tmp/meight-defaults"))
        self.assertTrue(response["ok"])
        return send.call_args_list[1].args[1]

    def test_each_mode_resolves_omitted_start_flags_on_the_cli_wire(self):
        for mode, expected in self.EXPECTED.items():
            with self.subTest(mode=mode):
                request = self._start_request(self._args("start", mode))
                model, effort, tier, sandbox = expected
                self.assertEqual(
                    (request["model"], request["effort"], request["service_tier"],
                     request["sandbox"]),
                    (model, effort, tier, sandbox),
                )
                self.assertEqual(request["mode"], mode)

    def test_legacy_alias_modes_resolve_to_posture_defaults_on_the_wire(self):
        for alias, canonical in (("design", "mate"), ("review", "mate"), ("delegate", "worker")):
            with self.subTest(alias=alias):
                request = self._start_request(self._args("start", alias))
                model, effort, tier, sandbox = self.EXPECTED[canonical]
                self.assertEqual(
                    (request["model"], request["effort"], request["service_tier"],
                     request["sandbox"]),
                    (model, effort, tier, sandbox),
                )
                self.assertEqual(request["mode"], canonical)

    def test_explicit_flags_override_every_mode_default(self):
        args = self._args(
            "start", "mate", "--model", "terra", "--effort", "max",
            "--fast", "--sandbox", "ro",
        )
        request = self._start_request(args)
        self.assertEqual(
            (request["model"], request["effort"], request["service_tier"],
             request["sandbox"]),
            ("gpt-5.6-terra", "max", "priority", "ro"),
        )

    def test_fast_overrides_worker_fast_default(self):
        request = self._start_request(self._args("start", "worker", "--fast"))
        self.assertEqual(request["service_tier"], "priority")

    def test_dispatch_uses_the_same_resolution_and_start_path(self):
        start_args = self._args("start", "worker", "--model", "sol", "--fast")
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
            "effort=max(default) fast=on(set) sandbox=full(default)",
            output.getvalue(),
        )


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
                "start", f"effort-{effort}", "--mode", "worker",
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

            with patch.object(meight, "CAPACITY_RETRY_DELAYS_SEC", (0, 0, 0, 0, 0)):
                worker.consume_stream(
                    meight.Daemon(home), worker.generation, self._capacity_handle()
                )

            result = (worker.dir / "result.md").read_text(encoding="utf-8")
            self.assertEqual(worker.status["state"], "completed")
            self.assertEqual(worker.status["capacity_retries"], 1)
            self.assertEqual(result.strip(), "OK")
            self.assertEqual(len(thread.calls), 1)
            self.assertEqual(thread.calls[0][0], meight.CAPACITY_RETRY_PROMPT)
            self.assertEqual(thread.calls[0][1]["service_tier"], "default")

    def test_capacity_failure_stops_after_five_retries(self):
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
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-1")
            worker.generation = 1
            thread = RetryThread([self._capacity_handle() for _ in range(5)])
            worker.thread = thread

            with patch.object(meight, "CAPACITY_RETRY_DELAYS_SEC", (0, 0, 0, 0, 0)):
                worker.consume_stream(
                    meight.Daemon(home), worker.generation, self._capacity_handle()
                )

            result = (worker.dir / "result.md").read_text(encoding="utf-8")
            events = (worker.dir / "events.log").read_text(encoding="utf-8")
            self.assertEqual(worker.status["state"], "failed")
            self.assertEqual(worker.status["capacity_retries"], 5)
            self.assertEqual(thread.calls, 5)
            self.assertIn("Selected model is at capacity", result)
            self.assertIn("[capacity/exhausted] failed after 5 retries", events)


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
            "start", "mode-test", "--mode", mode,
            "--brief", "Review the contract.", "--cwd", cwd,
        ])

    def test_final_question_releases_runtime_but_preserves_resumable_status(self):
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

    def test_follow_rehydrates_dormant_worker_and_resumes_saved_thread(self):
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
            resumed = []

            class FakeCodex:
                def __init__(self, config):
                    self.config = config

                def thread_resume(self, thread_id, **kwargs):
                    resumed.append((thread_id, kwargs))
                    return capture_thread

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
                    "brief": "Continue from the saved question.",
                    **context,
                })

            self.assertTrue(response["ok"], response)
            self.assertEqual(response["thread_id"], "thread-resume")
            self.assertEqual(resumed, [(
                "thread-resume",
                {
                    "cwd": "/repo",
                    "sandbox": "workspace_write",
                    "service_tier": None,
                },
            )])
            restored = daemon.workers[
                meight.registry_key(context["repo_key"], worker.name)
            ]
            self.assertEqual(restored.status["turns"], 2)
            self.assertEqual(restored.status["state"], "starting")
            self.assertEqual(capture_thread.turn_kwargs[0]["model"], "gpt-5.6-sol")

    def test_follow_recovers_legacy_ephemeral_worker_into_persistent_subagent(self):
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
                    raise AssertionError("legacy ephemeral worker must not call thread_resume")

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
            self.assertEqual(started[0]["ephemeral"], False)
            self.assertEqual(started[0]["thread_source"], "subagent")
            self.assertIn("Original legacy brief.", capture_thread.inputs[0])
            self.assertIn("Work stopped after schema changes.", capture_thread.inputs[0])
            self.assertIn("Finish the implementation.", capture_thread.inputs[0])
            restored = daemon.workers[
                meight.registry_key(context["repo_key"], worker.name)
            ]
            self.assertEqual(restored.status["thread_id"], "thread-mode-test")
            self.assertEqual(restored.status["recovered_from_thread_id"], "thread-legacy")
            self.assertFalse(restored.status["thread_ephemeral"])

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
                    "start", "mode-teaching", "--brief", "No side effects.", *mode_args,
                ])
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    meight.start_request(args, Path("/tmp/meight-mode-teaching"))
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(stderr.getvalue().strip(), meight.MODE_TEACHING_ERROR)

    def test_single_axis_mode_validation_precedes_side_effects(self):
        parser = meight.build_parser()
        for command in ("start", "dispatch"):
            for mode_args in ([], ["--mode", "invalid"]):
                with self.subTest(command=command, mode_args=mode_args):
                    args = parser.parse_args([
                        command, "mode-precedence", "--brief", "No side effects.", *mode_args,
                    ])
                    stderr = io.StringIO()
                    call = meight.start_request if command == "start" else meight.cmd_dispatch
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

    def test_start_output_echoes_resolved_defaults_and_provenance(self):
        cases = (
            ("worker",
             "model=luna(default) effort=max(default) fast=off(default) "
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
                    patch.object(meight, "start_request", return_value=response),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(meight.cmd_start(args, Path("/tmp/meight-output")), 0)
                self.assertIn(f"mode={mode} {settings}", output.getvalue())

    def test_start_output_marks_explicit_flags_as_set(self):
        args = meight.build_parser().parse_args([
            "start", "mode-test", "--mode", "worker", "--brief", "Implement.",
            "--model", "sol", "--effort", "high", "--fast",
            "--sandbox", "ro",
        ])
        response = {
            "ok": True, "thread_id": "thread-worker", "mode": "worker",
            "protocol_epoch": meight.PROTOCOL_EPOCH,
        }
        output = io.StringIO()
        with (
            patch.object(meight, "start_request", return_value=response),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(meight.cmd_start(args, Path("/tmp/meight-output")), 0)
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

                stderr = io.StringIO()
                with (
                    patch.object(meight, "send_request", side_effect=swapped_daemon),
                    contextlib.redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as error,
                ):
                    meight.cmd_start(args, home)

                self.assertEqual(error.exception.code, 1)
                self.assertEqual(
                    stderr.getvalue().strip(),
                    "error: start protocol mismatch: "
                    f"expected mode=mate epoch={meight.PROTOCOL_EPOCH}",
                )
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
                         f"expected mode=worker epoch={meight.PROTOCOL_EPOCH}",
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
                             f"expected mode=mate epoch={meight.PROTOCOL_EPOCH}",
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
            self.assertFalse(status["thread_ephemeral"])
            self.assertNotIn("output_schema", capture_thread.turn_kwargs[0])
            self.assertIn("skills/meight-mate/SKILL.md", capture_thread.inputs[0])


if __name__ == "__main__":
    unittest.main()
