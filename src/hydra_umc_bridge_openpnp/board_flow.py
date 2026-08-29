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
        # ._handoffs currently covers every JobPhase the shared SDK defines
        # (verified in this project's own tests), but that mapping lives in
        # a SEPARATE repo (HYDRA-UMC-SDK) this bridge doesn't control - a
        # future phase added there without a matching handoff label here
        # would otherwise raise an unhandled KeyError instead of failing
        # safely, exactly the class of crash the rest of this bridge (and
        # its whole family) is built to avoid. .get() with a safe fallback
        # costs nothing today and removes that latent coupling risk.
        handoff = self._handoffs.get(job.phase, "unrecognized-phase")
        return BoardFlowDecision(decision.allowed, handoff, decision.reason)
