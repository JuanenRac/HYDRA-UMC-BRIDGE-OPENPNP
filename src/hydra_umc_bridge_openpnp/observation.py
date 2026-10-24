# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - What OpenPnP itself reported about the machine
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Read the machine state that OpenPnP's own event scripts write, and trust it only while it is fresh.

OpenPnP has no RPC API. What it does have is event scripts: a file named after an event (``Job.Starting.js``,
``Job.Finished.js``...) in the ``Events`` folder of its scripts directory runs when that event happens. The scripts in
``openpnp-scripts/HYDRA-UMC/Events`` write one small JSON file with the state each event implies, atomically; this module
reads it and turns it into the ``MachineState`` the shared gate needs as ``observed_machine_state``. The bridge then stops
gating on what the requester claims.

What the file can and cannot say, honestly: it says what OpenPnP last reported, not what the machine is doing now. A job that
started is ``RUNNING`` until ``Job.Finished`` says otherwise; nothing refreshes an idle machine. So a reading is only trusted
while it is younger than ``max_age_ms`` (a missing, unreadable, malformed, oversized, future-dated or stale file is ``None``,
which the bridge treats as "unknown": the job is refused), the writer must be the expected origin, and the generation must
advance, the way the laser bridge treats its GPIO evidence. ``None`` and ``OFFLINE`` are never idle.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hydra_umc_sdk.bridge_contract import MachineState

STATE_FILE_ENVIRONMENT = "HYDRA_UMC_OPENPNP_STATE_FILE"
MAX_AGE_ENVIRONMENT = "HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS"
DEFAULT_MAX_AGE_MS = 15 * 60 * 1000
EXPECTED_ORIGIN = "openpnp-events"
MAX_FILE_BYTES = 16 * 1024

# What each OpenPnP event implies. Anything the scripts do not name is not a state.
STATE_WORDS = {
    "IDLE": MachineState.IDLE,
    "RUNNING": MachineState.RUNNING,
    "HOLDING": MachineState.HOLDING,
    "FAULT": MachineState.FAULT,
    "OFFLINE": MachineState.OFFLINE,
}


@dataclass(frozen=True)
class OpenPnpObservation:
    """One reading of the state file."""

    machine_state: MachineState
    event: str
    job: str
    generation: int | None
    observed_at_ms: int | None
    reason: str = ""

    @property
    def observed(self) -> bool:
        """True when this is a real, fresh reading and not the fail-closed fallback."""
        return self.generation is not None


def _unknown(reason: str) -> OpenPnpObservation:
    return OpenPnpObservation(MachineState.OFFLINE, "", "", None, None, reason)


def read_state_file(
    path: str | os.PathLike[str],
    *,
    now_ms: int,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
    expected_origin: str = EXPECTED_ORIGIN,
    min_generation: int | None = None,
) -> OpenPnpObservation:
    """Read and validate the state file; any problem is an ``OFFLINE`` observation that says why, never an exception."""

    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or isinstance(max_age_ms, bool) or not isinstance(max_age_ms, int) or max_age_ms < 0:
        return _unknown("the clock or the maximum age is not valid")
    try:
        file_path = Path(path)
        if file_path.stat().st_size > MAX_FILE_BYTES:
            return _unknown("the state file is larger than expected")
        payload = json.loads(file_path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return _unknown("OpenPnP has not written the state file")
    except (OSError, ValueError, RecursionError):
        return _unknown("the state file cannot be read")
    if not isinstance(payload, dict):
        return _unknown("the state file is not a JSON object")
    word, event, job = payload.get("machine_state"), payload.get("event"), payload.get("job", "")
    generation, observed_at = payload.get("generation"), payload.get("observed_at_ms")
    if payload.get("origin") != expected_origin:
        return _unknown("the state file does not come from the OpenPnP event scripts")
    if not isinstance(word, str) or word not in STATE_WORDS:
        return _unknown("the state file names a state that is not known")
    if not isinstance(event, str) or not isinstance(job, str):
        return _unknown("the state file has an event or a job that is not text")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        return _unknown("the state file has no valid generation")
    if min_generation is not None and generation <= min_generation:
        return _unknown("the state file did not advance: it is a replay of a reading already seen")
    if isinstance(observed_at, bool) or not isinstance(observed_at, int) or observed_at > now_ms:
        return _unknown("the state file has no valid time of observation")
    if now_ms - observed_at > max_age_ms:
        return _unknown("the state file is older than the maximum age: OpenPnP has said nothing since")
    return OpenPnpObservation(STATE_WORDS[word], event[:64], job[:128], generation, observed_at)


class OpenPnpStateSource:
    """A callable for ``OpenPnpMqttBridge(state_source=...)``: reads the state file now, every time.

    The bridge never caches a reading: a job gated on what OpenPnP said some minutes ago is the failure this exists to avoid.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        expected_origin: str = EXPECTED_ORIGIN,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._max_age_ms = max_age_ms
        self._origin = expected_origin
        self._clock = clock

    def __call__(self) -> OpenPnpObservation:
        return read_state_file(
            self._path,
            now_ms=int(self._clock() * 1000),
            max_age_ms=self._max_age_ms,
            expected_origin=self._origin,
        )

    @classmethod
    def from_environment(cls, environment: dict[str, str] | None = None) -> "OpenPnpStateSource | None":
        """The source named by ``HYDRA_UMC_OPENPNP_STATE_FILE`` (None when it is not set); the maximum age comes from
        ``HYDRA_UMC_OPENPNP_STATE_MAX_AGE_SECONDS`` (default 900; a value that is not a positive number is the default)."""

        env = environment if environment is not None else os.environ
        path = env.get(STATE_FILE_ENVIRONMENT, "").strip()
        if not path:
            return None
        try:
            seconds = float(env.get(MAX_AGE_ENVIRONMENT, ""))
            max_age_ms = int(seconds * 1000) if seconds > 0 and seconds < 10**9 else DEFAULT_MAX_AGE_MS
        except ValueError:
            max_age_ms = DEFAULT_MAX_AGE_MS
        return cls(path, max_age_ms=max_age_ms)
