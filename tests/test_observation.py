# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Observed machine state tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The state file the OpenPnP event scripts write, how the bridge trusts it, and the scripts themselves (run in Node)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_bridge_openpnp import OpenPnpMqttBridge, OpenPnpStateSource, read_state_file
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "openpnp-scripts" / "HYDRA-UMC"
HARNESS = ROOT / "tests" / "openpnp_script_harness.js"
NOW = 1_800_000_000_000


def state(**overrides):
    payload = {"origin": "openpnp-events", "generation": 5, "observed_at_ms": NOW - 1000, "event": "Job.Finished", "job": "board.job.xml", "machine_state": "IDLE"}
    payload.update(overrides)
    return payload


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "openpnp_state.json"

    def write(self, payload):
        self.path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    def read(self, **kwargs):
        return read_state_file(self.path, now_ms=kwargs.pop("now_ms", NOW), **kwargs)

    def test_a_fresh_idle_reading_is_idle_and_observed(self):
        self.write(state())
        observation = self.read()
        self.assertEqual(observation.machine_state, MachineState.IDLE)
        self.assertTrue(observation.observed)
        self.assertEqual((observation.event, observation.job, observation.generation), ("Job.Finished", "board.job.xml", 5))

    def test_every_state_word_maps(self):
        for word, expected in (("RUNNING", MachineState.RUNNING), ("HOLDING", MachineState.HOLDING), ("FAULT", MachineState.FAULT), ("OFFLINE", MachineState.OFFLINE)):
            with self.subTest(word=word):
                self.write(state(machine_state=word))
                self.assertEqual(self.read().machine_state, expected)

    def test_a_missing_file_is_offline_and_not_observed(self):
        observation = self.read()
        self.assertEqual(observation.machine_state, MachineState.OFFLINE)
        self.assertFalse(observation.observed)
        self.assertIn("has not written", observation.reason)

    def test_an_old_reading_is_not_trusted(self):
        self.write(state(observed_at_ms=NOW - 901_000))
        observation = self.read()
        self.assertEqual(observation.machine_state, MachineState.OFFLINE)
        self.assertIn("older", observation.reason)
        self.assertEqual(self.read(max_age_ms=2_000_000).machine_state, MachineState.IDLE)

    def test_a_reading_from_the_future_is_not_trusted(self):
        self.write(state(observed_at_ms=NOW + 5))
        self.assertFalse(self.read().observed)

    def test_the_writer_must_be_the_event_scripts(self):
        self.write(state(origin="someone-else"))
        self.assertFalse(self.read().observed)
        self.write({key: value for key, value in state().items() if key != "origin"})
        self.assertFalse(self.read().observed)

    def test_the_generation_must_advance_when_the_caller_asks_for_it(self):
        self.write(state(generation=5))
        self.assertTrue(self.read(min_generation=4).observed)
        self.assertFalse(self.read(min_generation=5).observed)

    def test_anything_malformed_is_offline_never_an_exception(self):
        bad = ["", "not json", "[]", "null", "5", '{"origin":"openpnp-events"}']
        bad += [state(machine_state="BANANA"), state(machine_state=3), state(generation=True), state(generation=-1), state(generation="5"),
                state(observed_at_ms="now"), state(observed_at_ms=True), state(event=5), state(job=[])]
        for payload in bad:
            with self.subTest(payload=payload):
                self.write(payload)
                observation = self.read()
                self.assertEqual(observation.machine_state, MachineState.OFFLINE)
                self.assertFalse(observation.observed)

    def test_a_file_that_is_too_large_is_not_read(self):
        self.write(state(job="x" * 20_000))
        self.assertIn("larger", self.read().reason)

    def test_deeply_nested_json_does_not_crash_the_reader(self):
        self.write("[" * 100_000)
        self.assertFalse(self.read().observed)

    def test_a_clock_or_age_that_is_not_valid_is_offline(self):
        self.write(state())
        for now, age in ((True, 1), ("x", 1), (NOW, -1), (NOW, True), (NOW, "1")):
            with self.subTest(now=now, age=age):
                self.assertFalse(read_state_file(self.path, now_ms=now, max_age_ms=age).observed)  # type: ignore[arg-type]

    def test_event_and_job_are_cut_to_a_sane_length(self):
        self.write(state(job="j" * 5000, event="e" * 5000))
        observation = self.read()
        self.assertEqual((len(observation.job), len(observation.event)), (128, 64))

    def test_a_directory_in_place_of_the_file_is_offline(self):
        self.path.mkdir()
        self.assertFalse(self.read().observed)


