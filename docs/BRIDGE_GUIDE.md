<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Technical bridge guide
Copyright (C) JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP Technical Guide

## Scope and operating model

This bridge coordinates traceable PCB hand-off around OpenPnP; it is not a placement-motion, feeder or camera driver. `BoardFlow` maps SDK phases to verify/load/place/unload/record hand-offs. `BoardIdentity` binds board, recipe, revision and lot to local simulation evidence using a fingerprint rather than exposing raw identifiers. `configuration.py` reads a saved OpenPnP machine XML without opening a machine, bounds it to 4 MiB and rejects `DOCTYPE` declarations (whatever the file's encoding: the parser itself refuses a DOCTYPE the moment it starts); it reports head/camera/driver/feeder counts plus real actuator/nozzle-tip/signaler counts (`org.openpnp.spi.Machine`'s own `getAllActuators()`/`getNozzleTips()`/`getSignalers()`) - actuators control real hardware and signalers bind one to a real job/machine state, both safety/capability-relevant evidence. `openpnp-scripts/HYDRA-UMC/inspect_profile.js` reports counts from inside a live OpenPnP session, through the same real read-only getters. The two are not guaranteed to be identical: the saved-profile parser counts every camera, actuator and nozzle tip in the whole XML tree (machine and heads), while OpenPnP's own `machine.getCameras()` returns the machine-level cameras only; this has not been compared on a real OpenPnP installation yet, and neither has the script on the JVM OpenPnP ships with (Nashorn was removed from the JDK in version 15). `evidence.py` produces transport-neutral simulation records.

All current cycles are `simulation-only`. The bridge does not start OpenPnP, open a port, change `machine.xml`, move a head, feed a component or run a placement job.

`mqtt_transport.py` reaches this same real (simulation-only) logic over `HYDRA-UMC-MQTT-BROKER`. Unlike the sibling CNC/LASER/PRINTER3D bridges there is no `hydra/bridges/openpnp/state` topic - publishing one would imply this bridge observes a real machine, and it does not. `OpenPnpMqttBridge.handle_message()` routes `hydra/bridges/openpnp/cmd/job` (a bare gate check via `BoardFlow.plan`) and `hydra/bridges/openpnp/cmd/handoff` (a full traceable simulation via `simulate_board_handoff`, always tagged `mode: "simulation-only"` in its result), publishing `.../cmd/<verb>/result`. Nothing in this bridge observes OpenPnP, so the machine state that `cmd/job` gates on is whatever the requester declares in the message: the answer is marked `"mode": "simulation-only"` and `"observed": false`, and an `ABORT` through it is answered with `"forwarded": false` and a reason that says nothing was stopped. `cmd/job` and `cmd/handoff` keep separate idempotency key spaces (`job:<key>`, `handoff:<key>`), so a job checked with the gate can still be handed off with the same key; if handling fails after a key was claimed, the key keeps an explicit "could not be handled" answer. The board identifier follows one rule for the gate and for the trace (`^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`), and `cmd/handoff` takes the optional `slot_id`, `rack_id` and `table_id` of the identity. Every message is handled without ever raising: a payload over 16 KiB, deeply nested or unreadable JSON and any unexpected failure get a refusal on the verb's result topic. The bridge publishes `hydra/bridges/openpnp/availability` (`online` when connected; the broker publishes `offline`, the MQTT Last Will, when the connection is lost) - that is a liveness signal, not a machine state. The client uses paho-mqtt's version 2 callback API (`paho-mqtt>=2.1,<3`). Dispatch is pure in-memory logic, no real broker, OpenPnP install or machine required to test it - `paho-mqtt` (optional `[mqtt]` extra) is only imported, lazily, inside `run_forever()`.

## Observed machine state

