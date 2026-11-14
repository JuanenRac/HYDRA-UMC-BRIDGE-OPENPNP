# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - A repeated job key whose first attempt left no answer
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A repeat whose first attempt left no answer is answered with the state OpenPnP itself reported (switch off by default) and never planned again; no reading from OpenPnP keeps it refused. Simulated state file, evidence=simulator."""

import json
import os
import unittest
from unittest import mock

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_sdk.job_intake import IdempotencyStore

from hydra_umc_bridge_openpnp import OpenPnpMqttBridge
from hydra_umc_bridge_openpnp.mqtt_transport import IN_DOUBT_CONSULT_ENVIRONMENT, TOPIC_PREFIX
from hydra_umc_bridge_openpnp.observation import OpenPnpObservation

JOB_TOPIC = f"{TOPIC_PREFIX}cmd/job"
HANDOFF_TOPIC = f"{TOPIC_PREFIX}cmd/handoff"


def job(key="key-1"):
    return BridgeJob("job-1", key, "orchestrator", JobPhase.LOAD, MachineState.IDLE, {"board_id": "board-1"})


def job_message(key="key-1"):
    return json.dumps(job_to_dict(job(key))).encode("utf-8")


def handoff_message(key="key-1"):
    return json.dumps({"job": job_to_dict(job(key)), "identity": {"board_id": "board-1", "recipe_id": "recipe-1", "revision": "r1", "lot_id": "lot-1"}}).encode("utf-8")


def reported(state=MachineState.RUNNING):
    return lambda: OpenPnpObservation(state, "Job.Starting", "job-1", 7, 1_000)


def not_reported():
    return OpenPnpObservation(MachineState.OFFLINE, "", "", None, None, "the state file is missing")


def in_doubt_store(key):
    store = IdempotencyStore()
    assert store.claim(key)  # the first attempt claimed the key and never stored an answer
    return store


def bridge(store, state_source=None, **options):
    return OpenPnpMqttBridge(lambda: CellState.READY, store, state_source=state_source, **options)


def body(out):
    return json.loads(out[0].payload)


class SwitchTests(unittest.TestCase):
    def test_off_by_default_a_job_in_doubt_is_refused_as_before(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(IN_DOUBT_CONSULT_ENVIRONMENT, None)
            b = bridge(in_doubt_store("job:key-1"), reported())
        answer = body(b.handle_message(JOB_TOPIC, job_message()))
        self.assertFalse(b.in_doubt_consult)
        self.assertFalse(answer["allowed"])
        self.assertIn("already handled", answer["reason"])
        self.assertNotIn("in_doubt", answer)

    def test_the_environment_switch_turns_it_on(self):
        with mock.patch.dict(os.environ, {IN_DOUBT_CONSULT_ENVIRONMENT: "1"}):
            b = bridge(in_doubt_store("job:key-1"), reported())
        self.assertTrue(body(b.handle_message(JOB_TOPIC, job_message()))["in_doubt"])

    def test_any_other_value_of_the_switch_keeps_it_off(self):
        for value in ("0", "", "true", "yes"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {IN_DOUBT_CONSULT_ENVIRONMENT: value}):
                self.assertFalse(bridge(in_doubt_store("job:key-1"), reported()).in_doubt_consult)


class ConsultTests(unittest.TestCase):
    def test_the_repeat_is_answered_with_the_state_openpnp_reported_and_is_not_planned_again(self):
        answer = body(bridge(in_doubt_store("job:key-1"), reported(), in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertEqual((answer["allowed"], answer["in_doubt"], answer["forwarded"], answer["observed"], answer["machine_state"]), (False, True, False, True, "RUNNING"))
        self.assertEqual((answer["event"], answer["job"], answer["mode"]), ("Job.Starting", "job-1", "simulation-only"))
        self.assertIn("RUNNING", answer["reason"])

    def test_an_idle_machine_and_a_ready_cell_do_not_turn_a_repeat_into_a_new_job(self):
        answer = body(bridge(in_doubt_store("job:key-1"), reported(MachineState.IDLE), in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertFalse(answer["allowed"])
        self.assertTrue(answer["in_doubt"])

    def test_the_handoff_is_looked_up_the_same_way_under_its_own_key(self):
        answer = body(bridge(in_doubt_store("handoff:key-1"), reported(), in_doubt_consult=True).handle_message(HANDOFF_TOPIC, handoff_message()))
        self.assertEqual((answer["allowed"], answer["in_doubt"], answer["machine_state"]), (False, True, "RUNNING"))

    def test_a_job_key_in_doubt_does_not_make_the_handoff_with_the_same_key_a_repeat(self):
        out = bridge(in_doubt_store("job:key-1"), reported(MachineState.IDLE), in_doubt_consult=True).handle_message(HANDOFF_TOPIC, handoff_message())
        self.assertNotIn("in_doubt", body(out))

    def test_without_a_state_source_nothing_from_openpnp_is_known_and_the_repeat_stays_refused(self):
        answer = body(bridge(in_doubt_store("job:key-1"), None, in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertFalse(answer["allowed"])
        self.assertNotIn("in_doubt", answer)
        self.assertIn("already handled", answer["reason"])

    def test_a_reading_that_is_old_missing_or_not_from_the_scripts_stays_refused(self):
        answer = body(bridge(in_doubt_store("job:key-1"), not_reported, in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertNotIn("in_doubt", answer)

    def test_a_state_source_that_fails_stays_refused(self):
        def broken():
            raise OSError("state file unreadable")

        answer = body(bridge(in_doubt_store("job:key-1"), broken, in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertNotIn("in_doubt", answer)

    def test_the_answer_is_stored_so_a_third_repeat_gets_the_same_one_without_a_new_reading(self):
        readings = [MachineState.HOLDING, MachineState.IDLE]
        b = bridge(in_doubt_store("job:key-1"), lambda: OpenPnpObservation(readings.pop(0), "Job.Paused", "job-1", 7, 1_000), in_doubt_consult=True)
        first = b.handle_message(JOB_TOPIC, job_message())[0]
        third = b.handle_message(JOB_TOPIC, job_message())[0]
        self.assertEqual(third.payload, first.payload)
        self.assertEqual(json.loads(first.payload)["machine_state"], "HOLDING")
        self.assertEqual(readings, [MachineState.IDLE])

    def test_a_key_with_a_stored_answer_gets_that_answer_not_a_reading(self):
        b = bridge(IdempotencyStore(), reported(MachineState.IDLE), in_doubt_consult=True)
        first = b.handle_message(JOB_TOPIC, job_message())[0]
        second = b.handle_message(JOB_TOPIC, job_message())[0]
        self.assertEqual(second.payload, first.payload)
        self.assertNotIn("in_doubt", json.loads(second.payload))

    def test_a_new_key_is_planned_normally_with_the_switch_on(self):
        answer = body(bridge(in_doubt_store("job:other"), reported(MachineState.IDLE), in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertTrue(answer["allowed"])

    def test_without_a_store_nothing_is_in_doubt(self):
        answer = body(bridge(None, reported(MachineState.IDLE), in_doubt_consult=True).handle_message(JOB_TOPIC, job_message()))
        self.assertTrue(answer["allowed"])


if __name__ == "__main__":
    unittest.main()
