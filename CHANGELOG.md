# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **`EventPublish` passes its QoS to the SDK's `MqttPublish`** instead of declaring a slot of its own; the board event is still published at QoS 1 and nothing changes on the wire.

- **The bridge can follow the global stop of the server, off by default:** with `HYDRA_UMC_OPENPNP_GLOBAL_STOP=1` it subscribes to the retained announcement on `hydra/swarm/safety/estop` (`HYDRA_UMC_OPENPNP_GLOBAL_STOP_TOPIC` changes the topic) and, while the last message says `SAFE_STOP`, says anything but `READY` or cannot be read, `cmd/job` (an abort passes), `cmd/handoff` and asserting an SMEMA line are refused with the reason in the answer; stops and read-only requests keep working and only `READY` ends it. `HYDRA_UMC_OPENPNP_GLOBAL_STOP_STRICT=1` also refuses until the first announcement has been heard. Without the switch nothing changes. `tests/test_global_stop.py` covers the guard and the refusals, `tests/test_global_stop_broker.py` runs them against a real broker on a free local port (the announcement is delivered at QoS 0, 1 and 2, a retained stop is obeyed at connect, an unreadable one fails closed).

- **The MQTT transport is tested against a real broker:** `tests/test_broker_integration.py` starts a `HYDRA-UMC-MQTT-BROKER` on a free local port and runs the bridge through the shared client: the retained availability, a command answered at QoS 0, 1 and 2, a retained command that is only a replay, messages published at each QoS, the last will after an unclean loss of the link and the way back after the broker went down and up. It skips itself when node, `paho-mqtt` or the installed broker (`HYDRA_UMC_TEST_BROKER_DIR`, default the folder next to this one) are missing.

## [0.2.1] - The universal README and its check in the CI

- **README in the universal layout:** the README and its seven translations follow the layout that the four families share (22 sections in a fixed order), with an architecture picture and a repository-structure picture drawn from `docs/architecture.json` and `docs/structure.json`; the CI validator checks both pictures and the file tree. Where the repository has a service or an MQTT transport, the README now says how to start it and which environment variables it reads.

- **The layout of the README is checked in the CI:** the validator runs `tools/universal_readme_check.py` and lists, as a warning, what differs from the universal layout of the README.

## [0.2.0] - The machine state is read from OpenPnP and sMEMA hand-over signals

- **The machine state is read from OpenPnP.** Event scripts (`Job.Starting`, `Job.Placement.Complete`, `Job.Finished`, `Machine.AfterHoming`, `Machine.AfterDisabled`) and a menu script (`Report_state.js`) in `openpnp-scripts/HYDRA-UMC` write the state each event implies to one small JSON file, atomically; `OpenPnpStateSource` reads it and the bridge gates on it instead of on the claim of the job message. A missing, stale, foreign or malformed file is an OFFLINE machine and the job is refused with the reason; answers say `observed: true` when the state was read. `cmd/status` publishes the retained `state`. The scripts are tested in Node; they have not run inside OpenPnP.
- **SMEMA hand-over signals.** `SmemaReceiver` and `SmemaSender` read and drive `board available` / `machine ready` with debounce; driving an output goes through the shared gate (READY cell, machine observed idle, empty fixture or staged board), an output is withdrawn when its condition stops being true, on every abort and when a line cannot be written. Topics `cmd/smema_status`, `cmd/smema_ready`, `cmd/smema_offer` and the retained `smema`. Tested against a simulated neighbour.
- **Per-board traceability.** `BoardTraceRecorder` puts the hand-offs of each board together and, when its cycle ends, publishes the trace on `event/board` (QoS 1) and sends HYDRA-UMC-DATALAKE one `board_handoff` sample per step and one `production_event` (`good`, `cycleTimeS`) for the OEE report. Only the fingerprint leaves by default. A data lake that is down never stops the cell.
- **The code on the board.** `HYDRA_UMC_OPENPNP_BOARD_CODE` (`off` by default, `advisory`, `required`) compares the DataMatrix read by HYDRA-UMC-VISION-NODE (`POST /read-code`) with the board of the job, fills in a missing `board_id` from the single code read and refuses another board.
- `simulate_board_handoff` takes the machine state that was read, and its result says whether it was `observed`.
- Building no longer changes the version; raising it is the explicit `bump` command (`python tools/hydra_project_tool.py bump`). The build scripts only report the version they built, and CI fails if a build script runs a bump.
- **The MQTT transport comes from the SDK.** Connecting with retries, the publish record and the message dispatcher are the shared `hydra_umc_sdk.bridge_transport` of SDK 0.3.6 instead of a copy of their own; what is specific to this bridge (its topics and what it does with a message) stays here, and its tests are unchanged.