OpenPnP has no RPC API. What it has is event scripts: a file named after an event in the `Events` folder of its scripts directory runs when that event happens. `openpnp-scripts/HYDRA-UMC/Events` holds one for `Job.Starting` (RUNNING), `Job.Placement.Complete` (RUNNING, renews the time of the reading), `Job.Finished` (IDLE), `Machine.AfterHoming` (IDLE) and `Machine.AfterDisabled` (OFFLINE), and `openpnp-scripts/HYDRA-UMC/Report_state.js` is a menu script the operator runs after a long rest (it states IDLE only if OpenPnP says the machine is enabled and not busy). Each writes one small JSON file atomically (`origin`, `generation`, `observed_at_ms`, `event`, `job`, `machine_state`) to `~/.openpnp2/hydra-umc/openpnp_state.json`, or to the path in `HYDRA_UMC_OPENPNP_STATE_FILE`, which the bridge reads too. They call nothing that enables, homes, moves or actuates the machine, and a failure to write is swallowed so that a script never stops a job.

`observation.py` reads that file and `OpenPnpMqttBridge(state_source=OpenPnpStateSource(...))` gates on it instead of on the machine state the job message claims. What the file says is what OpenPnP last reported, not what the machine does now, so a reading is only trusted while it is younger than `HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS` (default 900), must carry the origin `openpnp-events` and a valid generation and time, and is read again for every job. A file that is missing, oversized, stale, from the future, from another writer or malformed is an `OFFLINE` machine that refuses the job and says why (`observation_reason`); `observed: true` in an answer means the state was read. `cmd/status` publishes the retained `hydra/bridges/openpnp/state`. The scripts are tested in Node, with the few Java classes they use provided by a harness (`tests/openpnp_script_harness.js`); they have not run inside OpenPnP, and an event name that your version of OpenPnP does not fire is harmless: the state then stays as the last event left it until it goes stale.

## SMEMA

`smema.py` takes part in the SMEMA handshake of an SMT line. `SmemaReceiver` is the cell taking boards from an upstream machine (it reads that machine's `board available` and drives `machine ready`); `SmemaSender` is the cell giving boards to a downstream machine (it drives `board available` and reads that machine's `machine ready`). Reading is debounced (several samples must all be asserted). Driving an output tells another machine that a board may move, so it goes through the shared gate: it is asserted only for a READY cell, a machine that was observed idle (not claimed) and an empty fixture (receiver) or a staged finished board (sender); withdrawing is always allowed; `reconcile` withdraws an output whose condition stopped being true, every `ABORT` through `cmd/job` withdraws both, and a line that cannot be written leaves the output assumed asserted, never assumed withdrawn. `fixture_empty` and `board_staged` come from sensors when the bridge is given them, and from the message (which must say literally `true`) otherwise. Topics: `cmd/smema_status`, `cmd/smema_ready` `{"ready": bool, "fixture_empty": bool}`, `cmd/smema_offer` `{"available": bool, "board_staged": bool}`, and the retained `hydra/bridges/openpnp/smema`. `open_smema_gpio` requests the lines with libgpiod v2 with the output already withdrawn; SMEMA runs on 12 to 24 V opto-isolated signals, so the CM5 pins need an interface board. Everything is tested against `SimulatedSmemaNeighbour`.

## Traceability

`traceability.py` keeps the story of each board. `BoardTraceRecorder` collects the hand-offs of a board (by the fingerprint of its identity) and closes the trace when an allowed `COMPLETE` (completed) or `ABORT` (aborted) arrives, or by `finish(fingerprint, "failed")`. The closed trace goes out as an event on `hydra/bridges/openpnp/event/board` (QoS 1, not retained) and, with a `DatalakeSink`, as samples to HYDRA-UMC-DATALAKE `POST /ingest/batch`: one `board_handoff` sample per step under the source `board-<fingerprint>` (`phase` ordinal, `allowed` 0/1) and one `production_event` under the machine source with `good` and `cycleTimeS`, which is what HYDRA-UMC-PRODUCTION-REPORTS computes OEE from. Only the fingerprint leaves by default; `include_identifiers=True` adds the board, recipe, revision and lot to the event (never to the numeric samples). A data lake that is down is not an error for the cell: the samples (at most 5000) wait and are sent, in batches of 500, with the next trace or by `flush()`. At most 256 boards are in progress at once.

