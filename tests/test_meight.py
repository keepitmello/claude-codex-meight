import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import meight


class ModelAliasTests(unittest.TestCase):
    def test_known_aliases_and_custom_model_pass_through(self):
        self.assertEqual(meight.normalize_model("sol"), "gpt-5.6-sol")
        self.assertEqual(meight.normalize_model("terra"), "gpt-5.6-terra")
        self.assertEqual(meight.normalize_model("luna"), "gpt-5.6-luna")
        self.assertEqual(meight.normalize_model("vendor/custom-model"), "vendor/custom-model")
        self.assertIsNone(meight.normalize_model(None))


class EffortTests(unittest.TestCase):
    def test_ultra_and_max_parse_and_reach_start_request(self):
        parser = meight.build_parser()
        for effort in ("ultra", "max"):
            args = parser.parse_args([
                "start", f"effort-{effort}", "--mode", "delegate",
                "--brief", "Say OK", "--effort", effort,
            ])
            responses = ({"ok": True, "capabilities": ["mode3"]},
                         {"ok": True, "mode": "delegate"})
            with patch.object(meight, "send_request", side_effect=responses) as send:
                meight.start_request(args, Path("/tmp/meight-test"))
            self.assertEqual(send.call_args.args[1]["effort"], effort)

    def test_dynamic_efforts_are_accepted_by_installed_sdk_params(self):
        from openai_codex.generated.v2_all import TurnStartParams

        for effort in ("ultra", "max"):
            meight.allow_dynamic_sdk_effort(effort)
            params = TurnStartParams(thread_id="thread", input=[], effort=effort)
            self.assertEqual(params.model_dump(mode="json")["effort"], effort)


class TerminalErrorTests(unittest.TestCase):
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


