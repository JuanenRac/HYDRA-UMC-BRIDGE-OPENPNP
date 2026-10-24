# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Board code check tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The code printed on the board compared with the board of the job, and the VISION-NODE source."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_bridge_openpnp import BoardTraceRecorder, OpenPnpMqttBridge, VisionNodeCodeSource, board_code_mode_from_environment, check_board_code
from hydra_umc_bridge_openpnp.board_code import clean_codes
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX


class CheckTests(unittest.TestCase):
    def test_off_believes_the_job(self):
        check = check_board_code("PCB-1", ["PCB-2"], "off")
        self.assertEqual((check.outcome, check.allowed, check.board_id), ("skipped", True, "PCB-1"))

    def test_the_code_of_the_job_matches(self):
        check = check_board_code("PCB-1", ["PCB-1"], "required")
        self.assertEqual((check.outcome, check.allowed), ("match", True))

    def test_another_code_is_a_mismatch_in_both_strict_modes(self):
        for mode in ("advisory", "required"):
            with self.subTest(mode=mode):
                check = check_board_code("PCB-1", ["PCB-2"], mode)
                self.assertEqual((check.outcome, check.allowed), ("mismatch", False))
                self.assertIn("PCB-2", check.reason)
                self.assertIn("PCB-1", check.reason)

    def test_no_code_is_refused_only_when_required(self):
        self.assertTrue(check_board_code("PCB-1", [], "advisory").allowed)
        required = check_board_code("PCB-1", [], "required")
        self.assertFalse(required.allowed)
        self.assertEqual(required.outcome, "no_code")

    def test_a_job_with_no_board_takes_the_single_code(self):
        check = check_board_code(None, ["PCB-9"], "advisory")
        self.assertEqual((check.outcome, check.allowed, check.board_id), ("filled", True, "PCB-9"))

    def test_a_job_with_no_board_and_no_code_is_refused(self):
        self.assertFalse(check_board_code(None, [], "advisory").allowed)

    def test_several_different_codes_cannot_tell_which_board_it_is(self):
        self.assertFalse(check_board_code(None, ["A-1", "B-2"], "advisory").allowed)
        self.assertFalse(check_board_code("A-1", ["A-1", "B-2"], "advisory").allowed)

    def test_the_same_code_read_twice_is_one_code(self):
        self.assertEqual(check_board_code("A-1", ["A-1", "A-1", " A-1 "], "required").outcome, "match")

    def test_what_is_not_a_board_identifier_is_not_a_code(self):
        junk = ["", "has space", "../etc", "<script>", "x" * 200, 5, None, b"A-1", "A\nB"]
        self.assertEqual(clean_codes(junk), [])
        self.assertEqual(clean_codes("A-1"), [])
        self.assertEqual(clean_codes([f"C-{i}" for i in range(40)]), [f"C-{i}" for i in range(16)])
        self.assertFalse(check_board_code("PCB-1", junk, "required").allowed)

    def test_an_unknown_mode_is_an_error(self):
        with self.assertRaises(ValueError):
            check_board_code("A", ["A"], "sometimes")

    def test_the_mode_comes_from_the_environment_and_defaults_to_off(self):
        self.assertEqual(board_code_mode_from_environment({}), "off")
        self.assertEqual(board_code_mode_from_environment({"HYDRA_UMC_OPENPNP_BOARD_CODE": "Required"}), "required")
        self.assertEqual(board_code_mode_from_environment({"HYDRA_UMC_OPENPNP_BOARD_CODE": "banana"}), "off")


def job_message(phase=JobPhase.LOAD, board="PCB-1", key="k-1"):
    parameters = {} if board is None else {"board_id": board}
    return json.dumps(job_to_dict(BridgeJob("j-1", key, "orchestrator", phase, MachineState.IDLE, parameters))).encode()


def handoff_message(phase, board="PCB-1", key="h-1"):
    request = {
        "job": job_to_dict(BridgeJob("j-1", key, "orchestrator", phase, MachineState.IDLE, {"board_id": board})),
        "identity": {"board_id": board, "recipe_id": "R", "revision": "A", "lot_id": "L"},
    }
    return json.dumps(request).encode()


def bridge(codes, mode):
    return OpenPnpMqttBridge(lambda: CellState.READY, code_source=lambda: codes, code_mode=mode)


def ask(b, payload):
    return json.loads(b.handle_message(f"{TOPIC_PREFIX}cmd/job", payload)[0].payload)


