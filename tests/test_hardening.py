# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Hostile payloads, one key space per verb and honest answers
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What a client of the broker can do to this bridge must never end its loop, and the answers must not claim more than the bridge knows."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_sdk.job_intake import IdempotencyStore

from hydra_umc_bridge_openpnp import BoardFlow, BoardIdentity, OpenPnpMqttBridge, inspect_machine_configuration
from hydra_umc_bridge_openpnp.mqtt_transport import AVAILABILITY_TOPIC, MAX_PAYLOAD_BYTES, TOPIC_PREFIX, MessageDispatcher


def make_job(key="k1", phase=JobPhase.LOAD, board="pcb-42"):
    return BridgeJob("job-1", key, "orchestrator", phase, MachineState.IDLE, {"board_id": board})


def job_payload(**kwargs):
    return json.dumps(job_to_dict(make_job(**kwargs))).encode("utf-8")


def handoff_payload(key="k1", **identity):
    fields = {"board_id": "pcb-42", "recipe_id": "recipe", "revision": "r1", "lot_id": "lot-1"}
    fields.update(identity)
    return json.dumps({"job": job_to_dict(make_job(key)), "identity": fields}).encode("utf-8")


def bridge(store=None, state=CellState.READY):
    return OpenPnpMqttBridge(lambda: state, store)


class HostilePayloadTests(unittest.TestCase):
    def test_a_deeply_nested_json_is_a_refusal_not_an_exception(self):
        for verb in ("job", "handoff"):
            publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/{verb}", b"[" * 100_000)
            self.assertEqual(len(publishes), 1, verb)
            self.assertFalse(json.loads(publishes[0].payload)["allowed"])
            self.assertEqual(publishes[0].topic, f"{TOPIC_PREFIX}cmd/{verb}/result")

    def test_a_payload_over_the_limit_is_refused(self):
        publishes = bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", b" " * (MAX_PAYLOAD_BYTES + 1))
        result = json.loads(publishes[0].payload)
        self.assertIn("larger than", result["reason"])
        self.assertEqual(result["mode"], "simulation-only")
        self.assertIsNone(result["identity_fingerprint"])

    def test_a_failure_while_gating_is_a_refusal_and_leaves_an_honest_answer_for_the_key(self):
        def broken():
            raise RuntimeError("cell state source down")

        failing = OpenPnpMqttBridge(broken, IdempotencyStore())
        first = failing.handle_message(f"{TOPIC_PREFIX}cmd/job", job_payload())[0]
        again = failing.handle_message(f"{TOPIC_PREFIX}cmd/job", job_payload())[0]
        self.assertFalse(json.loads(first.payload)["allowed"])
        self.assertEqual(again.payload, first.payload)


class IdempotencyPerVerbTests(unittest.TestCase):
    def test_a_job_checked_with_the_gate_can_still_be_handed_off_with_the_same_key(self):
        shared = bridge(IdempotencyStore())
        gate = json.loads(shared.handle_message(f"{TOPIC_PREFIX}cmd/job", job_payload(key="same"))[0].payload)
        self.assertTrue(gate["allowed"])
        handoff = json.loads(shared.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_payload("same"))[0].payload)
        self.assertEqual(handoff["mode"], "simulation-only")
        self.assertEqual(len(handoff["identity_fingerprint"]), 64)

    def test_a_repeated_handoff_gets_the_first_answer(self):
        shared = bridge(IdempotencyStore())
        first = shared.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_payload("again"))[0]
        second = shared.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_payload("again"))[0]
        self.assertEqual(second.payload, first.payload)


class HonestJobAnswerTests(unittest.TestCase):
    def test_a_job_answer_says_it_is_simulation_only_and_not_observed(self):
        result = json.loads(bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", job_payload())[0].payload)
        self.assertEqual(result["mode"], "simulation-only")
        self.assertIs(result["observed"], False)

    def test_an_abort_says_that_nothing_was_stopped(self):
        result = json.loads(bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", job_payload(phase=JobPhase.ABORT))[0].payload)
        self.assertIs(result["forwarded"], False)
        self.assertIn("nothing was stopped", result["reason"])


class BoardIdentifierTests(unittest.TestCase):
    def test_the_gate_and_the_trace_accept_the_same_identifiers(self):
        for board in ("../x", "a b", "x" * 97, "-start", ""):
            decision = BoardFlow().plan(make_job(board=board), CellState.READY, board)
            self.assertFalse(decision.allowed, board)
        self.assertTrue(BoardFlow().plan(make_job(board="pcb-42.v2_a"), CellState.READY, "pcb-42.v2_a").allowed)

    def test_a_board_the_gate_accepts_can_be_traced(self):
        board = "pcb-42.v2_a"
        self.assertIsNone(BoardIdentity(board, "recipe", "r1", "lot-1").validation_error())


class PlacementIdentityTests(unittest.TestCase):
    def fingerprint(self, **extra):
        return json.loads(bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_payload(**extra))[0].payload)["identity_fingerprint"]

    def test_two_placements_of_the_same_board_have_different_fingerprints(self):
        plain = self.fingerprint()
        slot_a = self.fingerprint(slot_id="slot-a")
        slot_b = self.fingerprint(slot_id="slot-b")
        self.assertEqual(len({plain, slot_a, slot_b}), 3)
        self.assertNotEqual(self.fingerprint(rack_id="rack-1"), self.fingerprint(table_id="rack-1"))

    def test_a_badly_formed_placement_identifier_is_refused(self):
        result = json.loads(bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_payload(slot_id="../x"))[0].payload)
        self.assertFalse(result["allowed"])
        self.assertIn("slot_id", result["reason"])