class SourceTests(unittest.TestCase):
    def test_the_source_reads_the_file_every_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json"
            source = OpenPnpStateSource(path, clock=lambda: NOW / 1000)
            self.assertFalse(source().observed)
            path.write_text(json.dumps(state()), encoding="utf-8")
            self.assertEqual(source().machine_state, MachineState.IDLE)
            path.write_text(json.dumps(state(machine_state="RUNNING", generation=6)), encoding="utf-8")
            self.assertEqual(source().machine_state, MachineState.RUNNING)

    def test_from_environment(self):
        self.assertIsNone(OpenPnpStateSource.from_environment({}))
        self.assertIsNone(OpenPnpStateSource.from_environment({"HYDRA_UMC_OPENPNP_STATE_FILE": "  "}))
        source = OpenPnpStateSource.from_environment({"HYDRA_UMC_OPENPNP_STATE_FILE": "/tmp/s.json", "HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS": "30"})
        self.assertEqual(source._max_age_ms, 30_000)  # noqa: SLF001
        for text in ("abc", "-5", "0", "nan", "1e99", ""):
            with self.subTest(text=text):
                default = OpenPnpStateSource.from_environment({"HYDRA_UMC_OPENPNP_STATE_FILE": "/tmp/s.json", "HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS": text})
                self.assertEqual(default._max_age_ms, 15 * 60 * 1000)  # noqa: SLF001


def job_message(phase=JobPhase.LOAD, key="k-1", claimed=MachineState.IDLE):
    return json.dumps(job_to_dict(BridgeJob("j-1", key, "orchestrator", phase, claimed, {"board_id": "PCB-001"}))).encode()