- **Pinned to SDK 0.3.6** (dependency and contract checkout in CI). From this version the shared bridge gate fails closed: a productive job is refused when the bridge did not pass the state it read from its machine. This bridge only simulates the hand-off and reads nothing from OpenPnP, so it asks for the gate's explicit opt-in and every answer keeps saying that nothing was observed; when it reads OpenPnP it will pass the reading and the opt-in goes.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- Added `tools/hydra_project_tool.py`: the same `validate`, `test`, `version`, `status` and `bump` commands in every repository. The checks run with `HYDRA_UMC_CI=1` and fail if the version changes; only `bump` changes it.
- The SDK is now fetched at a release tag instead of the main branch, so a change of the SDK cannot break this repository by itself.
- Successful incremental build: synchronized package metadata and `hydra-umc.project.json`.

## [0.1.9]

- Successful incremental build: synchronized package metadata and `hydra-umc.project.json`.
- The licence is written as GPL-3.0-or-later in every header and in the package metadata.

## [0.1.8] - Maturity lowered to functional

- Maturity is functional: the code, tests and documentation are in place, but nothing here has been verified on real hardware yet, so the manifest no longer claims the established level.

## [0.1.7] - One key space per verb, honest job answers and a DOCTYPE check that does not depend on the encoding

- **The hand-off keeps its guarantee.** `cmd/job` and `cmd/handoff` shared one idempotency key space: a job checked with the gate and then handed off with the same key got the gate's stored answer back, without the identity fingerprint and without `"mode": "simulation-only"`. Keys are now `job:<key>` and `handoff:<key>`.
- **`cmd/job` says what it is.** The bridge does not observe OpenPnP: the machine state is whatever the requester declares. The result now carries `"mode": "simulation-only"` and `"observed": false`; an `ABORT` says `"forwarded": false` and that nothing was stopped.
- **The loop survives anything a client sends.** Deeply nested JSON, a payload larger than 16 KiB, an unreadable payload and any unexpected failure while handling a message are answered with a refusal on the result topic instead of ending `loop_forever()`. A failure after the key was claimed leaves an explicit answer for the key.
- **One board identifier rule.** `BoardFlow.plan()` accepted any board id without surrounding spaces (`../x`, `a b`, a thousand characters) while the hand-off trace required `^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`; a board could pass the gate and not be traceable. Both use the stricter rule now.
- **Placement identity over MQTT.** `cmd/handoff` reads the optional `slot_id`, `rack_id` and `table_id`, so two hand-offs through different slots no longer share a fingerprint.
- **DOCTYPE is refused whatever the encoding.** The check looked for the ASCII bytes `<!DOCTYPE`, which a UTF-16 file does not contain; the parser now refuses a DOCTYPE the moment it starts.
- **A retained state can be judged.** `availability` is `online` once connected and the broker publishes `offline` (Last Will) when the bridge dies.
- **paho-mqtt.** The client uses the version 2 callback API, which also starts with paho-mqtt 2.0; the extra now requires `paho-mqtt>=2.1,<3`.
- The unused `subprocess` import of `tools/ci_validate.py` and the missing `noqa` of `tools/inspect_openpnp_config.py` are fixed; `LICENSE` now carries the complete GPL-3.0-or-later text.
- README (all eight languages) and `docs/` updated: test counts and test file list, no "status transport" claim (this bridge has no state topic), no HYDRA-UMC-SERVER path that does not exist.
- 18 new tests (`tests/test_hardening.py`).

## [0.1.6] - Connects to a broker that demands credentials: user, password and TLS from the environment

- The MQTT client now takes its credentials and TLS from the environment of the service (`HYDRA_MQTT_USERNAME`, `HYDRA_MQTT_PASSWORD` or `HYDRA_MQTT_PASSWORD_FILE`, `HYDRA_MQTT_TLS_CA`) through `hydra_umc_sdk.mqtt_connection`, so it can reach a production HYDRA-UMC-MQTT-BROKER, which refuses anonymous clients and evaluates its ACL for the identity of the credential.
- An explicit `username`/`password` argument still wins, and a password without a user name is refused.
- The client ID must start with the `clientIdPrefix` of the bridge's credential.
- New `tests/test_mqtt_environment.py` (a fake paho client, so it runs without paho-mqtt) proves that the environment credentials and the CA reach the client, that the explicit ones win, that nothing set is an anonymous plain connection, and that a lonely password is refused.

