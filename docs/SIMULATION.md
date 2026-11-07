# Simulation bench

The OpenPnP bridge follows boards through a pick and place machine. The simulated SMEMA neighbour replaces the conveyor handshake and the board flow tests drive the board codes, traceability and event publishing without a machine.

The simulation bench replaces the hardware with a simulated SMEMA neighbour, simulated board flow and a script harness for the OpenPnP scripts. It proves the parsing, the gating, the transports and the failure paths of the bridge; it says nothing about
a real machine, real timing or real safety functions.

## Run it

```
python -m unittest -v <modules>
```

from the `tests` folder, with `src` of this repository and `clients/python/src` of the SDK on `PYTHONPATH` (the same layout `python tools/build_test.py` uses). The
workflow named "Simulation bench" does exactly this on a clean Linux runner on every push and pull request, by hand and once a week, with nothing but Python.

## What it runs

| File | What it exercises |
|------|-------------------|
| `tests/test_smema.py` | stable reading of the SMEMA lines and the receiver side against the simulated neighbour |
| `tests/test_smema_line_simulation.py` | boards travelling tick by tick through simulated upstream and downstream conveyors, with a stalled neighbour, a stop of the cell and bad lines |
| `tests/test_smema_environment.py` | the SMEMA settings read from the environment |
| `tests/test_board_flow.py` | board flow through the bridge |
| `tests/test_event_publish.py` | the events the bridge publishes (QoS 1) |
| `tests/test_traceability.py` | one trace event per board, with the identifiers kept back by default |
| `tests/test_mqtt_transport.py` | the topic dispatch, QoS, idempotency and limits without a broker |
| `tests/test_broker_integration.py` | the same dispatch against a real MQTT broker; skipped unless the broker checkout is present |
| `tests/test_global_stop_broker.py` | the global stop over a real broker; skipped unless the broker checkout is present |

The broker scenarios start a real MQTT broker from a checkout of HYDRA-UMC-MQTT-BROKER (`HYDRA_UMC_TEST_BROKER_DIR`); the simulation job does not install it, so
those cases skip themselves there and run in the normal test run on a machine that has the broker.

## What it cannot show

A real OpenPnP installation and its machine, real conveyors and SMEMA wiring, feeders and cameras. The hardware row of the status table therefore stays at "simulated" until a person has run the bridge on a real setup.