class BridgeTests(unittest.TestCase):
    def test_a_board_with_another_code_is_refused_at_the_gate(self):
        answer = ask(bridge(["PCB-2"], "required"), job_message(JobPhase.LOAD, "PCB-1"))
        self.assertFalse(answer["allowed"])
        self.assertEqual(answer["code_check"]["outcome"], "mismatch")
        self.assertIn("PCB-2", answer["reason"])

    def test_the_right_board_goes_through(self):
        answer = ask(bridge(["PCB-1"], "required"), job_message(JobPhase.LOAD, "PCB-1"))
        self.assertTrue(answer["allowed"])
        self.assertEqual(answer["code_check"]["outcome"], "match")

    def test_a_job_without_a_board_is_filled_from_the_code(self):
        answer = ask(bridge(["PCB-7"], "advisory"), job_message(JobPhase.PREPARE, None))
        self.assertTrue(answer["allowed"])
        self.assertEqual(answer["code_check"], {"outcome": "filled", "board_id": "PCB-7"})

    def test_a_job_without_a_board_and_without_a_code_is_still_malformed(self):
        answer = ask(bridge([], "advisory"), job_message(JobPhase.PREPARE, None))
        self.assertFalse(answer["allowed"])
        self.assertIn("board_id", answer["reason"])

    def test_off_is_the_old_behaviour_even_with_a_source(self):
        answer = ask(bridge(["PCB-2"], "off"), job_message(JobPhase.LOAD, "PCB-1"))
        self.assertTrue(answer["allowed"])
        self.assertNotIn("code_check", answer)

    def test_a_mode_without_a_source_is_off(self):
        answer = ask(OpenPnpMqttBridge(lambda: CellState.READY, code_mode="required"), job_message(JobPhase.LOAD, "PCB-1"))
        self.assertTrue(answer["allowed"])

    def test_only_the_phases_in_which_a_board_arrives_are_checked(self):
        for phase in (JobPhase.PROCESS, JobPhase.UNLOAD, JobPhase.COMPLETE):
            with self.subTest(phase=phase):
                answer = ask(bridge(["PCB-2"], "required"), job_message(phase, "PCB-1"))
                self.assertTrue(answer["allowed"])
                self.assertNotIn("code_check", answer)

    def test_abort_is_never_held_back_by_a_code(self):
        answer = ask(bridge(["PCB-2"], "required"), job_message(JobPhase.ABORT, "PCB-1"))
        self.assertTrue(answer["allowed"])

    def test_a_source_that_raises_is_a_code_that_was_not_read(self):
        def broken():
            raise RuntimeError("camera")

        b = OpenPnpMqttBridge(lambda: CellState.READY, code_source=broken, code_mode="required")
        self.assertFalse(ask(b, job_message(JobPhase.LOAD, "PCB-1"))["allowed"])
        advisory = OpenPnpMqttBridge(lambda: CellState.READY, code_source=broken, code_mode="advisory")
        self.assertTrue(ask(advisory, job_message(JobPhase.LOAD, "PCB-1"))["allowed"])

    def test_the_handoff_is_refused_without_a_fingerprint_for_the_wrong_board(self):
        b = bridge(["PCB-2"], "required")
        answer = json.loads(b.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_message(JobPhase.LOAD))[0].payload)
        self.assertFalse(answer["allowed"])
        self.assertIsNone(answer["identity_fingerprint"])
        self.assertEqual(answer["code_check"]["outcome"], "mismatch")
        ok = json.loads(bridge(["PCB-1"], "required").handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_message(JobPhase.LOAD))[0].payload)
        self.assertTrue(ok["allowed"])
        self.assertIsNotNone(ok["identity_fingerprint"])

    def test_the_trace_records_the_refusal(self):
        recorder = BoardTraceRecorder()
        b = OpenPnpMqttBridge(lambda: CellState.READY, code_source=lambda: ["PCB-2"], code_mode="required", trace_recorder=recorder)
        b.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_message(JobPhase.LOAD))
        (record,) = recorder._open.values()  # noqa: SLF001
        self.assertFalse(record.steps[0].allowed)


class FakeVisionNode(BaseHTTPRequestHandler):
    seen: list = []
    reply = (200, {"codes": ["PCB-1"]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        type(self).seen.append((self.path, self.headers.get("Authorization"), self.rfile.read(length)))
        status, body = type(self).reply
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class VisionNodeSourceTests(unittest.TestCase):
    def setUp(self):
        FakeVisionNode.seen, FakeVisionNode.reply = [], (200, {"codes": ["PCB-1"]})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVisionNode)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.frame = lambda: (b"\x00" * 12, 2, 2, 3)

    def test_it_sends_the_frame_and_returns_the_codes(self):
        source = VisionNodeCodeSource(self.url, self.frame, token="a-token")
        self.assertEqual(source(), ["PCB-1"])
        path, authorization, body = FakeVisionNode.seen[0]
        self.assertEqual(path, "/read-code?width=2&height=2&channels=3")
        self.assertEqual(authorization, "Bearer a-token")
        self.assertEqual(body, b"\x00" * 12)

    def test_a_reply_that_is_not_codes_is_no_code(self):
        for reply in ((500, {"error": "x"}), (200, {"codes": "PCB-1"}), (200, ["PCB-1"]), (200, {"codes": ["has space", 5]}), (200, {})):
            with self.subTest(reply=reply):
                FakeVisionNode.reply = reply
                self.assertEqual(VisionNodeCodeSource(self.url, self.frame)(), [])

    def test_a_camera_that_fails_is_no_code(self):
        def broken():
            raise OSError("no camera")

        self.assertEqual(VisionNodeCodeSource(self.url, broken)(), [])

    def test_a_service_that_is_down_is_no_code(self):
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(VisionNodeCodeSource(self.url, self.frame, timeout_s=0.5)(), [])

    def test_the_url_must_be_http(self):
        with self.assertRaises(ValueError):
            VisionNodeCodeSource("file:///x", self.frame)

    def test_an_oversized_reply_is_no_code(self):
        source = VisionNodeCodeSource("http://x", self.frame, post=lambda url, body, headers: (200, b"{" + b" " * 70_000 + b"}"))
        self.assertEqual(source(), [])


if __name__ == "__main__":
    unittest.main()