class DoctypeTests(unittest.TestCase):
    def inspect(self, document: bytes):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "machine.xml"
            path.write_bytes(document)
            return inspect_machine_configuration(path)

    def test_a_doctype_in_utf16_is_refused_too(self):
        document = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE openpnp-machine [<!ENTITY x "y">]><openpnp-machine><machine/></openpnp-machine>'.encode("utf-16")
        self.assertNotIn(b"<!DOCTYPE", document.upper())
        profile = self.inspect(document)
        self.assertFalse(profile.available)
        self.assertIn("DOCTYPE", profile.reason)

    def test_a_plain_utf16_document_is_still_read(self):
        profile = self.inspect('<?xml version="1.0" encoding="utf-16"?><openpnp-machine><machine class="x"/></openpnp-machine>'.encode("utf-16"))
        self.assertTrue(profile.available)
        self.assertEqual(profile.machine_class, "x")

    def test_a_malformed_document_is_unavailable(self):
        self.assertFalse(self.inspect(b"<openpnp-machine><machine></openpnp-machine>").available)


class DispatcherTests(unittest.TestCase):
    def test_answers_are_published_and_a_retained_message_is_never_queued(self):
        client = mock.MagicMock()
        dispatcher = MessageDispatcher(bridge())
        dispatcher.on_message(client, None, mock.MagicMock(topic=f"{TOPIC_PREFIX}cmd/job", payload=job_payload(), retain=False))
        dispatcher.on_message(client, None, mock.MagicMock(topic=f"{TOPIC_PREFIX}cmd/job", payload=job_payload(), retain=True))
        dispatcher.close()
        self.assertEqual(client.publish.call_count, 1)


class FakeClient:
    instances: list = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.will = None
        self.published = []
        self.subscribed = []
        self.reconnect = None
        FakeClient.instances.append(self)

    def username_pw_set(self, *args, **kwargs):
        pass

    def tls_set(self, *args, **kwargs):
        pass

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self.reconnect = (min_delay, max_delay)

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def connect(self, *args, **kwargs):
        pass

    def subscribe(self, topic, *args, **kwargs):
        self.subscribed.append(topic)

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def loop_forever(self):
        return None


class RunForeverTests(unittest.TestCase):
    def run_it(self):
        paho = types.ModuleType("paho")
        mqtt_package = types.ModuleType("paho.mqtt")
        client_module = types.ModuleType("paho.mqtt.client")
        client_module.Client = FakeClient
        client_module.CallbackAPIVersion = types.SimpleNamespace(VERSION2="v2")
        paho.mqtt = mqtt_package
        mqtt_package.client = client_module
        modules = {"paho": paho, "paho.mqtt": mqtt_package, "paho.mqtt.client": client_module}
        from hydra_umc_bridge_openpnp import run_forever

        FakeClient.instances.clear()
        with mock.patch.dict(sys.modules, modules):
            run_forever(bridge(), "127.0.0.1")
        return FakeClient.instances[-1]

    def test_the_client_uses_the_version_2_callbacks(self):
        self.assertEqual(self.run_it().args[0], "v2")

    def test_a_last_will_marks_the_bridge_offline_and_connecting_marks_it_online(self):
        client = self.run_it()
        self.assertEqual(client.will, (AVAILABILITY_TOPIC, "offline", 1, True))
        client.on_connect(client, None, {}, types.SimpleNamespace(is_failure=False), None)
        self.assertIn((AVAILABILITY_TOPIC, "online", 1, True), client.published)
        self.assertEqual(client.subscribed, [f"{TOPIC_PREFIX}cmd/#"])
        self.assertEqual(client.reconnect, (1, 30))

    def test_a_refused_connection_does_not_announce_the_bridge_online(self):
        client = self.run_it()
        client.on_connect(client, None, {}, types.SimpleNamespace(is_failure=True), None)
        self.assertEqual(client.published, [])


if __name__ == "__main__":
    unittest.main()
