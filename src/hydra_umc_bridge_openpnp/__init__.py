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
from .smema import SimulatedSmemaNeighbour, SmemaReceiver, SmemaSender, open_smema_gpio
from .traceability import BoardTrace, BoardTraceRecorder, DatalakeSink, datalake_samples
from .board_code import CodeCheck, VisionNodeCodeSource, board_code_mode_from_environment, check_board_code
from .observation import OpenPnpObservation, OpenPnpStateSource, read_state_file
from .mqtt_transport import connect_with_retry, MqttPublish, OpenPnpMqttBridge, run_forever

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
    "OpenPnpMqttBridge",
    "CodeCheck",
    "VisionNodeCodeSource",
    "board_code_mode_from_environment",
    "check_board_code",
    "BoardTrace",
    "BoardTraceRecorder",
    "DatalakeSink",
    "datalake_samples",
    "SimulatedSmemaNeighbour",
    "SmemaReceiver",
    "SmemaSender",
    "open_smema_gpio",
    "OpenPnpObservation",
    "OpenPnpStateSource",
    "read_state_file",
    "MqttPublish",
    "connect_with_retry",
    "run_forever",
]