## The code on the board

`board_code.py` compares the DataMatrix read from the board with the board the job names, for the phases in which a board arrives (`PREPARE`, `LOAD`). `HYDRA_UMC_OPENPNP_BOARD_CODE` is `off` (default: the job is believed, as before), `advisory` (a code that was read must agree; one that could not be read changes nothing) or `required` (a board with no readable code, or with another code, is refused). A job without a `board_id` takes the single code read; several different codes cannot tell which board it is; anything that is not a stable board identifier is not a code. `VisionNodeCodeSource` gets the codes from HYDRA-UMC-VISION-NODE `POST /read-code` with a frame from a `frame_provider`; a camera or a service that fails is a code that was not read. `ABORT` is never held back by a code.

## Compatible software

The current inspected format is the public OpenPnP machine configuration XML. Future live integration targets OpenPnP itself, including installations controlling LumenPnP or other OpenPnP-supported machines, only through their documented interfaces and after identity/safety validation. It is not a generic bridge for arbitrary PnP vendors.

## Scripts and verification

| Script | Purpose | Changes version/CHANGELOG? |
|---|---|---|
| `build-test.bat` / `build-test.sh` | Compile and run configuration, hand-off and evidence tests | No |
| `build.bat` / `build.sh` | Validate, then build (never changes the version or the CHANGELOG) | No |

`HYDRA_UMC_SDK_ROOT` can point to the SDK checkout. The safe workflow is inspect XML, run local simulation, review evidence, then stop; none of these steps prove a machine is ready.

## Adding a new script

Use the standard repository header, a numbered console flow, explicit mutating/non-mutating behavior and `pause` in `.bat`. Keep parsing and simulation in `src/` or `tools/`, cover it with tests, and ensure no script starts OpenPnP or touches a serial port unless a separate authenticated hardware feature is explicitly designed and tested.

## Following the global stop

The server can announce a global stop on `<mqtt prefix>/safety/estop` (a retained `SafetyState` message: `SAFE_STOP`, later `READY`; the contract is `docs/GLOBAL_STOP.md` of HYDRA-UMC-SERVER). This bridge can follow it. It is off by default and then behaves exactly as before: it does not even subscribe to the topic.

| Switch | Default | Meaning |
|---|---|---|
| `HYDRA_UMC_OPENPNP_GLOBAL_STOP` | off | `1` makes the bridge subscribe to the announcement (QoS 1, again after every reconnect) |
| `HYDRA_UMC_OPENPNP_GLOBAL_STOP_TOPIC` | `hydra/swarm/safety/estop` | the topic, when the MQTT prefix of the server is not the default one |
| `HYDRA_UMC_OPENPNP_GLOBAL_STOP_STRICT` | off | `1` also refuses before the first announcement has been heard |

While the last announcement says `SAFE_STOP`, says anything but `READY`, or cannot be read, the command handler of the bridge refuses `cmd/job` (an abort job passes), `cmd/handoff` and asserting an SMEMA line (`cmd/smema_ready` or `cmd/smema_offer` with `true`; withdrawing a line is always allowed) with an answer that gives the reason (`global stop active (SAFE_STOP) - nothing moves until the server announces READY`); `cmd/status` and the withdrawal of an SMEMA line keep working. Only a `READY` message ends it. The announcement is read although it is retained: it is the state, not a replayed command. When the broker is lost the bridge keeps the last state it heard; a bridge that has not heard the topic yet is left as it was, unless `HYDRA_UMC_OPENPNP_GLOBAL_STOP_STRICT` is on. This is a refusal in software: the controller and the machine keep the last word, and the contract adds a stop, it never removes one. Tested against a real broker (`tests/test_global_stop_broker.py`); never run with the real server.

## Hardware acceptance gate

Identify the machine/profile and fixture, read state without motion, bind an inspected profile to a physical machine, verify board/recipe/lot traceability, test controlled stop, then conduct dry hand-off HIL trials. Native OpenPnP/machine safety remains authoritative.
