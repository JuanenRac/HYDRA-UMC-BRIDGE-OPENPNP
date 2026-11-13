# Bench tests

Every test below is **not executed**: the scripts have run against the JavaScript harness in `tests/openpnp_script_harness.js`, and the SMEMA lines against a fake libgpiod, never inside an installed OpenPnP or on a conveyor. Write a result only after a person ran the step.

## What the software already covers (no machine needed)

- The unit tests, the script harness and the broker integration test run with `python tools/hydra_project_tool.py test`.
- `inspect-openpnp-config.*` reads an OpenPnP configuration folder and reports what the bridge would use. The launchers print it as text for a person; `python tools/inspect_openpnp_config.py --config FILE` prints JSON (add `--text` for the text). Exit code 0: the file was read; 1: it could not be; 2: wrong arguments.

## Setup

- An OpenPnP installation with its machine configured and a safe test board, with the machine powered but the nozzle without a part.
- The scripts of `openpnp-scripts/` copied into the Scripts folder of OpenPnP, and the bridge reading the state file named by `HYDRA_UMC_OPENPNP_STATE_FILE`.
- For the board flow: two SMEMA lines wired through opto-isolators (12 to 24 V on the conveyor side), `HYDRA_UMC_OPENPNP_SMEMA=gpio` and the chip in `HYDRA_UMC_OPENPNP_SMEMA_CHIP`.

## Steps

| # | Step | Expected result | Result |
|---|------|-----------------|--------|
| 1 | Run the inspector on the real configuration folder. | It lists the machine objects without error. | not executed |
| 2 | Run each script from the OpenPnP Scripts menu. | The event names the script writes are the ones the bridge reads; if a name differs, record the real name. | not executed |
| 3 | Run a job and watch the state file. | The file is updated and the bridge reports it as fresh; after `HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS` without writes it is reported as stale. | not executed |
| 4 | Scan a board code and send the same job twice. | One traceability record; the second request is answered from the store. | not executed |
| 5 | With SMEMA in `simulated` mode, run the hand-off. | The hand-off completes without touching a GPIO line. | not executed |
| 6 | With SMEMA in `gpio` mode, drive the "board available" line from the upstream machine. | The bridge sees the line, answers "machine ready" only when OpenPnP is idle and releases the lines at the end. | not executed |
| 7 | Disconnect the conveyor cable during a hand-off. | The hand-off ends as failed within its timeout; no line stays asserted. | not executed |
| 8 | Send the global stop while a job runs. | The job is paused from OpenPnP and the state says so. | not executed |

## What this bench cannot show

How a real conveyor behaves at the end of its travel and the electrical levels of the SMEMA lines depend on the line; measure both before step 6.
