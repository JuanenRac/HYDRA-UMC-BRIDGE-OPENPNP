#!/usr/bin/env python3
# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Trace-only productive-cycle simulator
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Simulate an ordered PCB cycle locally; this tool has no machine I/O."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SDK_ROOT = Path(os.environ.get("HYDRA_UMC_SDK_ROOT", ROOT.parent / "HYDRA-UMC-SDK"))
sys.path[:0] = [str(ROOT / "src"), str(SDK_ROOT / "clients" / "python" / "src")]

from hydra_umc_sdk.bridge_contract import CellState, MachineState  # noqa: E402
from hydra_umc_bridge_openpnp import BoardIdentity, cycle_evidence, simulate_board_cycle  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Read explicit non-secret inputs for a local-only simulation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--lot-id", required=True)
    parser.add_argument("--cell-state", choices=[state.value for state in CellState], default=CellState.READY.value)
    parser.add_argument("--machine-state", choices=[state.value for state in MachineState], default=MachineState.IDLE.value)
    return parser.parse_args()


def main() -> int:
    """Print the ordered local result and fail nonzero if any phase is denied."""

    args = parse_args()
    identity = BoardIdentity(args.board_id, args.recipe_id, args.revision, args.lot_id)
    result = simulate_board_cycle(CellState(args.cell_state), MachineState(args.machine_state), identity)
    payload = {
        "allowed": result.allowed,
        "mode": result.mode,
        "steps": [evidence.to_dict() for evidence in cycle_evidence(result)],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
