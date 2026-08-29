# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Public package interface
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Board-flow coordination with OpenPnP while preserving safety ownership."""

from .board_flow import BoardFlow, BoardFlowDecision
from .configuration import OpenPnpMachineProfile, inspect_machine_configuration
from .evidence import HandoffEvidence, cycle_evidence, handoff_evidence
from .handoff import (
    BoardIdentity,
    SimulatedBoardCycle,
    SimulatedBoardHandoff,
    simulate_board_cycle,
    simulate_board_handoff,
)

__all__ = [
    "BoardFlow",
    "BoardFlowDecision",
    "BoardIdentity",
    "HandoffEvidence",
    "OpenPnpMachineProfile",
    "SimulatedBoardCycle",
    "SimulatedBoardHandoff",
    "inspect_machine_configuration",
    "cycle_evidence",
    "handoff_evidence",
    "simulate_board_cycle",
    "simulate_board_handoff",
]
