# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Board-flow tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState
from hydra_umc_bridge_openpnp import (
    BoardFlow,
    BoardIdentity,
    cycle_evidence,
    handoff_evidence,
    inspect_machine_configuration,
    simulate_board_cycle,
    simulate_board_handoff,
)


def job(phase=JobPhase.LOAD, machine=MachineState.IDLE):
    return BridgeJob("pcb-job-1", "pcb-key-1", "openpnp", phase, machine, {"board_id": "pcb-42"})


class BoardFlowTests(unittest.TestCase):
    def test_load_is_traceable_and_allowed_only_when_ready(self):
        decision = BoardFlow().plan(job(), CellState.READY, "pcb-42")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.handoff, "robot-loads-board-into-pnp-fixture")

    def test_missing_board_id_is_rejected(self):
        self.assertFalse(BoardFlow().plan(job(), CellState.READY, "").allowed)

    def test_placement_is_denied_while_machine_is_running(self):
        self.assertFalse(BoardFlow().plan(job(JobPhase.PROCESS, MachineState.RUNNING), CellState.READY, "pcb-42").allowed)

    def test_a_phase_unknown_to_this_bridge_fails_safe_instead_of_crashing(self):
        # Simulates a real, if unlikely, coupling risk: HYDRA_UMC_SDK (a
        # separate repo this bridge doesn't control) adding a JobPhase this
        # bridge's own _handoffs table hasn't been updated for yet. A bare
        # string that isn't one of the real JobPhase members reproduces
        # exactly that "unrecognized key" condition without needing the SDK
        # to actually define a new phase first.
        unknown_phase_job = BridgeJob("pcb-job-2", "pcb-key-2", "openpnp", "SOME_FUTURE_PHASE", MachineState.IDLE, {"board_id": "pcb-42"})
        decision = BoardFlow().plan(unknown_phase_job, CellState.READY, "pcb-42")
        self.assertEqual(decision.handoff, "unrecognized-phase")
        self.assertFalse(decision.allowed)

    def test_machine_configuration_is_summarized_read_only(self):
        xml = (
            "<openpnp-machine><machine class=\"ReferenceMachine\">"
            "<head/><camera/><camera/><driver/><feeder/><feeder/>"
            "<actuators><actuator/><actuator/><actuator/></actuators>"
            "<nozzle-tips><nozzle-tip/><nozzle-tip/></nozzle-tips>"
            "<signalers><actuator-signaler/></signalers>"
            "</machine></openpnp-machine>"
        )
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "machine.xml"
            config.write_text(xml, encoding="utf-8")
            profile = inspect_machine_configuration(config)
        self.assertTrue(profile.available)
        self.assertEqual(profile.machine_class, "ReferenceMachine")
        self.assertEqual(
            (
                profile.head_count,
                profile.camera_count,
                profile.driver_count,
                profile.feeder_count,
                profile.actuator_count,
                profile.nozzle_tip_count,
                profile.signaler_count,
            ),
            (1, 2, 1, 2, 3, 2, 1),
        )

    def test_machine_configuration_without_signalers_reports_zero(self):
        # signalers is an optional container - a machine that never
        # configured one must report 0, not crash on a missing element.
        xml = """<openpnp-machine><machine class=\"ReferenceMachine\"><head/></machine></openpnp-machine>"""
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "machine.xml"
            config.write_text(xml, encoding="utf-8")
            profile = inspect_machine_configuration(config)
        self.assertEqual(profile.signaler_count, 0)
        self.assertEqual(profile.actuator_count, 0)
        self.assertEqual(profile.nozzle_tip_count, 0)

    def test_invalid_machine_configuration_fails_safe(self):
        profile = inspect_machine_configuration("not-a-real-machine.xml")
        self.assertFalse(profile.available)

    def test_oversized_or_doctype_machine_configuration_is_not_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            oversized = workspace / "oversized.xml"
            oversized.write_bytes(b" " * (4 * 1024 * 1024 + 1))
            self.assertFalse(inspect_machine_configuration(oversized).available)

            doctype = workspace / "doctype.xml"
            doctype.write_text("<!DOCTYPE openpnp-machine><openpnp-machine><machine/></openpnp-machine>", encoding="utf-8")
            profile = inspect_machine_configuration(doctype)
        self.assertFalse(profile.available)
        self.assertIn("DOCTYPE", profile.reason)

    def test_simulated_handoff_binds_a_valid_identity_without_machine_io(self):
        identity = BoardIdentity("pcb-42", "lumen-demo", "r1", "lot-20260830")
        result = simulate_board_handoff(job(), CellState.READY, identity)
        self.assertTrue(result.allowed)
        self.assertEqual(result.mode, "simulation-only")
        self.assertEqual(result.handoff, "robot-loads-board-into-pnp-fixture")
        self.assertEqual(len(result.identity_fingerprint or ""), 64)

    def test_simulated_handoff_denies_a_job_identity_mismatch(self):
        identity = BoardIdentity("pcb-43", "lumen-demo", "r1", "lot-20260830")
        result = simulate_board_handoff(job(), CellState.READY, identity)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "job board_id does not match the explicit board identity")

    def test_simulated_handoff_denies_ambiguous_identity(self):
        identity = BoardIdentity("pcb 42", "lumen-demo", "r1", "lot-20260830")
        result = simulate_board_handoff(job(), CellState.READY, identity)
        self.assertFalse(result.allowed)
        self.assertEqual(result.handoff, "none")

    def test_simulated_productive_cycle_is_ordered_and_allowed_when_ready(self):
        identity = BoardIdentity("pcb-42", "lumen-demo", "r1", "lot-20260830")
        cycle = simulate_board_cycle(CellState.READY, MachineState.IDLE, identity)
        self.assertTrue(cycle.allowed)
        self.assertEqual(
            [step.handoff for step in cycle.steps],
            [
                "verify-board-and-fixture",
                "robot-loads-board-into-pnp-fixture",
                "openpnp-places-declared-job",
                "robot-removes-board-from-fixture",
                "record-completed-board-handoff",
            ],
        )
        self.assertTrue(all(step.mode == "simulation-only" for step in cycle.steps))

    def test_simulated_productive_cycle_denies_all_productive_phases_when_running(self):
        identity = BoardIdentity("pcb-42", "lumen-demo", "r1", "lot-20260830")
        cycle = simulate_board_cycle(CellState.READY, MachineState.RUNNING, identity)
        self.assertFalse(cycle.allowed)
        self.assertTrue(all(not step.allowed for step in cycle.steps))
        self.assertTrue(all(step.identity_fingerprint is None for step in cycle.steps))

    def test_handoff_evidence_has_a_schema_and_excludes_raw_identity(self):
        identity = BoardIdentity("pcb-42", "lumen-demo", "r1", "lot-20260830")
        result = simulate_board_handoff(job(JobPhase.LOAD), CellState.READY, identity)
        evidence = handoff_evidence(JobPhase.LOAD, result).to_dict()
        self.assertEqual(evidence["schema_version"], "1.0")
        self.assertEqual(evidence["mode"], "simulation-only")
        self.assertEqual(evidence["phase"], "LOAD")
        self.assertEqual(len(evidence["identity_fingerprint"] or ""), 64)
        self.assertNotIn("pcb-42", str(evidence))
        self.assertNotIn("lumen-demo", str(evidence))

    def test_cycle_evidence_preserves_productive_phase_order(self):
        identity = BoardIdentity("pcb-42", "lumen-demo", "r1", "lot-20260830")
        evidence = cycle_evidence(simulate_board_cycle(CellState.READY, MachineState.IDLE, identity))
        self.assertEqual(
            [entry.phase for entry in evidence],
            ["PREPARE", "LOAD", "PROCESS", "UNLOAD", "COMPLETE"],
        )

    def test_simulation_clis_emit_non_sensitive_evidence(self):
        root = Path(__file__).resolve().parent.parent
        environment = os.environ.copy()
        environment["HYDRA_UMC_SDK_ROOT"] = str(root.parent / "HYDRA-UMC-SDK")
        command = [
            sys.executable,
            str(root / "tools" / "simulate_handoff.py"),
            "--board-id",
            "PCB-42",
            "--recipe-id",
            "LUMEN-DEMO",
            "--revision",
            "R1",
            "--lot-id",
            "LOT-20260830",
        ]
        output = subprocess.run(
            command,
            check=True,
            capture_output=True,
            cwd=root,
            encoding="utf-8",
            env=environment,
        ).stdout
        evidence = json.loads(output)
        self.assertEqual(evidence["mode"], "simulation-only")
        self.assertNotIn("PCB-42", output)
        self.assertNotIn("LUMEN-DEMO", output)

    def test_openpnp_menu_script_remains_read_only(self):
        script_path = (
            Path(__file__).resolve().parent.parent
            / "openpnp-scripts"
            / "HYDRA-UMC"
            / "inspect_profile.js"
        )
        script = script_path.read_text(encoding="utf-8")
        for required_call in (
            "machine.getHeads()",
            "machine.getCameras()",
            "machine.getDrivers()",
            "machine.getFeeders()",
            "machine.getAllActuators()",
            "machine.getSignalers()",
            "machine.getNozzleTips()",
            "javax.swing.JOptionPane.showMessageDialog",
        ):
            self.assertIn(required_call, script)
        for forbidden_call in (
            ".enable(",
            ".home(",
            ".moveTo(",
            ".actuate(",
            ".feed(",
            "config.scriptState",
        ):
            self.assertNotIn(forbidden_call, script)


if __name__ == "__main__":
    unittest.main()
