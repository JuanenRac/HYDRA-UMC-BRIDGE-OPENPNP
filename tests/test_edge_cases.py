# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Identity boundaries, configuration parsing hazards and payload edge cases
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_sdk.job_intake import IdempotencyStore

from hydra_umc_bridge_openpnp import BoardIdentity, OpenPnpMqttBridge, inspect_machine_configuration
from hydra_umc_bridge_openpnp.board_flow import BoardFlow
from hydra_umc_bridge_openpnp.evidence import cycle_evidence
from hydra_umc_bridge_openpnp.handoff import SimulatedBoardCycle, simulate_board_cycle
from hydra_umc_bridge_openpnp.mqtt_transport import MAX_PAYLOAD_BYTES, STOP_VERBS, TOPIC_PREFIX


def job(phase=JobPhase.PROCESS, board="board-1", key="k1", machine=MachineState.IDLE):
    return BridgeJob("j", key, "orchestrator", phase, machine, {"board_id": board})


class IdentifierBoundaryTests(unittest.TestCase):
    def test_a_board_id_is_one_to_ninety_six_safe_characters_starting_with_an_alphanumeric(self):
        flow = BoardFlow()
        for good in ("a", "A1", "board-1.rev_2", "9" * 96):
            self.assertTrue(flow.plan(job(), CellState.READY, good).allowed, good)
        for bad in ("", "-a", ".a", "_a", "a b", "a/b", "a\\b", "a\n", "a" * 97, "café", None, 5, ["a"]):
            self.assertFalse(flow.plan(job(), CellState.READY, bad).allowed, repr(bad))

    def test_the_fingerprint_does_not_confuse_values_that_run_together(self):
        a = BoardIdentity("ab", "c", "r", "l")
        b = BoardIdentity("a", "bc", "r", "l")
        self.assertNotEqual(a.fingerprint(), b.fingerprint())
        self.assertEqual(a.fingerprint(), BoardIdentity("ab", "c", "r", "l").fingerprint())
        self.assertEqual(len(a.fingerprint()), 64)

    def test_every_identity_field_is_checked_and_named(self):
        ok = dict(board_id="b", recipe_id="r", revision="1", lot_id="l")
        for field in ok:
            for bad in ("", " x", "x y", "x" * 97, None, 5):
                identity = BoardIdentity(**{**ok, field: bad})
                self.assertIn(field, identity.validation_error() or "", (field, bad))
        for field in ("slot_id", "rack_id", "table_id"):
            self.assertIsNone(BoardIdentity(**ok, **{field: ""}).validation_error())
            self.assertIn(field, BoardIdentity(**ok, **{field: "bad id"}).validation_error() or "")
            self.assertIn(field, BoardIdentity(**ok, **{field: 5}).validation_error() or "")


class CycleTests(unittest.TestCase):
    identity = BoardIdentity("board-1", "recipe", "1", "lot")

    def test_a_cycle_is_allowed_only_when_the_cell_is_ready_and_the_machine_idle(self):
        self.assertTrue(simulate_board_cycle(CellState.READY, MachineState.IDLE, self.identity).allowed)
        for cell, machine in ((CellState.FAULT, MachineState.IDLE), (CellState.READY, MachineState.RUNNING), (CellState.READY, MachineState.FAULT)):
            cycle = simulate_board_cycle(cell, machine, self.identity)
            self.assertFalse(cycle.allowed, (cell, machine))
            self.assertTrue(all(step.identity_fingerprint is None for step in cycle.steps))

    def test_a_cycle_missing_a_step_has_no_evidence(self):
        short = SimulatedBoardCycle(True, simulate_board_cycle(CellState.READY, MachineState.IDLE, self.identity).steps[:3])
        with self.assertRaises(ValueError):
            cycle_evidence(short)


