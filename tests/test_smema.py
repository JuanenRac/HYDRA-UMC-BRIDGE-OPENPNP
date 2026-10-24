# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - SMEMA hand-over tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The SMEMA signals against a neighbour machine that exists only in memory, and over MQTT."""

import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_bridge_openpnp import OpenPnpMqttBridge, OpenPnpStateSource, SimulatedSmemaNeighbour, SmemaReceiver, SmemaSender, open_smema_gpio
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX
from hydra_umc_bridge_openpnp.smema import stable_read

READY, IDLE = CellState.READY, MachineState.IDLE
NO_SLEEP = lambda seconds: None  # noqa: E731
NOW = 1_800_000_000_000


def receiver(neighbour):
    return SmemaReceiver(neighbour.board_available_line(), neighbour.output(), sleep=NO_SLEEP)


def sender(neighbour):
    return SmemaSender(neighbour.output(), neighbour.machine_ready_line(), sleep=NO_SLEEP)


class StableReadTests(unittest.TestCase):
    def test_a_steady_asserted_line_is_asserted(self):
        neighbour = SimulatedSmemaNeighbour(board_available=True)
        self.assertTrue(stable_read(neighbour.board_available_line(), sleep=NO_SLEEP))

    def test_a_bouncing_line_is_not_asserted(self):
        neighbour = SimulatedSmemaNeighbour(board_available=True, bounce=True)
        self.assertFalse(stable_read(neighbour.board_available_line(), sleep=NO_SLEEP))

    def test_a_line_that_cannot_be_read_is_not_asserted(self):
        neighbour = SimulatedSmemaNeighbour(board_available=True, fail_reads=True)
        self.assertFalse(stable_read(neighbour.board_available_line(), sleep=NO_SLEEP))

    def test_only_a_real_true_counts(self):
        class Odd:
            def read(self):
                return 1

        self.assertFalse(stable_read(Odd(), sleep=NO_SLEEP))


