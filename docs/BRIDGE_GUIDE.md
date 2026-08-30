<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Technical bridge guide
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP Technical Guide

## Scope and operating model

This bridge coordinates traceable PCB hand-off around OpenPnP; it is not a placement-motion, feeder or camera driver. `BoardFlow` maps SDK phases to verify/load/place/unload/record hand-offs. `BoardIdentity` binds board, recipe, revision and lot to local simulation evidence using a fingerprint rather than exposing raw identifiers. `configuration.py` reads a saved OpenPnP machine XML without opening a machine, bounds it to 4 MiB and rejects `DOCTYPE` declarations before parsing; `evidence.py` produces transport-neutral simulation records.

All current cycles are `simulation-only`. The bridge does not start OpenPnP, open a port, change `machine.xml`, move a head, feed a component or run a placement job.

## Compatible software

The current inspected format is the public OpenPnP machine configuration XML. Future live integration targets OpenPnP itself, including installations controlling LumenPnP or other OpenPnP-supported machines, only through their documented interfaces and after identity/safety validation. It is not a generic bridge for arbitrary PnP vendors.

## Scripts and verification

| Script | Purpose | Changes version/CHANGELOG? |
|---|---|---|
| `build-test.bat` / `build-test.sh` | Compile and run configuration, hand-off and evidence tests | No |
| `build.bat` / `build.sh` | Validate, then increment version and CHANGELOG | Yes, after success |

`HYDRA_UMC_SDK_ROOT` can point to the SDK checkout. The safe workflow is inspect XML, run local simulation, review evidence, then stop; none of these steps prove a machine is ready.

## Adding a new script

Use the standard repository header, a numbered console flow, explicit mutating/non-mutating behavior and `pause` in `.bat`. Keep parsing and simulation in `src/` or `tools/`, cover it with tests, and ensure no script starts OpenPnP or touches a serial port unless a separate authenticated hardware feature is explicitly designed and tested.

## Hardware acceptance gate

Identify the machine/profile and fixture, read state without motion, bind an inspected profile to a physical machine, verify board/recipe/lot traceability, test controlled stop, then conduct dry hand-off HIL trials. Native OpenPnP/machine safety remains authoritative.
