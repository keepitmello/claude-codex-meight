import json
import tempfile
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
            with patch.object(meight, "send_request", return_value={"ok": True}) as send:
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


if __name__ == "__main__":
    unittest.main()
