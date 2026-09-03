<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

## [0.1.1] - Real MQTT transport over the real broker

- **`mqtt_transport.py`** (new) - reaches this bridge's already-real
  (simulation-only) logic (`BoardFlow.plan`, `simulate_board_handoff`)
  over `HYDRA-UMC-MQTT-BROKER`, per the ecosystem's own "MQTT via the
  real broker, real commands included" decision. Unlike the sibling CNC/
  LASER/PRINTER3D bridges there is no `state` topic - there is no real
  machine transport in this bridge to observe, publishing one would be
  dishonest. `OpenPnpMqttBridge` routes `hydra/bridges/openpnp/cmd/job`
  (a bare gate check) and `.../cmd/handoff` (a full traceable simulation,
  always tagged `mode: "simulation-only"` in its result), publishing
  `.../cmd/<verb>/result`. Dispatch is pure in-memory logic, no real
  broker, OpenPnP install or machine required to test it. `run_forever()`
  is the thin real-I/O glue, lazily importing the new optional
  `paho-mqtt` dependency. 12 new tests.

## [0.1.0] - Real actuator/signaler/nozzle-tip evidence

- Bounded read-only OpenPnP `machine.xml` inspection to 4 MiB and rejects
  `DOCTYPE` declarations before XML parsing. Oversized or entity-declaring
  files fail unavailable rather than being treated as partial machine evidence.
- **`configuration.py`** - `OpenPnpMachineProfile` gained `actuator_count`,
  `nozzle_tip_count` and `signaler_count`, real OpenPnP concepts researched
  against `org.openpnp.spi.Machine`'s own real `getAllActuators()`/
  `getSignalers()`/`getNozzleTips()` methods and a real published
  `machine.xml`
  ([github.com/openpnp/openpnp](https://github.com/openpnp/openpnp/blob/develop/src/test/resources/config/SampleJobTest/machine.xml)).
  Actuators control real hardware (vacuum valves, nozzle-tip-changer
  clamps, feeder actuation); signalers bind an actuator to a real job/
  machine state - both are safety/capability-relevant evidence this
  profile never surfaced before. `signaler_count` counts direct children
  of the `signalers` container generically, since signalers are a
  polymorphic OpenPnP concept with no single fixed tag name.
- **`openpnp-scripts/HYDRA-UMC/inspect_profile.js`** - the in-machine
  read-only profile dialog now reports the same three counts via the
  matching real, read-only `machine.getAllActuators()`/
  `.getSignalers()`/`.getNozzleTips()` calls, kept consistent with the
  offline XML parser.
- 2 new/updated regression tests, extended to also cover the JS script's
  new required calls - 17/17 tests passing.

## [0.0.9]

- Added `docs/BRIDGE_GUIDE.md`, defining OpenPnP board-flow scope, compatible
  software, script conventions and the physical hand-off acceptance gate.
- Removed the duplicated terminal BUILD & RUN section from all seven README files.
- Extended `build_test.py` so CI compiles every Python tool as well as package
  source, preventing a syntax-only regression in an operator CLI.
- Added an end-to-end test which invokes `simulate_handoff.py`, validates its
  `simulation-only` evidence, and proves raw board and recipe values are not
  present in the emitted JSON.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.8]

- Added deterministic JSON hand-off evidence schema `1.0` and its public
  contract documentation. The record identifies only the phase, decision,
  reason and permitted SHA-256 identity fingerprint; raw board, recipe,
  revision and lot identifiers are excluded.
- Updated both local simulation CLIs to emit that evidence and added regression
  coverage for its non-sensitive fields and productive-phase order.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.7]

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

## [0.0.6]

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

## [0.0.5]

- Made the read-only OpenPnP menu script visibly report its result in an
  informational dialog as well as the internal scripting console. The dialog
  contains the same class/component summary and has no machine-control path.
- Extended the read-only regression test to require the visible dialog while
  retaining the rejection of movement, homing, feeder, actuator, enablement
  and configuration-write calls.
- Synchronized the English README and all six translated README files.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.4]

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

## [0.0.3]

- Added a read-only inspector for a saved OpenPnP `machine.xml` profile. It
  reports only the machine class and component counts; it does not start
  OpenPnP, open serial ports or send any machine command.
- Added Windows and POSIX launchers for the inspector, with explicit usage and
  no mutation path.
- Synchronized the English README and all six translated README files with the
  inspected-profile boundary and current six-test coverage.
- Successful incremental build: synchronized package metadata and
  `hydra-umc.project.json`.

## [0.0.2]

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