## [0.1.5] - Retained messages are ignored and a repeated idempotency key is answered once

- **Retained messages.** `OpenPnpMqttBridge.handle_message()` takes the retain flag of the message and ignores a retained one: the broker replays it at every reconnect, so acting on it repeated a command nobody had sent again (the CNC, laser and printer bridges already did this; the OpenPnP bridge had not got the fix).
- **Idempotency keys.** The bridge accepts an `IdempotencyStore` from HYDRA-UMC-SDK: the first time a job key arrives it is evaluated and its answer kept; a repeat (QoS 1 delivers some twice, a client may retry) gets the same answer and nothing is evaluated again. docs/BRIDGE_CONTRACT.md asked bridges to do this and none did. A malformed job does not use up a key.
- Tests for retained messages and repeated keys (tests/test_idempotency.py).

## [0.1.4] - MQTT connect retries with backoff; bump script no longer embeds a literal date

- **`tools/bump_version.py`** - its own auto-generated CHANGELOG
  heading embedded a literal calendar date (`date.today().isoformat()`)
  into this public file - every real entry here is otherwise dated only
  by its position, never a literal date. The same bug, copied from the
  same template, found and fixed in the same pass across all 5 sibling
  bridges (BRIDGE-CNC/LASER/OPENPNP/PRINTER3D/ROS2) plus HYDRA-UMC-SDK
  and HYDRA-UMC-OS. Removed
  before it could ever actually land one (no prior real build in this
  repo's own history shows the script running mechanically without a
  hand-written entry replacing the stub first). Repo-hygiene fix, no
  runtime code changed, no version bump.

- **`run_forever()`'s initial MQTT connect now retries with backoff**
  (`connect_with_retry()`, new) - this bridge's process used to die
  outright if it started before HYDRA-UMC-MQTT-BROKER was listening yet,
  a real race between two independent systemd units with no ordering
  guarantee across a reboot. Only `OSError` (what an unreachable broker
  actually raises) is retried; anything else surfaces immediately as a
  real bug. Once connected, paho-mqtt's own `loop_forever()` already
  handles a later mid-session drop on its own - only the first connect
  needed this.

## [0.1.3]

- **`BoardIdentity` now tracks real, separate slot/rack/table
  identity.** `BoardFlow.plan()` and `BoardIdentity` only ever validated
  `board_id` - two different physical placements of the exact same
  board (recipe/revision/lot unchanged) were fingerprinted identically,
  discarding real traceability information. New optional fields
  `slot_id`/`rack_id`/`table_id` (default `""` = not tracked, so every
  existing caller keeps working unchanged) record which feeder slot,
  storage rack and placement table an exact hand-off actually used,
  feeding into `fingerprint()` the same way the other four fields
  already do - each still validated by the same stable-identifier shape
  when supplied, and never exposed raw in `HandoffEvidence` (only the
  opaque fingerprint changes). `tools/simulate_handoff.py`/
  `simulate_cycle.py` gain matching optional `--slot-id`/`--rack-id`/
  `--table-id` flags. 7 new tests in `tests/test_board_flow.py`
  (40 total), confirmed via a real git-stash-based regression check that
  they fail against the pre-fix source. README x7 synced (test count and
  feature description).

## [0.1.2] - The SDK's own real phase-construction rejection reached this bridge's test suite

A second, closer review found this bridge's own
`test_a_phase_unknown_to_this_bridge_fails_safe_instead_of_crashing`
still constructed a `BridgeJob` directly with a raw `"SOME_FUTURE_PHASE"`
string - HYDRA-UMC-SDK's own real fix now rejects that AT
CONSTRUCTION TIME, so the test never even reached `BoardFlow.plan()`'s
own assertion. Split in two, same as HYDRA-UMC-BRIDGE-UAV's own
already-updated test: a new
`test_constructing_a_bridge_job_with_an_unknown_phase_is_refused_by_the_sdk_itself`
proves the SDK's own real rejection, and the original test now uses a
minimal explicit double (`SimpleNamespace(phase=..., machine_state=...)`
- `plan()` calls `evaluate_job()` before its own unmapped-phase check,
so both attributes are needed) to keep proving `BoardFlow.plan()`'s own
defensive `_handoffs.get(...)` fallback still fails safe - real
defense-in-depth, not weakened to let the old construction succeed
again.

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
