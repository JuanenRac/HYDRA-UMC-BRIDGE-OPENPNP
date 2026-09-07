# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Simulation evidence contract
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Create deterministic, non-sensitive evidence from local-only simulations."""

from __future__ import annotations

from dataclasses import dataclass

from hydra_umc_sdk.bridge_contract import JobPhase

from .handoff import SimulatedBoardCycle, SimulatedBoardHandoff


HANDOFF_EVIDENCE_SCHEMA_VERSION = "1.0"
_PRODUCTIVE_PHASES = (
    JobPhase.PREPARE,
    JobPhase.LOAD,
    JobPhase.PROCESS,
    JobPhase.UNLOAD,
    JobPhase.COMPLETE,
)


@dataclass(frozen=True)
class HandoffEvidence:
    """A transport-neutral record which cannot be mistaken for machine proof."""

    schema_version: str
    mode: str
    phase: str
    allowed: bool
    handoff: str
    reason: str
    identity_fingerprint: str | None

    def to_dict(self) -> dict[str, str | bool | None]:
        """Serialize only contract fields; raw board identity never enters it."""

        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "phase": self.phase,
            "allowed": self.allowed,
            "handoff": self.handoff,
            "reason": self.reason,
            "identity_fingerprint": self.identity_fingerprint,
        }


def handoff_evidence(phase: JobPhase, result: SimulatedBoardHandoff) -> HandoffEvidence:
    """Bind a simulated phase result to the stable public evidence schema."""

    return HandoffEvidence(
        HANDOFF_EVIDENCE_SCHEMA_VERSION,
        result.mode,
        phase.value,
        result.allowed,
        result.handoff,
        result.reason,
        result.identity_fingerprint,
    )


def cycle_evidence(cycle: SimulatedBoardCycle) -> tuple[HandoffEvidence, ...]:
    """Return ordered evidence for a nominal productive cycle only."""

    if len(cycle.steps) != len(_PRODUCTIVE_PHASES):
        raise ValueError("simulation cycle does not contain the complete productive phase set")
    return tuple(
        handoff_evidence(phase, result)
        for phase, result in zip(_PRODUCTIVE_PHASES, cycle.steps, strict=True)
    )