class ConfigurationTests(unittest.TestCase):
    def inspect(self, content, name="machine.xml"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / name
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            return inspect_machine_configuration(path)

    def test_an_entity_expansion_bomb_is_refused_unparsed(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><openpnp-machine><machine class="x">&b;</machine></openpnp-machine>'
        profile = self.inspect(bomb)
        self.assertFalse(profile.available)
        self.assertIn("DOCTYPE", profile.reason)

    def test_a_doctype_in_lowercase_or_utf16_is_refused_as_well(self):
        self.assertFalse(self.inspect("<!doctype x><openpnp-machine><machine/></openpnp-machine>").available)
        utf16 = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x><openpnp-machine><machine/></openpnp-machine>'.encode("utf-16")
        profile = self.inspect(utf16)
        self.assertFalse(profile.available)

    def test_a_document_one_byte_over_the_limit_is_not_read(self):
        padding = b" " * (4 * 1024 * 1024 + 1)
        profile = self.inspect(b"<openpnp-machine><machine/></openpnp-machine>" + padding)
        self.assertFalse(profile.available)
        self.assertIn("4 MiB", profile.reason)

    def test_a_document_that_is_not_an_openpnp_machine_is_unavailable(self):
        for content in ("<other><machine/></other>", "<openpnp-machine/>", "<openpnp-machine><x/></openpnp-machine>", "not xml at all", "", "<openpnp-machine><machine></openpnp-machine>"):
            self.assertFalse(self.inspect(content).available, content)

    def test_a_missing_file_a_directory_and_a_bad_path_fail_safely(self):
        self.assertFalse(inspect_machine_configuration("definitely-missing.xml").available)
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(inspect_machine_configuration(directory).available)
        self.assertFalse(inspect_machine_configuration(None).available)

    def test_the_counts_are_taken_from_everywhere_below_the_machine(self):
        xml = (
            '<openpnp-machine><machine class="org.openpnp.machine.reference.ReferenceMachine">'
            "<heads><head><nozzles/></head><head/></heads><cameras><camera/><camera/><camera/></cameras>"
            "<drivers><driver/></drivers><feeders><feeder/><feeder/></feeders><actuators><actuator/></actuators>"
            "<nozzle-tips><nozzle-tip/></nozzle-tips><signalers><signaler/><signaler/></signalers></machine></openpnp-machine>"
        )
        profile = self.inspect(xml)
        self.assertTrue(profile.available)
        self.assertEqual(
            (profile.machine_class.rsplit(".", 1)[1], profile.head_count, profile.camera_count, profile.driver_count, profile.feeder_count, profile.actuator_count, profile.nozzle_tip_count, profile.signaler_count),
            ("ReferenceMachine", 2, 3, 1, 2, 1, 1, 2),
        )


class PayloadTests(unittest.TestCase):
    def bridge(self, store=None):
        return OpenPnpMqttBridge(lambda: CellState.READY, store)

    def test_this_bridge_has_no_stop_verb_and_an_abort_stops_nothing(self):
        self.assertEqual(STOP_VERBS, frozenset())
        publishes = self.bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", json.dumps(job_to_dict(job(JobPhase.ABORT))).encode())
        result = json.loads(publishes[0].payload)
        self.assertIs(result["forwarded"], False)
        self.assertIs(result["observed"], False)

    def test_a_job_without_a_board_is_a_refusal(self):
        for board in ("", None, 5, ["b"]):
            body = job_to_dict(job())
            body["parameters"] = {"board_id": board}
            result = json.loads(self.bridge().handle_message(f"{TOPIC_PREFIX}cmd/job", json.dumps(body).encode())[0].payload)
            self.assertFalse(result["allowed"], repr(board))

    def test_payloads_that_are_not_requests_are_refused_on_both_verbs(self):
        for verb in ("cmd/job", "cmd/handoff"):
            for payload in (b"null", b"[]", b"7", b'"x"', b"", b"{", bytes([255, 254]), b"{}", b'{"job": 5, "identity": 5}'):
                publishes = self.bridge().handle_message(f"{TOPIC_PREFIX}{verb}", payload)
                self.assertEqual(len(publishes), 1, (verb, payload))
                self.assertEqual(publishes[0].topic, f"{TOPIC_PREFIX}{verb}/result")
                self.assertFalse(json.loads(publishes[0].payload)["allowed"], (verb, payload))

    def test_the_size_limit_is_exact_and_the_refusal_names_the_verb(self):
        over = self.bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", b" " * (MAX_PAYLOAD_BYTES + 1))
        self.assertEqual(over[0].topic, f"{TOPIC_PREFIX}cmd/handoff/result")
        self.assertIn("larger than", json.loads(over[0].payload)["reason"])
        at_limit = self.bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", b" " * MAX_PAYLOAD_BYTES)
        self.assertNotIn("larger than", json.loads(at_limit[0].payload)["reason"])

    def test_a_handoff_for_one_board_cannot_carry_another_boards_identity(self):
        request = {
            "job": job_to_dict(job(board="board-1", key="h1")),
            "identity": {"board_id": "board-2", "recipe_id": "r", "revision": "1", "lot_id": "l"},
        }
        result = json.loads(self.bridge().handle_message(f"{TOPIC_PREFIX}cmd/handoff", json.dumps(request).encode())[0].payload)
        self.assertFalse(result["allowed"])
        self.assertIsNone(result["identity_fingerprint"])

    def test_the_same_key_is_judged_once_per_verb(self):
        store = IdempotencyStore()
        b = self.bridge(store)
        payload = json.dumps(job_to_dict(job(key="same"))).encode()
        first = b.handle_message(f"{TOPIC_PREFIX}cmd/job", payload)[0].payload
        self.assertEqual(b.handle_message(f"{TOPIC_PREFIX}cmd/job", payload)[0].payload, first)

    def test_retained_and_foreign_topics_get_no_answer(self):
        b = self.bridge()
        self.assertEqual(b.handle_message(f"{TOPIC_PREFIX}cmd/job", b"{}", retained=True), [])
        for topic in ("other/cmd/job", f"{TOPIC_PREFIX}cmd/unknown", f"{TOPIC_PREFIX}state", ""):
            self.assertEqual(b.handle_message(topic, b"{}"), [], topic)


if __name__ == "__main__":
    unittest.main()
