<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Simulation evidence contract
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC OpenPnP Hand-off Evidence Contract

Schema `1.0` represents only a local `simulation-only` result. It is not proof
that OpenPnP, a LumenPnP controller, a robot or a physical PCB performed an
action. The producer never opens a serial port, starts OpenPnP or sends a
machine command.

Each JSON evidence item contains:

- `schema_version`: evidence contract version.
- `mode`: currently always `simulation-only`.
- `phase`: one of `PREPARE`, `LOAD`, `PROCESS`, `UNLOAD` or `COMPLETE`.
- `allowed`, `handoff` and `reason`: shared SDK/bridge decision details.
- `identity_fingerprint`: SHA-256 fingerprint only when allowed; it does not
  expose raw board, recipe, revision or lot identifiers.

The optional `tools/simulate_handoff.py` and `tools/simulate_cycle.py` CLI
programs emit these records. A future authorised integration must keep the
evidence mode distinct from confirmed physical execution.
