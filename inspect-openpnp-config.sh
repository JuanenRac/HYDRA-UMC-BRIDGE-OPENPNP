#!/usr/bin/env bash
# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Read-only OpenPnP configuration inspection
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"
trap '[ -t 0 ] && read -r -p "Press Enter to close..." _' EXIT
printf '%s\n' '*******************************************************************************' '* HYDRA-UMC-BRIDGE-OPENPNP - READ-ONLY OPENPNP PROFILE INSPECTION           *' '* 1. Parse a saved machine.xml.  2. Print non-sensitive component counts.   *' '* No OpenPnP launch, serial-port access, motion, feeder action or write.    *' '*******************************************************************************'
if [ "$#" -ne 1 ]; then
  echo 'Usage: ./inspect-openpnp-config.sh <path-to-machine.xml>' >&2
  exit 2
fi
python3 tools/inspect_openpnp_config.py --config "$1"
