#!/usr/bin/env python3
# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Read-only OpenPnP configuration inspector
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Report a safe summary of a saved OpenPnP machine XML configuration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sdk_root = Path(os.environ.get("HYDRA_UMC_SDK_ROOT", ROOT.parent / "HYDRA-UMC-SDK"))
sys.path.insert(0, str(sdk_root / "clients" / "python" / "src"))

from hydra_umc_bridge_openpnp import inspect_machine_configuration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read an OpenPnP machine.xml file without opening OpenPnP or sending machine commands."
    )
    parser.add_argument("--config", required=True, help="Path to OpenPnP machine.xml")
    parser.add_argument("--json", action="store_true", help="Emit the profile summary as JSON")
    args = parser.parse_args()

    profile = inspect_machine_configuration(args.config)
    if args.json:
        print(json.dumps(asdict(profile), indent=2, ensure_ascii=False))
    else:
        print(f"OPENPNP_PROFILE={'PASS' if profile.available else 'FAIL'}")
        print(profile.reason)
        if profile.available:
            print(
                "machine_class={0} heads={1} cameras={2} drivers={3} feeders={4} "
                "actuators={5} nozzle_tips={6} signalers={7}".format(
                    profile.machine_class,
                    profile.head_count,
                    profile.camera_count,
                    profile.driver_count,
                    profile.feeder_count,
                    profile.actuator_count,
                    profile.nozzle_tip_count,
                    profile.signaler_count,
                )
            )
    return 0 if profile.available else 1


if __name__ == "__main__":
    raise SystemExit(main())