class DecisionRoutingTests(unittest.TestCase):
    def test_needs_decision_routes_user_entry_before_dispatcher_fallback(self):
        cases = (
            (
                "dispatcher-first-user-later",
                [
                    {"target": "dispatcher", "kind": "technical"},
                    {"target": "user", "kind": "scope"},
                ],
                "user",
                "scope",
            ),
            (
                "all-dispatcher",
                [
                    {"target": "dispatcher", "kind": "technical"},
                    {"target": "dispatcher", "kind": "risk"},
                ],
                "dispatcher",
                "technical",
            ),
            (
                "single-user",
                [{"target": "user", "kind": "acceptance"}],
                "user",
                "acceptance",
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo_home = Path(tmp)
            for name, decisions, expected_target, expected_kind in cases:
                with self.subTest(name=name):
                    worker = meight.Worker(
                        name, repo_home, "/repo", "repo-key", "/repo",
                        "workspace_write", "gpt-5.6-sol", "medium",
                        mode="delegate", report="decision",
                    )
                    worker.dir.mkdir(parents=True)
                    worker.init_status(thread_id="thread-1")
                    worker._last_agent_msg = json.dumps({
                        "outcome": "needs_decision",
                        "decisions": decisions,
                    })

                    worker._on_turn_completed({"status": "completed"})

                    self.assertEqual(worker.status["state"], "needs_input")
                    self.assertEqual(worker.status["needs_input_source"], "question")
                    self.assertEqual(worker.status["needs_input_target"], expected_target)
                    self.assertEqual(worker.status["needs_input_kind"], expected_kind)


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

        def turn(self, turn_input, **kwargs):
            self.inputs.append(turn_input)
            return ModeLifecycleTests._EmptyHandle()

    def _start_args(self, cwd: str, mode: str = "review"):
        return meight.build_parser().parse_args([
            "start", "mode-test", "--mode", mode,
            "--brief", "Review the contract.", "--cwd", cwd,
        ])

    def test_each_mode_maps_to_expected_skill_and_common_contract(self):
        for mode, directory in (
            ("design", "meight-mate"),
            ("delegate", "meight-worker"),
            ("review", "meight-mate"),
        ):
            with self.subTest(mode=mode):
                preamble = meight.build_preamble(mode, "decision")
                self.assertIn(f"skills/{directory}/SKILL.md", preamble)
                self.assertIn("skills/meight-common/CONTRACT.md", preamble)
                self.assertIn(f"mode: {mode}", preamble)
                self.assertNotIn("role:", preamble)
        review = meight.build_preamble("review", "decision")
        for duty in ("verdict-first", "noise suppression", "incremental re-review", "reviewed-input identity"):
            self.assertIn(duty, review)

    def test_mode_aliases_normalize_and_review_has_no_alias(self):
        self.assertEqual(meight.normalize_mode("design"), "design")
        self.assertEqual(meight.normalize_mode("collab"), "design")
        self.assertEqual(meight.normalize_mode("collaborative"), "design")
        self.assertEqual(meight.normalize_mode("delegate"), "delegate")
        self.assertEqual(meight.normalize_mode("delegated"), "delegate")
        self.assertEqual(meight.normalize_mode("review"), "review")
        self.assertIsNone(meight.normalize_mode("reviewer"))

    def test_daemon_rejects_missing_or_invalid_mode_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            for mode in (None, "reviewer"):
                with self.subTest(mode=mode):
                    req = {"cmd": "start"}
                    if mode is not None:
                        req["mode"] = mode
                    response = daemon._dispatch(req)
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["error"], meight.MODE_TEACHING_ERROR.removeprefix("error: "))
                    self.assertEqual(daemon.workers, {})
                    self.assertFalse((home / "repos").exists())

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
            repo_home = home / "repos" / "repo-key"
            worker = meight.Worker(
                "inherit-mode", repo_home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "high",
                mode="review", report="decision",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-mode-test")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            thread = self._CaptureThread()
            worker.thread = thread

            daemon = meight.Daemon(home)
            daemon.workers[meight.registry_key("repo-key", "inherit-mode")] = worker
            response = daemon.cmd_follow({
                "name": "inherit-mode",
                "brief": "Use the recommended correction.",
                "repo_key": "repo-key",
                "repo_root": "/repo",
                "repo_home": str(repo_home),
            })
            if worker.consumer is not None:
                worker.consumer.join(timeout=2)

            self.assertTrue(response["ok"])
            self.assertEqual(response["mode"], "review")
            self.assertEqual(worker.status["mode"], "review")
            self.assertIn("skills/meight-mate/SKILL.md", thread.inputs[0])
            self.assertIn("skills/meight-common/CONTRACT.md", thread.inputs[0])
            for duty in ("verdict-first", "noise-suppressed", "incremental review",
                         "reviewed-input identity"):
                self.assertIn(duty, thread.inputs[0])

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
        self.assertIn("review", output.getvalue().splitlines()[1])

    def test_legacy_rows_with_role_and_old_modes_render_without_crash(self):
        for old_mode, expected in (("collaborative", "design"), ("delegated", "delegate")):
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

    def test_missing_mode3_capability_fails_before_start_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            args = self._start_args(tmp)
            requests = []

            def old_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                requests.append(req)
                return {"ok": True, "pid": 1234}

            with patch.object(meight, "send_request", side_effect=old_daemon):
                response = meight.start_request(args, home)

            self.assertEqual(response, {
                "ok": False,
                "error": "daemon predates --mode review; restart required",
            })
            self.assertEqual(requests, [{"cmd": "ping"}])
            self.assertFalse((home / "repos").exists())

    def test_missing_or_mismatched_start_mode_echo_fails_and_interrupts(self):
        for echo in (None, "delegate"):
            with self.subTest(echo=echo), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                args = self._start_args(tmp, mode="review")
                requests = []

                def swapped_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                    requests.append(req)
                    if req["cmd"] == "ping":
                        return {"ok": True, "capabilities": ["mode3"]}
                    if req["cmd"] == "start":
                        response = {"ok": True, "thread_id": "old-daemon-worker"}
                        if echo is not None:
                            response["mode"] = echo
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
                    "error: legacy daemon accepted the start without mode3 support",
                )
                self.assertEqual([req["cmd"] for req in requests], ["ping", "start", "interrupt"])
                self.assertEqual(requests[2]["name"], args.name)
                for key in ("repo_root", "repo_key", "repo_home"):
                    self.assertEqual(requests[2][key], requests[1][key])

    def test_missing_or_mismatched_follow_mode_echo_fails_and_interrupts(self):
        for echo in (None, "delegate"):
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
                        if echo is not None:
                            response["mode"] = echo
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
                    "error": "legacy daemon accepted the follow without mode3 support",
                })
                self.assertEqual([req["cmd"] for req in requests], ["follow", "interrupt"])
                self.assertEqual(requests[1]["name"], args.name)

    def test_ping_and_runtime_status_advertise_mode3_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            ping = daemon._dispatch({"cmd": "ping"})
            runtime = daemon.cmd_runtime_status({
                "name": "unknown",
                "repo_key": "repo-key",
                "repo_root": "/repo",
                "repo_home": str(home / "repos" / "repo-key"),
            })
            self.assertIn("mode3", ping["capabilities"])
            self.assertIn("mode3", runtime["capabilities"])

    def test_advertised_mode3_capability_starts_and_records_mode(self):
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
                patch.object(meight, "allow_dynamic_sdk_effort"),
            ):
                response = meight.start_request(args, home)

            self.assertTrue(response["ok"])
            self.assertEqual(response["mode"], "review")
            repo_home = Path(meight.repo_context(home)["repo_home"])
            status_path = repo_home / "workers" / "mode-test" / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertNotIn("role", status)
            self.assertEqual(status["mode"], "review")
            self.assertIn("skills/meight-mate/SKILL.md", capture_thread.inputs[0])


if __name__ == "__main__":
    unittest.main()
