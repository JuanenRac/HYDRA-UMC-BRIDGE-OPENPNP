# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - High-level board-flow coordinator
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Coordinate PCB hand-off phases; this is not a placement-motion driver."""

from __future__ import annotations

from dataclasses import dataclass

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, GateDecision, JobPhase, evaluate_job


@dataclass(frozen=True)
class BoardFlowDecision:
    allowed: bool
    handoff: str
    reason: str


class BoardFlow:
    """Validate a PCB transfer before an OpenPnP integration receives it."""

    _handoffs = {
        JobPhase.PREPARE: "verify-board-and-fixture",
        JobPhase.LOAD: "robot-loads-board-into-pnp-fixture",
        JobPhase.PROCESS: "openpnp-places-declared-job",
        JobPhase.UNLOAD: "robot-removes-board-from-fixture",
        JobPhase.COMPLETE: "record-completed-board-handoff",
        JobPhase.ABORT: "request-controlled-stop",
    }

    def plan(self, job: BridgeJob, cell_state: CellState, board_id: str) -> BoardFlowDecision:
        if not board_id or board_id.strip() != board_id:
            return BoardFlowDecision(False, "none", "a stable board_id is required for traceability")
        decision: GateDecision = evaluate_job(job, cell_state)
        return BoardFlowDecision(decision.allowed, self._handoffs[job.phase], decision.reason)
