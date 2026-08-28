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


if __name__ == "__main__":
    unittest.main()