class ReceiverTests(unittest.TestCase):
    def test_a_ready_cell_with_an_empty_fixture_asserts_machine_ready(self):
        neighbour = SimulatedSmemaNeighbour()
        decision = receiver(neighbour).set_ready(True, READY, IDLE, fixture_empty=True)
        self.assertEqual((decision.allowed, decision.asserted), (True, True))
        self.assertTrue(neighbour.output_level)

    def test_nothing_is_asserted_on_a_machine_state_nobody_read(self):
        neighbour = SimulatedSmemaNeighbour()
        decision = receiver(neighbour).set_ready(True, READY, None, fixture_empty=True)
        self.assertFalse(decision.allowed)
        self.assertIn("not read", decision.reason)
        self.assertFalse(neighbour.output_level)

    def test_nothing_is_asserted_for_a_cell_that_is_not_ready_or_a_machine_that_is_not_idle(self):
        for cell, machine in ((CellState.INHIBITED, IDLE), (CellState.FAULT, IDLE), (CellState.SAFE_STOP, IDLE), (READY, MachineState.RUNNING), (READY, MachineState.OFFLINE), (READY, MachineState.FAULT)):
            with self.subTest(cell=cell, machine=machine):
                neighbour = SimulatedSmemaNeighbour()
                self.assertFalse(receiver(neighbour).set_ready(True, cell, machine, fixture_empty=True).allowed)
                self.assertFalse(neighbour.output_level)

    def test_a_full_fixture_cannot_take_another_board(self):
        neighbour = SimulatedSmemaNeighbour()
        decision = receiver(neighbour).set_ready(True, READY, IDLE, fixture_empty=False)
        self.assertFalse(decision.allowed)
        self.assertIn("not empty", decision.reason)

    def test_the_fixture_must_be_literally_empty(self):
        neighbour = SimulatedSmemaNeighbour()
        self.assertFalse(receiver(neighbour).set_ready(True, READY, IDLE, fixture_empty="yes").allowed)  # type: ignore[arg-type]

    def test_a_refusal_withdraws_an_output_that_was_up(self):
        neighbour = SimulatedSmemaNeighbour()
        link = receiver(neighbour)
        link.set_ready(True, READY, IDLE, fixture_empty=True)
        decision = link.set_ready(True, CellState.INHIBITED, IDLE, fixture_empty=True)
        self.assertEqual((decision.allowed, decision.asserted), (False, False))
        self.assertFalse(neighbour.output_level)

    def test_withdrawing_is_always_allowed(self):
        neighbour = SimulatedSmemaNeighbour()
        link = receiver(neighbour)
        link.set_ready(True, READY, IDLE, fixture_empty=True)
        decision = link.set_ready(False, CellState.FAULT, None, fixture_empty=False)
        self.assertEqual((decision.allowed, decision.asserted), (True, False))
        self.assertFalse(neighbour.output_level)

    def test_reconcile_withdraws_when_the_machine_starts_running(self):
        neighbour = SimulatedSmemaNeighbour()
        link = receiver(neighbour)
        link.set_ready(True, READY, IDLE, fixture_empty=True)
        self.assertFalse(link.reconcile(READY, IDLE, fixture_empty=True))
        self.assertTrue(link.reconcile(READY, MachineState.RUNNING, fixture_empty=True))
        self.assertFalse(neighbour.output_level)
        self.assertFalse(link.reconcile(READY, MachineState.RUNNING, fixture_empty=True))  # nothing left to withdraw

    def test_reconcile_withdraws_when_the_fixture_fills_or_the_cell_stops(self):
        for args in ((READY, IDLE, False), (CellState.SAFE_STOP, IDLE, True), (READY, None, True)):
            with self.subTest(args=args):
                neighbour = SimulatedSmemaNeighbour()
                link = receiver(neighbour)
                link.set_ready(True, READY, IDLE, fixture_empty=True)
                self.assertTrue(link.reconcile(args[0], args[1], fixture_empty=args[2]))

    def test_the_arm_may_take_a_board_only_when_the_cell_said_ready_and_the_upstream_has_one(self):
        neighbour = SimulatedSmemaNeighbour(board_available=True)
        link = receiver(neighbour)
        self.assertFalse(link.may_take_board())  # the upstream has a board, but the cell has not said it is ready
        link.set_ready(True, READY, IDLE, fixture_empty=True)
        self.assertTrue(link.may_take_board())
        neighbour.board_available = False
        self.assertFalse(link.may_take_board())
        neighbour.board_available = True
        neighbour.bounce = True
        self.assertFalse(link.may_take_board())

    def test_a_line_that_cannot_be_written_stays_withdrawn_and_says_so(self):
        neighbour = SimulatedSmemaNeighbour(fail_writes=True)
        decision = receiver(neighbour).set_ready(True, READY, IDLE, fixture_empty=True)
        self.assertEqual((decision.allowed, decision.asserted), (False, False))
        self.assertFalse(neighbour.output_level)

    def test_a_line_that_cannot_be_written_at_all_is_assumed_asserted_never_withdrawn(self):
        class Dead:
            def write(self, asserted):
                raise OSError("gone")

        link = SmemaReceiver(SimulatedSmemaNeighbour().board_available_line(), Dead(), sleep=NO_SLEEP)
        decision = link.set_ready(True, READY, IDLE, fixture_empty=True)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.asserted)  # it may be up: the cell does not claim otherwise
        self.assertIn("may still be asserted", link.withdraw().reason)


