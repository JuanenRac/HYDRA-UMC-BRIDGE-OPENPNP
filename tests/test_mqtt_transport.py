# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Real MQTT transport tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Tests OpenPnpMqttBridge's real (simulation-only) topic dispatch - pure
in-memory logic, no real MQTT broker, OpenPnP install or machine required."""

import json
import unittest

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_bridge_openpnp import OpenPnpMqttBridge
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX


def bridge(cell_state=CellState.READY):
    return OpenPnpMqttBridge(lambda: cell_state)


def job(board_id="board-1", phase=JobPhase.LOAD, machine_state=MachineState.IDLE):
    return BridgeJob("job-1", "key-1", "orchestrator", phase, machine_state, {"board_id": board_id})


class TopicRoutingTests(unittest.TestCase):
    def test_unknown_prefix_is_ignored(self):
        self.assertEqual(bridge().handle_message("some/other/topic", b""), [])

    def test_unrecognised_cmd_topic_is_ignored_not_an_error(self):
        self.assertEqual(bridge().handle_message(f"{TOPIC_PREFIX}cmd/move", b""), [])


class JobCommandTests(unittest.TestCase):
    def test_a_valid_job_against_a_ready_cell_is_allowed(self):
        publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", json.dumps(job_to_dict(job())).encode("utf-8"))
        self.assertEqual(publishes[0].topic, f"{TOPIC_PREFIX}cmd/job/result")
        decision = json.loads(publishes[0].payload)
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["handoff"], "robot-loads-board-into-pnp-fixture")

    def test_a_job_missing_board_id_fails_closed(self):
        job_without_board = BridgeJob("job-1", "key-1", "orchestrator", JobPhase.LOAD, MachineState.IDLE, {})
        publishes = bridge().handle_message(
            f"{TOPIC_PREFIX}cmd/job", json.dumps(job_to_dict(job_without_board)).encode("utf-8")
        )
        decision = json.loads(publishes[0].payload)
        self.assertFalse(decision["allowed"])
        self.assertIn("board_id", decision["reason"])

    def test_malformed_json_fails_closed_with_a_real_result_not_a_crash(self):
        publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", b"{not valid json")
        decision = json.loads(publishes[0].payload)
        self.assertFalse(decision["allowed"])
        self.assertIn("malformed job payload", decision["reason"])

    def test_abort_is_always_allowed(self):
        payload = job_to_dict(job(phase=JobPhase.ABORT, machine_state=MachineState.FAULT))
        publishes = bridge(cell_state=CellState.FAULT).handle_message(
            f"{TOPIC_PREFIX}cmd/job", json.dumps(payload).encode("utf-8")
        )
        self.assertTrue(json.loads(publishes[0].payload)["allowed"])


class HandoffCommandTests(unittest.TestCase):
    def _request(self, board_id="board-1", job_board_id="board-1"):
        return {
            "job": job_to_dict(job(board_id=job_board_id, phase=JobPhase.LOAD)),
            "identity": {"board_id": board_id, "recipe_id": "recipe-1", "revision": "r1", "lot_id": "lot-1"},
        }

    def test_a_matching_identity_produces_a_simulation_only_result(self):
        publishes = bridge().handle_message(
            f"{TOPIC_PREFIX}cmd/handoff", json.dumps(self._request()).encode("utf-8")
        )
        self.assertEqual(publishes[0].topic, f"{TOPIC_PREFIX}cmd/handoff/result")
        result = json.loads(publishes[0].payload)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["mode"], "simulation-only")
        self.assertIsNotNone(result["identity_fingerprint"])

    def test_a_mismatched_board_id_is_rejected(self):
        publishes = bridge().handle_message(
            f"{TOPIC_PREFIX}cmd/handoff",
            json.dumps(self._request(board_id="board-1", job_board_id="board-2")).encode("utf-8"),
        )
        result = json.loads(publishes[0].payload)
        self.assertFalse(result["allowed"])
        self.assertIsNone(result["identity_fingerprint"])

    def test_missing_identity_field_fails_closed_with_a_real_result_not_a_crash(self):
        request = self._request()
        del request["identity"]["lot_id"]
        publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", json.dumps(request).encode("utf-8"))
        result = json.loads(publishes[0].payload)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["mode"], "simulation-only")
        self.assertIn("malformed handoff payload", result["reason"])

    def test_malformed_json_fails_closed_with_a_real_result_not_a_crash(self):
        publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", b"{not valid")
        result = json.loads(publishes[0].payload)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["mode"], "simulation-only")


class RunForeverTests(unittest.TestCase):
    def test_missing_paho_mqtt_raises_a_clear_runtime_error_not_an_import_error(self):
        try:
            import paho.mqtt.client  # noqa: F401

            self.skipTest("paho-mqtt is installed in this environment - nothing to prove here")
        except ImportError:
            pass
        from hydra_umc_bridge_openpnp import run_forever

        with self.assertRaises(RuntimeError) as context:
            run_forever(bridge(), "127.0.0.1")
        self.assertIn("paho-mqtt is not installed", str(context.exception))


class ConnectWithRetryTests(unittest.TestCase):
    """connect_with_retry() is pure - no real paho-mqtt/broker needed to
    prove the real startup-race tolerance an ecosystem-wide software
    audit found missing here (this bridge's process used to die outright
    if it started before HYDRA-UMC-MQTT-BROKER was listening yet)."""

    def test_succeeds_on_the_first_try_without_sleeping(self):
        from hydra_umc_bridge_openpnp import connect_with_retry

        sleeps: list = []
        connect_with_retry(lambda: None, sleep=sleeps.append)
        self.assertEqual(sleeps, [])

    def test_retries_a_transient_connection_failure_then_succeeds(self):
        from hydra_umc_bridge_openpnp import connect_with_retry

        attempts = {"n": 0}
        sleeps: list = []

        def flaky_connect() -> None:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionRefusedError("broker not up yet")

        connect_with_retry(flaky_connect, max_attempts=5, retry_delay_seconds=1.5, sleep=sleeps.append)
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(sleeps, [1.5, 1.5])

    def test_gives_up_after_max_attempts_with_a_clear_error(self):
        from hydra_umc_bridge_openpnp import connect_with_retry

        def always_fails() -> None:
            raise ConnectionRefusedError("broker still not up")

        with self.assertRaises(RuntimeError) as context:
            connect_with_retry(always_fails, max_attempts=3, retry_delay_seconds=0.01, sleep=lambda _: None)
        self.assertIn("after 3 attempts", str(context.exception))
        self.assertIn("broker still not up", str(context.exception))

    def test_a_non_os_error_is_never_retried(self):
        from hydra_umc_bridge_openpnp import connect_with_retry

        def broken_connect() -> None:
            raise ValueError("not an OSError - a real bug, not a broker being down")

        with self.assertRaises(ValueError):
            connect_with_retry(broken_connect, sleep=lambda _: None)



if __name__ == "__main__":
    unittest.main()
