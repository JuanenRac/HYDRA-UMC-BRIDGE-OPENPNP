# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Board-flow tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import unittest

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState
from hydra_umc_bridge_openpnp import BoardFlow


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


if __name__ == "__main__":
    unittest.main()