class SenderTests(unittest.TestCase):
    def test_a_staged_board_is_offered_to_a_ready_machine(self):
        neighbour = SimulatedSmemaNeighbour(machine_ready=True)
        link = sender(neighbour)
        self.assertTrue(link.offer(True, READY, IDLE, board_staged=True).asserted)
        self.assertTrue(neighbour.output_level)
        self.assertTrue(link.may_deliver_board())

    def test_the_arm_waits_while_the_downstream_machine_is_not_ready(self):
        neighbour = SimulatedSmemaNeighbour(machine_ready=False)
        link = sender(neighbour)
        link.offer(True, READY, IDLE, board_staged=True)
        self.assertFalse(link.may_deliver_board())
        neighbour.machine_ready = True
        self.assertTrue(link.may_deliver_board())

    def test_there_is_nothing_to_offer_without_a_staged_board(self):
        neighbour = SimulatedSmemaNeighbour()
        decision = sender(neighbour).offer(True, READY, IDLE, board_staged=False)
        self.assertFalse(decision.allowed)
        self.assertIn("nothing to offer", decision.reason)

    def test_the_gate_applies_to_the_sender_too(self):
        for cell, machine in ((CellState.INHIBITED, IDLE), (READY, MachineState.RUNNING), (READY, None)):
            with self.subTest(cell=cell, machine=machine):
                neighbour = SimulatedSmemaNeighbour()
                self.assertFalse(sender(neighbour).offer(True, cell, machine, board_staged=True).allowed)
                self.assertFalse(neighbour.output_level)

    def test_reconcile_and_withdraw(self):
        neighbour = SimulatedSmemaNeighbour()
        link = sender(neighbour)
        link.offer(True, READY, IDLE, board_staged=True)
        self.assertFalse(link.reconcile(READY, IDLE, board_staged=True))
        self.assertTrue(link.reconcile(READY, IDLE, board_staged=False))
        self.assertFalse(neighbour.output_level)
        self.assertTrue(link.offer(False, READY, None, board_staged=False).allowed)


class GpioTests(unittest.TestCase):
    def test_without_libgpiod_it_is_a_clear_error(self):
        try:
            import gpiod  # noqa: F401

            self.skipTest("libgpiod is installed in this environment")
        except ImportError:
            pass
        with self.assertRaises(RuntimeError) as context:
            open_smema_gpio("/dev/gpiochip0", input_offset=5, output_offset=6)
        self.assertIn("gpiod", str(context.exception))


