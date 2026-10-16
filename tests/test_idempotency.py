# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Retained messages and repeated idempotency keys
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""docs/BRIDGE_CONTRACT.md: a retained message is not a request, and an idempotency key is handled once."""

import json
import unittest

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_sdk.job_intake import IdempotencyStore
from hydra_umc_bridge_openpnp import OpenPnpMqttBridge
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX


def message(key="key-1", board_id="board-1"):
    job = BridgeJob("job-1", key, "orchestrator", JobPhase.LOAD, MachineState.IDLE, {"board_id": board_id})
    return json.dumps(job_to_dict(job)).encode("utf-8")


class RetainedTests(unittest.TestCase):
    def test_a_retained_job_is_not_acted_on(self):
        bridge = OpenPnpMqttBridge(lambda: CellState.READY)
        self.assertEqual(bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message(), retained=True), [])
        self.assertEqual(bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", b"{}", retained=True), [])

    def test_the_same_message_not_retained_is_acted_on(self):
        bridge = OpenPnpMqttBridge(lambda: CellState.READY)
        self.assertEqual(len(bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message(), retained=False)), 1)


class IdempotencyTests(unittest.TestCase):
    def test_a_repeated_key_gets_the_first_answer_and_is_not_evaluated_again(self):
        states = [CellState.READY, CellState.FAULT]
        bridge = OpenPnpMqttBridge(lambda: states.pop(0), IdempotencyStore())
        first = bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message())[0]
        second = bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message())[0]
        self.assertTrue(json.loads(first.payload)["allowed"])
        self.assertEqual(second.payload, first.payload)           # the cell is FAULT now, but nothing was evaluated again
        self.assertEqual(states, [CellState.FAULT])               # the second call never asked for the cell state

    def test_a_different_key_is_a_different_job(self):
        bridge = OpenPnpMqttBridge(lambda: CellState.READY, IdempotencyStore())
        bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message("key-1"))
        again = bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message("key-2"))[0]
        self.assertTrue(json.loads(again.payload)["allowed"])

    def test_a_malformed_job_does_not_use_up_a_key(self):
        store = IdempotencyStore()
        bridge = OpenPnpMqttBridge(lambda: CellState.READY, store)
        bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", b"not json")
        self.assertEqual(len(store), 0)

    def test_without_a_store_nothing_is_deduplicated(self):
        bridge = OpenPnpMqttBridge(lambda: CellState.READY)
        for _ in range(2):
            self.assertTrue(json.loads(bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", message())[0].payload)["allowed"])


if __name__ == "__main__":
    unittest.main()
