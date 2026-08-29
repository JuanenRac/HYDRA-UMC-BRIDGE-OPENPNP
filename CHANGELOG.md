<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

## [0.0.8] - 2026-08-30

- Added deterministic JSON hand-off evidence schema `1.0` and its public
  contract documentation. The record identifies only the phase, decision,
  reason and permitted SHA-256 identity fingerprint; raw board, recipe,
  revision and lot identifiers are excluded.
- Updated both local simulation CLIs to emit that evidence and added regression
  coverage for its non-sensitive fields and productive-phase order.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.7] - 2026-08-30

- Added a trace-only productive-cycle simulator for ordered `PREPARE`, `LOAD`,
  `PROCESS`, `UNLOAD` and `COMPLETE` evidence. It evaluates every phase with
  the same explicit cell/machine state, without importing or controlling
  OpenPnP.
- Added `tools/simulate_cycle.py` and regression tests proving the ordered
  READY/IDLE path and fail-closed denial of every productive phase while a
  machine is RUNNING. `ABORT` remains on its distinct shared SDK safety path.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.6] - 2026-08-30

- Added a trace-only board hand-off simulation with an explicit `BoardIdentity`
  (board, recipe, revision and lot). Stable identifiers are fail-closed and an
  allowed plan emits a deterministic SHA-256 fingerprint without exposing a
  machine-control path.
- Denied mismatched or ambiguous identities before they can be represented as
  hand-off evidence; all results declare `simulation-only` mode.
- Added the local `tools/simulate_handoff.py` CLI and three regression tests;
  it has no OpenPnP, serial or machine I/O.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.5] - 2026-08-30

- Made the read-only OpenPnP menu script visibly report its result in an
  informational dialog as well as the internal scripting console. The dialog
  contains the same class/component summary and has no machine-control path.
- Extended the read-only regression test to require the visible dialog while
  retaining the rejection of movement, homing, feeder, actuator, enablement
  and configuration-write calls.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.4] - 2026-08-30

- Added `openpnp-scripts/HYDRA-UMC/inspect_profile.js`, a manually invoked
  OpenPnP menu-script template which only reads the machine class and counts
  heads, cameras, drivers and feeders. It contains no motion, homing, feeder,
  actuator, enablement or configuration-write call.
- Added a regression test that rejects a future change which would introduce a
  machine-control call into that menu script.
- Synchronized the English README and all six translated README files with the
  seven-test coverage and explicit manual/read-only integration boundary.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.3] - 2026-08-30

- Added a read-only inspector for a saved OpenPnP `machine.xml` profile. It
  reports only the machine class and component counts; it does not start
  OpenPnP, open serial ports or send any machine command.
- Added Windows and POSIX launchers for the inspector, with explicit usage and
  no mutation path.
- Synchronized the English README and all six translated README files with the
  inspected-profile boundary and current six-test coverage.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.2] - 2026-08-30

- Made an unknown SDK job phase fail closed instead of only avoiding a
  `KeyError`: no unrecognized phase can now be marked as allowed for an
  OpenPnP board hand-off.
- Synchronized the English README and all six translated README files with
  the current version.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.1]

- Added traceable PCB hand-off coordinator, SDK safety gate and local tests.
- Added non-mutating build-test scripts and CI SDK checkout.
- Standardized README (all 7 languages) and project banner to match the
  rest of the ecosystem's established-project structure.
- Fixed a latent crash risk: `BoardFlow.plan()` looked up a job's handoff
  label with a plain dict index, which would raise an unhandled
  `KeyError` for any `JobPhase` the shared SDK might add in the future
  without this bridge's own handoff table being updated in lockstep. Now
  falls back to a real `"unrecognized-phase"` label instead of crashing -
  verified with a new test that reproduces exactly that condition.
- Promoted to `established`: manifest, docs, build-test/CI and this
  project's own real functional gap (above) all verified locally.
