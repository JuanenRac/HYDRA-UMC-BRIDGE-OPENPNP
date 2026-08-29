# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Trace-only PCB hand-off simulation
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Validate and simulate a traceable PCB hand-off without machine I/O.

This module intentionally creates evidence only.  It never imports OpenPnP,
opens a port, starts a process, or sends a motion, feeder or actuator command.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState

from .board_flow import BoardFlow


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


@dataclass(frozen=True)
class BoardIdentity:
    """Stable non-secret identifiers which bind a simulated PCB hand-off."""

    board_id: str
    recipe_id: str
    revision: str
    lot_id: str

    def validation_error(self) -> str | None:
        """Return a fail-closed validation error, never normalizing identity."""

        for field_name, value in (
            ("board_id", self.board_id),
            ("recipe_id", self.recipe_id),
            ("revision", self.revision),
            ("lot_id", self.lot_id),
        ):
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                return f"{field_name} must be a stable identifier using letters, digits, dot, dash or underscore"
        return None

    def fingerprint(self) -> str:
        """Return a deterministic digest without exposing the identifiers."""

        canonical = "\0".join((self.board_id, self.recipe_id, self.revision, self.lot_id))
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SimulatedBoardHandoff:
    """A local simulation result which must never be treated as machine proof."""

    allowed: bool
    handoff: str
    reason: str
    identity_fingerprint: str | None
    mode: str = "simulation-only"


def simulate_board_handoff(
    job: BridgeJob,
    cell_state: CellState,
    identity: BoardIdentity,
) -> SimulatedBoardHandoff:
    """Apply identity and SDK gates without contacting OpenPnP or a machine."""

    validation_error = identity.validation_error()
    if validation_error:
        return SimulatedBoardHandoff(False, "none", validation_error, None)

    payload_board_id = job.parameters.get("board_id")
    if payload_board_id != identity.board_id:
        return SimulatedBoardHandoff(
            False,
            "none",
            "job board_id does not match the explicit board identity",
            None,
        )

    decision = BoardFlow().plan(job, cell_state, identity.board_id)
    fingerprint = identity.fingerprint() if decision.allowed else None
    return SimulatedBoardHandoff(
        decision.allowed,
        decision.handoff,
        decision.reason,
        fingerprint,
    )