class BridgeWithAStateSourceTests(unittest.TestCase):
    def bridge(self, machine_state="IDLE", **overrides):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "s.json"
        if machine_state is not None:
            self.path.write_text(json.dumps(state(machine_state=machine_state, **overrides)), encoding="utf-8")
        return OpenPnpMqttBridge(lambda: CellState.READY, state_source=OpenPnpStateSource(self.path, clock=lambda: NOW / 1000), clock=lambda: NOW / 1000)

    def ask(self, bridge, phase=JobPhase.LOAD, key="k-1", claimed=MachineState.IDLE):
        return json.loads(bridge.handle_message(f"{TOPIC_PREFIX}cmd/job", job_message(phase, key, claimed))[0].payload)

    def test_an_idle_machine_that_openpnp_reported_lets_the_board_through_and_says_observed(self):
        answer = self.ask(self.bridge("IDLE"))
        self.assertTrue(answer["allowed"])
        self.assertTrue(answer["observed"])

    def test_a_running_machine_refuses_whatever_the_requester_claims(self):
        answer = self.ask(self.bridge("RUNNING"), claimed=MachineState.IDLE)
        self.assertFalse(answer["allowed"])
        self.assertIn("RUNNING", answer["reason"])
        self.assertTrue(answer["observed"])

    def test_no_state_file_is_a_refused_job_with_the_reason(self):
        answer = self.ask(self.bridge(None))
        self.assertFalse(answer["allowed"])
        self.assertFalse(answer["observed"])
        self.assertIn("has not written", answer["observation_reason"])

    def test_an_old_reading_is_a_refused_job(self):
        answer = self.ask(self.bridge("IDLE", observed_at_ms=NOW - 3_600_000))
        self.assertFalse(answer["allowed"])
        self.assertIn("older", answer["observation_reason"])

    def test_abort_is_still_forwarded_and_still_says_nothing_was_stopped(self):
        answer = self.ask(self.bridge(None), JobPhase.ABORT)
        self.assertTrue(answer["allowed"])
        self.assertFalse(answer["forwarded"])

    def test_a_source_that_raises_is_an_offline_machine(self):
        def broken():
            raise RuntimeError("disk gone")

        bridge = OpenPnpMqttBridge(lambda: CellState.READY, state_source=broken)
        answer = self.ask(bridge)
        self.assertFalse(answer["allowed"])
        self.assertFalse(answer["observed"])

    def test_without_a_source_the_claim_is_used_and_says_so(self):
        answer = self.ask(OpenPnpMqttBridge(lambda: CellState.READY))
        self.assertTrue(answer["allowed"])
        self.assertFalse(answer["observed"])

    def test_the_handoff_uses_the_observed_state_too(self):
        bridge = self.bridge("RUNNING")
        request = {"job": job_to_dict(BridgeJob("j-1", "h-1", "o", JobPhase.LOAD, MachineState.IDLE, {"board_id": "PCB-001"})), "identity": {"board_id": "PCB-001", "recipe_id": "R", "revision": "A", "lot_id": "L"}}
        answer = json.loads(bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", json.dumps(request).encode())[0].payload)
        self.assertFalse(answer["allowed"])
        self.assertTrue(answer["observed"])
        self.assertIsNone(answer["identity_fingerprint"])
        idle = self.bridge("IDLE")
        answer = json.loads(idle.handle_message(f"{TOPIC_PREFIX}cmd/handoff", json.dumps(request).encode())[0].payload)
        self.assertTrue(answer["allowed"])
        self.assertIsNotNone(answer["identity_fingerprint"])

    def test_status_publishes_the_retained_state_with_its_provenance(self):
        publishes = self.bridge("RUNNING", event="Job.Starting").handle_message(f"{TOPIC_PREFIX}cmd/status", b"")
        self.assertEqual(publishes[0].topic, f"{TOPIC_PREFIX}state")
        self.assertTrue(publishes[0].retain)
        payload = json.loads(publishes[0].payload)
        self.assertEqual((payload["machine_state"], payload["observed"], payload["event"]), ("RUNNING", True, "Job.Starting"))
        self.assertEqual(payload["published_at"], NOW)

    def test_status_of_a_missing_file_says_why(self):
        payload = json.loads(self.bridge(None).handle_message(f"{TOPIC_PREFIX}cmd/status", b"")[0].payload)
        self.assertEqual((payload["machine_state"], payload["observed"]), ("OFFLINE", False))
        self.assertIn("reason", payload)

    def test_status_does_nothing_without_a_source(self):
        self.assertEqual(OpenPnpMqttBridge(lambda: CellState.READY).handle_message(f"{TOPIC_PREFIX}cmd/status", b""), [])


@unittest.skipUnless(shutil.which("node"), "node is not installed: the OpenPnP scripts are not run")
class ScriptTests(unittest.TestCase):
    """The scripts, run in Node with the few Java classes they use, writing the file the Python reader reads."""

    def run_script(self, relative, *options):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        target = Path(directory) / "nested" / "openpnp_state.json"
        completed = subprocess.run(["node", str(HARNESS), str(SCRIPTS / relative), str(target), *options], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return target

    def read(self, target):
        return read_state_file(target, now_ms=int(__import__("time").time() * 1000))

    def test_each_event_writes_the_state_it_implies(self):
        cases = {
            "Events/Job.Starting.js": (MachineState.RUNNING, "Job.Starting"),
            "Events/Job.Placement.Complete.js": (MachineState.RUNNING, "Job.Placement.Complete"),
            "Events/Job.Finished.js": (MachineState.IDLE, "Job.Finished"),
            "Events/Machine.AfterHoming.js": (MachineState.IDLE, "Machine.AfterHoming"),
            "Events/Machine.AfterDisabled.js": (MachineState.OFFLINE, "Machine.AfterDisabled"),
        }
        for relative, (expected, event) in cases.items():
            with self.subTest(script=relative):
                observation = self.read(self.run_script(relative, "job=a.job.xml"))
                self.assertEqual(observation.event, event)
                self.assertEqual(observation.machine_state, expected)
                if expected is not MachineState.OFFLINE:
                    self.assertTrue(observation.observed)

    def test_the_job_name_is_recorded_for_the_job_events_only(self):
        self.assertEqual(self.read(self.run_script("Events/Job.Starting.js", "job=panel-7.xml")).job, "panel-7.xml")
        self.assertEqual(self.read(self.run_script("Events/Machine.AfterHoming.js", "job=panel-7.xml")).job, "")

    def test_a_job_event_without_a_job_in_scope_still_writes(self):
        self.assertTrue(self.read(self.run_script("Events/Job.Finished.js", "nojob")).observed)

    def test_the_generation_grows_with_every_event(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        target = Path(directory) / "s.json"
        generations = []
        for relative in ("Events/Job.Starting.js", "Events/Job.Placement.Complete.js", "Events/Job.Finished.js"):
            subprocess.run(["node", str(HARNESS), str(SCRIPTS / relative), str(target)], check=True)
            generations.append(json.loads(target.read_text(encoding="utf-8"))["generation"])
        self.assertEqual(generations, [1, 2, 3])

    def test_a_corrupt_previous_file_restarts_the_generation_instead_of_failing(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        target = Path(directory) / "s.json"
        target.write_text("{not json", encoding="utf-8")
        subprocess.run(["node", str(HARNESS), str(SCRIPTS / "Events/Job.Finished.js"), str(target)], check=True)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["generation"], 1)

    def test_no_temporary_file_is_left_behind(self):
        target = self.run_script("Events/Job.Finished.js")
        self.assertEqual([entry.name for entry in target.parent.iterdir()], ["openpnp_state.json"])

    def test_the_menu_script_states_idle_only_for_an_enabled_machine_that_is_not_busy(self):
        self.assertEqual(self.read(self.run_script("Report_state.js", "machine=idle", "nojob")).machine_state, MachineState.IDLE)
        for mode in ("busy", "disabled", "broken"):
            with self.subTest(mode=mode):
                self.assertEqual(self.read(self.run_script("Report_state.js", f"machine={mode}", "nojob")).machine_state, MachineState.OFFLINE)

    def test_the_scripts_never_call_anything_that_moves_the_machine(self):
        for script in list(SCRIPTS.glob("Events/*.js")) + [SCRIPTS / "Report_state.js"]:
            code = "\n".join(line for line in script.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("//"))
            for forbidden in (".enable(", ".home(", ".moveTo(", ".actuate(", ".setEnabled(", ".execute("):
                with self.subTest(script=script.name, forbidden=forbidden):
                    self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
