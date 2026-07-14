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
                "start", f"effort-{effort}", "--role", "worker", "--mode", "delegate",
                "--brief", "Say OK", "--effort", effort,
            ])
            responses = ({"ok": True, "capabilities": ["role"]},
                         {"ok": True, "role": "worker"})
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
                        mode="delegated", report="decision",
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


class RoleLifecycleTests(unittest.TestCase):
    class _EmptyHandle:
        def stream(self):
            return iter(())

        def interrupt(self):
            return None

    class _CaptureThread:
        def __init__(self):
            self.id = "thread-role-test"
            self.inputs = []

        def turn(self, turn_input, **kwargs):
            self.inputs.append(turn_input)
            return RoleLifecycleTests._EmptyHandle()

    def _start_args(self, cwd: str, role: str = "mate"):
        return meight.build_parser().parse_args([
            "start", "role-test", "--role", role, "--mode", "delegate",
            "--brief", "Review the contract.", "--cwd", cwd,
        ])

    def test_role_maps_to_role_skill_and_common_contract(self):
        for role, directory in (("mate", "meight-mate"), ("worker", "meight-worker")):
            with self.subTest(role=role):
                preamble = meight.build_preamble(role, "delegated", "decision")
                self.assertIn(f"skills/{directory}/SKILL.md", preamble)
                self.assertIn("skills/meight-common/CONTRACT.md", preamble)
                self.assertIn(f"role: {role}", preamble)

    def test_daemon_rejects_missing_or_invalid_role_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            for role in (None, "reviewer"):
                with self.subTest(role=role):
                    req = {"cmd": "start", "mode": "delegate"}
                    if role is not None:
                        req["role"] = role
                    response = daemon._dispatch(req)
                    self.assertFalse(response["ok"])
                    self.assertIn("--role is required", response["error"])
                    self.assertEqual(daemon.workers, {})
                    self.assertFalse((home / "repos").exists())

    def test_daemon_role_teaching_error_precedes_mode_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            for req in (
                {"cmd": "start"},
                {"cmd": "start", "role": "reviewer", "mode": "invalid"},
            ):
                with self.subTest(req=req):
                    response = daemon._dispatch(req)
                    self.assertFalse(response["ok"])
                    self.assertIn("--role is required", response["error"])
                    self.assertEqual(daemon.workers, {})
                    self.assertFalse((home / "repos").exists())

    def test_cli_missing_and_invalid_role_share_teaching_error(self):
        parser = meight.build_parser()
        for role_args in ([], ["--role", "reviewer"]):
            with self.subTest(role_args=role_args):
                args = parser.parse_args([
                    "start", "role-teaching", "--mode", "delegate",
                    "--brief", "No side effects.", *role_args,
                ])
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                    meight.start_request(args, Path("/tmp/meight-role-teaching"))
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(stderr.getvalue().strip(), meight.ROLE_TEACHING_ERROR)

    def test_cli_role_teaching_error_precedes_mode_error(self):
        parser = meight.build_parser()
        for command in ("start", "dispatch"):
            for role_args, mode_args in (
                ([], []),
                (["--role", "reviewer"], ["--mode", "invalid"]),
            ):
                with self.subTest(command=command, role_args=role_args, mode_args=mode_args):
                    args = parser.parse_args([
                        command, "role-precedence", "--brief", "No side effects.",
                        *role_args, *mode_args,
                    ])
                    stderr = io.StringIO()
                    call = meight.start_request if command == "start" else meight.cmd_dispatch
                    with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                        call(args, Path("/tmp/meight-role-precedence"))
                    self.assertEqual(error.exception.code, 2)
                    self.assertEqual(stderr.getvalue().strip(), meight.ROLE_TEACHING_ERROR)

    def test_follow_and_reply_path_inherit_recorded_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo_home = home / "repos" / "repo-key"
            worker = meight.Worker(
                "inherit-role", repo_home, "/repo", "repo-key", "/repo",
                "workspace_write", "gpt-5.6-sol", "high",
                role="mate", mode="delegated", report="decision",
            )
            worker.dir.mkdir(parents=True)
            worker.init_status(thread_id="thread-role-test")
            worker.status["state"] = "needs_input"
            worker.status["needs_input_source"] = "question"
            worker.write_status(force=True)
            thread = self._CaptureThread()
            worker.thread = thread

            daemon = meight.Daemon(home)
            daemon.workers[meight.registry_key("repo-key", "inherit-role")] = worker
            response = daemon.cmd_follow({
                "name": "inherit-role",
                "brief": "Use the recommended correction.",
                "repo_key": "repo-key",
                "repo_root": "/repo",
                "repo_home": str(repo_home),
            })
            if worker.consumer is not None:
                worker.consumer.join(timeout=2)

            self.assertTrue(response["ok"])
            self.assertEqual(response["role"], "mate")
            self.assertEqual(worker.status["role"], "mate")
            self.assertIn("skills/meight-mate/SKILL.md", thread.inputs[0])
            self.assertIn("skills/meight-common/CONTRACT.md", thread.inputs[0])

    def test_status_table_has_role_column(self):
        status = {
            "name": "review-1",
            "state": "running",
            "role": "mate",
            "mode": "delegated",
            "started_at": meight.now_iso(),
            "updated_at": meight.now_iso(),
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            meight.print_status_table([status])
        self.assertIn("ROLE", output.getvalue().splitlines()[0])
        self.assertIn("mate", output.getvalue().splitlines()[1])

    def test_legacy_status_without_role_renders_without_crash(self):
        status = {
            "name": "legacy",
            "state": "completed",
            "mode": "delegated",
            "started_at": meight.now_iso(),
            "updated_at": meight.now_iso(),
        }
        line = meight.summary_line(status)
        self.assertIn("legacy", line)
        self.assertEqual(line.split()[2], "-")

    def test_missing_role_capability_fails_before_start_request(self):
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
                "error": "daemon predates --role; restart required",
            })
            self.assertEqual(requests, [{"cmd": "ping"}])
            self.assertFalse((home / "repos").exists())

    def test_missing_or_mismatched_start_role_echo_fails_and_interrupts(self):
        for echo in (None, "worker"):
            with self.subTest(echo=echo), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                args = self._start_args(tmp, role="mate")
                requests = []

                def swapped_daemon(_home, req, timeout=meight.SOCKET_TIMEOUT_SEC):
                    requests.append(req)
                    if req["cmd"] == "ping":
                        return {"ok": True, "capabilities": ["role"]}
                    if req["cmd"] == "start":
                        response = {"ok": True, "thread_id": "old-daemon-worker"}
                        if echo is not None:
                            response["role"] = echo
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
                    "error: legacy daemon accepted the start without role support",
                )
                self.assertEqual([req["cmd"] for req in requests], ["ping", "start", "interrupt"])
                self.assertEqual(requests[2]["name"], args.name)
                for key in ("repo_root", "repo_key", "repo_home"):
                    self.assertEqual(requests[2][key], requests[1][key])

    def test_ping_and_runtime_status_advertise_role_capability(self):
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
            self.assertIn("role", ping["capabilities"])
            self.assertIn("role", runtime["capabilities"])

    def test_advertised_role_capability_starts_and_records_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            daemon = meight.Daemon(home)
            args = self._start_args(tmp, role="mate")
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
            self.assertEqual(response["role"], "mate")
            repo_home = Path(meight.repo_context(home)["repo_home"])
            status_path = repo_home / "workers" / "role-test" / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["role"], "mate")
            self.assertIn("skills/meight-mate/SKILL.md", capture_thread.inputs[0])


if __name__ == "__main__":
    unittest.main()
