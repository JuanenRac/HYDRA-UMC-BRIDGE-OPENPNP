#!/usr/bin/env python3
# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Trace-only board hand-off simulator
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Run a local board-flow simulation; this tool has no OpenPnP machine I/O."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SDK_ROOT = Path(os.environ.get("HYDRA_UMC_SDK_ROOT", ROOT.parent / "HYDRA-UMC-SDK"))
sys.path[:0] = [str(ROOT / "src"), str(SDK_ROOT / "clients" / "python" / "src")]

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState  # noqa: E402
from hydra_umc_bridge_openpnp import BoardIdentity, handoff_evidence, simulate_board_handoff  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Read explicit local simulation inputs; no defaults imply a real job."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--lot-id", required=True)
    parser.add_argument("--phase", choices=[phase.value for phase in JobPhase], default=JobPhase.LOAD.value)
    parser.add_argument("--cell-state", choices=[state.value for state in CellState], default=CellState.READY.value)
    parser.add_argument("--machine-state", choices=[state.value for state in MachineState], default=MachineState.IDLE.value)
    return parser.parse_args()


def main() -> int:
    """Print a JSON simulation result and return nonzero for a denied plan."""

    args = parse_args()
    identity = BoardIdentity(args.board_id, args.recipe_id, args.revision, args.lot_id)
    job = BridgeJob(
        "simulated-openpnp-handoff",
        "simulated-openpnp-handoff-v1",
        "hydra-umc-bridge-openpnp-simulation",
        JobPhase(args.phase),
        MachineState(args.machine_state),
        {"board_id": args.board_id},
    )
    result = simulate_board_handoff(job, CellState(args.cell_state), identity)
    print(json.dumps(handoff_evidence(JobPhase(args.phase), result).to_dict(), sort_keys=True))
    return 0 if result.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
