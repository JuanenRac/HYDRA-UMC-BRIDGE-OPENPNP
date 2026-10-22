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

## Hardware acceptance gate

Identify the machine/profile and fixture, read state without motion, bind an inspected profile to a physical machine, verify board/recipe/lot traceability, test controlled stop, then conduct dry hand-off HIL trials. Native OpenPnP/machine safety remains authoritative.