def message(bridge, verb, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    return [(publish.topic, json.loads(publish.payload), publish.retain) for publish in bridge.handle_message(f"{TOPIC_PREFIX}{verb}", body)]


class MqttSmemaTests(unittest.TestCase):
    def build(self, machine_state="IDLE", cell=READY, with_source=True, fixture_empty=None, board_staged=None):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "s.json"
        self.write_state(machine_state)
        self.cell = [cell]
        self.upstream = SimulatedSmemaNeighbour(board_available=True)
        self.downstream = SimulatedSmemaNeighbour(machine_ready=True)
        return OpenPnpMqttBridge(
            lambda: self.cell[0],
            state_source=OpenPnpStateSource(self.path, clock=lambda: NOW / 1000) if with_source else None,
            clock=lambda: NOW / 1000,
            smema_receiver=receiver(self.upstream),
            smema_sender=sender(self.downstream),
            fixture_empty=fixture_empty,
            board_staged=board_staged,
        )

    def write_state(self, machine_state):
        self.path.write_text(json.dumps({"origin": "openpnp-events", "generation": 1, "observed_at_ms": NOW - 500, "event": "Job.Finished", "job": "", "machine_state": machine_state}), encoding="utf-8")

    def test_ready_and_offer_go_through_the_gate_and_publish_the_state(self):
        bridge = self.build()
        (result_topic, result, _), (state_topic, state, retained) = message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": True})
        self.assertEqual(result_topic, f"{TOPIC_PREFIX}cmd/smema_ready/result")
        self.assertTrue(result["allowed"] and result["asserted"] and result["observed"])
        self.assertEqual(state_topic, f"{TOPIC_PREFIX}smema")
        self.assertTrue(retained)
        self.assertTrue(state["machine_ready_asserted"] and state["board_waiting"])
        (_, offer, _), (_, state, _) = message(bridge, "cmd/smema_offer", {"available": True, "board_staged": True})
        self.assertTrue(offer["asserted"])
        self.assertTrue(state["board_available_asserted"] and state["downstream_ready"])

    def test_without_a_state_source_nothing_is_asserted_on_a_claim(self):
        bridge = self.build(with_source=False)
        (_, result, _), _ = message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": True})
        self.assertFalse(result["allowed"])
        self.assertFalse(self.upstream.output_level)

    def test_a_running_machine_keeps_the_outputs_down_and_takes_them_down(self):
        bridge = self.build()
        message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": True})
        self.assertTrue(self.upstream.output_level)
        self.write_state("RUNNING")
        (_, state, _), = message(bridge, "cmd/smema_status")
        self.assertFalse(state["machine_ready_asserted"])
        self.assertFalse(self.upstream.output_level)

    def test_the_cell_stopping_takes_the_outputs_down(self):
        bridge = self.build()
        message(bridge, "cmd/smema_offer", {"available": True, "board_staged": True})
        self.cell[0] = CellState.SAFE_STOP
        (_, state, _), = message(bridge, "cmd/smema_status")
        self.assertFalse(state["board_available_asserted"])
        self.assertFalse(self.downstream.output_level)

    def test_an_abort_through_the_gate_withdraws_both_outputs(self):
        bridge = self.build()
        message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": True})
        message(bridge, "cmd/smema_offer", {"available": True, "board_staged": True})
        abort = json.dumps(job_to_dict(BridgeJob("j", "k", "o", JobPhase.ABORT, IDLE, {"board_id": "PCB-1"}))).encode()
        answer = json.loads(bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", abort)[0].payload)
        self.assertTrue(answer["smema_withdrawn"])
        self.assertFalse(self.upstream.output_level)
        self.assertFalse(self.downstream.output_level)

    def test_a_sensor_decides_when_there_is_one_and_the_message_is_ignored(self):
        bridge = self.build(fixture_empty=lambda: False, board_staged=lambda: False)
        (_, ready, _), _ = message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": True})
        self.assertFalse(ready["allowed"])
        (_, offer, _), _ = message(bridge, "cmd/smema_offer", {"available": True, "board_staged": True})
        self.assertFalse(offer["allowed"])

    def test_a_claim_must_be_literally_true(self):
        bridge = self.build()
        (_, result, _), _ = message(bridge, "cmd/smema_ready", {"ready": True, "fixture_empty": "yes"})
        self.assertFalse(result["allowed"])

    def test_malformed_requests_are_refused_and_never_assert(self):
        bridge = self.build()
        for payload in (b"not json", b"[]", b'{"ready": "yes"}', b'{"available": 1}', b"{" * 5000):
            for verb in ("cmd/smema_ready", "cmd/smema_offer"):
                with self.subTest(payload=payload[:20], verb=verb):
                    first = bridge.handle_message(f"{TOPIC_PREFIX}{verb}", payload)[0]
                    self.assertFalse(json.loads(first.payload)["allowed"])
        self.assertFalse(self.upstream.output_level)
        self.assertFalse(self.downstream.output_level)

    def test_an_oversized_payload_is_refused(self):
        bridge = self.build()
        publish = bridge.handle_message(f"{TOPIC_PREFIX}cmd/smema_ready", b" " * 20_000)[0]
        self.assertFalse(json.loads(publish.payload)["allowed"])

    def test_a_bridge_without_smema_ignores_the_verbs(self):
        bridge = OpenPnpMqttBridge(lambda: READY)
        for verb in ("cmd/smema_status", "cmd/smema_ready", "cmd/smema_offer"):
            self.assertEqual(bridge.handle_message(f"{TOPIC_PREFIX}{verb}", b"{}"), [])

    def test_a_retained_command_is_ignored(self):
        bridge = self.build()
        self.assertEqual(bridge.handle_message(f"{TOPIC_PREFIX}cmd/smema_ready", b'{"ready": true, "fixture_empty": true}', retained=True), [])
        self.assertFalse(self.upstream.output_level)

    def test_only_a_sender_or_only_a_receiver(self):
        upstream = SimulatedSmemaNeighbour(board_available=True)
        bridge = OpenPnpMqttBridge(lambda: READY, smema_receiver=receiver(upstream))
        ((_, result, _),) = message(bridge, "cmd/smema_offer", {"available": True, "board_staged": True})
        self.assertFalse(result["allowed"])
        self.assertIn("no SMEMA sender", result["reason"])


if __name__ == "__main__":
    unittest.main()
