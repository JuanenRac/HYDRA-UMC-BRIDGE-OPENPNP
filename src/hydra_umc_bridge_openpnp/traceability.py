# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Per-board traceability for the data lake
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Keep the story of each board that passes through the cell, and hand it to the data lake and to the OEE report.

Every hand-off of a board (verify, load, place, unload, record) already produces evidence with a fingerprint of the board
identity. This module puts those steps together per board and, when the board's cycle ends, produces:

- a ``BoardTrace``: the ordered steps, who/when, the outcome (``completed``, ``aborted`` or ``failed``) and the cycle time;
- the samples for HYDRA-UMC-DATALAKE: one ``board_handoff`` sample per step under the source ``board-<fingerprint>``
  (``phase`` ordinal, ``allowed`` 0/1), so that ``GET /query?sourceId=board-...`` gives the history of one board; and one
  ``production_event`` sample under the machine source with ``good`` (1.0 / 0.0) and ``cycleTimeS``, the convention that
  HYDRA-UMC-PRODUCTION-REPORTS computes OEE from;
- an event (QoS 1, never retained) on ``hydra/bridges/openpnp/event/board`` for anything that wants the trace live.

Privacy, as a setting: by default only the fingerprint of the board identity leaves the bridge (a digest, not the identifiers).
``include_identifiers=True`` adds the board, recipe, revision and lot to the event (never to the numeric samples), for a
plant whose data lake is allowed to hold them.

Nothing here talks to a machine. Sending to the data lake is a plain HTTP POST (``DatalakeSink``) with an injectable
transport; a data lake that is down does not stop the cell, the samples are kept and sent with the next trace.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from hydra_umc_sdk.bridge_contract import JobPhase
from hydra_umc_sdk.bridge_transport import MqttPublish

from .handoff import BoardIdentity, SimulatedBoardHandoff

TRACE_SCHEMA_VERSION = "1.0"
EVENT_TOPIC = "hydra/bridges/openpnp/event/board"
BOARD_KIND = "board_handoff"
PRODUCTION_KIND = "production_event"

OUTCOME_COMPLETED = "completed"
OUTCOME_ABORTED = "aborted"
OUTCOME_FAILED = "failed"
OUTCOMES = (OUTCOME_COMPLETED, OUTCOME_ABORTED, OUTCOME_FAILED)

MAX_OPEN_TRACES = 256  # boards in progress at once; the oldest is dropped, never the memory of the process
MAX_PENDING_SAMPLES = 5000  # samples waiting for a data lake that is down
BATCH_SAMPLES = 500  # a batch the data lake accepts (it takes 1000 by default)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PHASE_ORDINAL = {phase: index for index, phase in enumerate(JobPhase)}


class EventPublish(MqttPublish):
    """An ``MqttPublish`` that also carries its QoS (events use 1)."""

    __slots__ = ("qos",)

    def __init__(self, topic: str, payload: str, retain: bool = False, qos: int = 1) -> None:
        super().__init__(topic, payload, retain)
        self.qos = qos


@dataclass(frozen=True)
class TraceStep:
    phase: str
    allowed: bool
    handoff: str
    reason: str
    at_ms: int
    observed: bool


@dataclass(frozen=True)
class BoardTrace:
    fingerprint: str
    outcome: str
    steps: tuple[TraceStep, ...]
    started_at_ms: int
    finished_at_ms: int
    identity: dict[str, str] | None = None
    schema_version: str = TRACE_SCHEMA_VERSION

    @property
    def cycle_time_s(self) -> float:
        return max(0.0, (self.finished_at_ms - self.started_at_ms) / 1000.0)

    @property
    def good(self) -> bool:
        return self.outcome == OUTCOME_COMPLETED and all(step.allowed for step in self.steps)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "outcome": self.outcome,
            "good": self.good,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "cycle_time_s": self.cycle_time_s,
            "steps": [
                {"phase": step.phase, "allowed": step.allowed, "handoff": step.handoff, "reason": step.reason, "at_ms": step.at_ms, "observed": step.observed}
                for step in self.steps
            ],
        }
        if self.identity is not None:
            payload["identity"] = dict(self.identity)
        return payload


def datalake_samples(trace: BoardTrace, machine_source: str) -> list[dict[str, object]]:
    """The DATALAKE samples (``sourceId``, ``kind``, ``timestamp``, numeric ``fields``) that say what a trace says."""

    if not _SAFE_ID.fullmatch(machine_source):
        raise ValueError("machine_source must be a stable identifier")
    board_source = f"board-{trace.fingerprint[:32]}"
    samples: list[dict[str, object]] = []
    for step in trace.steps:
        samples.append({
            "sourceId": board_source,
            "kind": BOARD_KIND,
            "timestamp": step.at_ms,
            "fields": {"phase": float(_PHASE_ORDINAL.get(JobPhase(step.phase), -1)), "allowed": 1.0 if step.allowed else 0.0},
        })
    samples.append({
        "sourceId": machine_source,
        "kind": PRODUCTION_KIND,
        "timestamp": trace.finished_at_ms,
        "fields": {"good": 1.0 if trace.good else 0.0, "cycleTimeS": trace.cycle_time_s},
    })
    return samples


class DatalakeSink:
    """Sends samples to HYDRA-UMC-DATALAKE (``POST /ingest/batch``, with the Bearer token of an ``ingest`` role when it has one).

    ``post`` is the transport: ``post(url, body, headers) -> status``. The default uses ``urllib`` with a timeout. A sink never
    raises: it returns whether the batch was accepted, and the recorder keeps what was not.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout_s: float = 5.0,
        post: Callable[[str, bytes, dict[str, str]], int] | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http or https URL")
        self._url = base_url.rstrip("/") + "/ingest/batch"
        self._token = token
        self._timeout = timeout_s
        self._post = post if post is not None else self._urllib_post

    def _urllib_post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - the scheme was checked
                return int(response.status)
        except urllib.error.HTTPError as error:
            return int(error.code)

    def send(self, samples: list[dict[str, object]]) -> bool:
        if not samples:
            return True
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            status = self._post(self._url, json.dumps({"samples": samples}).encode(), headers)
        except Exception:  # noqa: BLE001 - a data lake that is down must never stop the cell
            return False
        return 200 <= status < 300


@dataclass
class _Open:
    steps: list[TraceStep] = field(default_factory=list)
    started_at_ms: int = 0
    identity: dict[str, str] | None = None


class BoardTraceRecorder:
    """Collects the steps of each board and closes the trace when the cycle ends.

    A cycle ends by itself with an allowed ``COMPLETE`` (``completed``) or ``ABORT`` (``aborted``), or by ``finish(..., "failed")``.
    """

    def __init__(
        self,
        machine_source: str = "openpnp",
        *,
        include_identifiers: bool = False,
        sink: DatalakeSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not _SAFE_ID.fullmatch(machine_source):
            raise ValueError("machine_source must be a stable identifier")
        self._machine_source = machine_source
        self._include = include_identifiers
        self._sink = sink
        self._clock = clock
        self._lock = threading.Lock()
        self._open: "OrderedDict[str, _Open]" = OrderedDict()
        self._pending: list[dict[str, object]] = []

    @property
    def open_boards(self) -> int:
        with self._lock:
            return len(self._open)

    @property
    def pending_samples(self) -> int:
        with self._lock:
            return len(self._pending)

    def on_handoff(self, phase: JobPhase, result: SimulatedBoardHandoff, identity: BoardIdentity) -> list[MqttPublish]:
        """Record one hand-off step. Returns the events to publish: the closed trace, when this step closed it."""

        if identity.validation_error() is not None:
            return []  # an identity that is not a stable one cannot be traced
        fingerprint = identity.fingerprint()
        now_ms = int(self._clock() * 1000)
        step = TraceStep(phase.value, bool(result.allowed), result.handoff, result.reason, now_ms, bool(result.observed))
        with self._lock:
            record = self._open.get(fingerprint)
            if record is None:
                record = _Open(started_at_ms=now_ms)
                if self._include:
                    record.identity = {"board_id": identity.board_id, "recipe_id": identity.recipe_id, "revision": identity.revision, "lot_id": identity.lot_id}
                self._open[fingerprint] = record
                while len(self._open) > MAX_OPEN_TRACES:
                    self._open.popitem(last=False)
            record.steps.append(step)
        if phase is JobPhase.ABORT and result.allowed:
            return self.finish(fingerprint, OUTCOME_ABORTED)
        if phase is JobPhase.COMPLETE and result.allowed:
            return self.finish(fingerprint, OUTCOME_COMPLETED)
        return []

    def finish(self, fingerprint: str, outcome: str) -> list[MqttPublish]:
        """Close the trace of a board with an outcome; returns the event to publish (empty when no such board is open)."""

        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        now_ms = int(self._clock() * 1000)
        with self._lock:
            record = self._open.pop(fingerprint, None)
        if record is None:
            return []
        trace = BoardTrace(fingerprint, outcome, tuple(record.steps), record.started_at_ms, now_ms, record.identity)
        self._deliver(trace)
        return [EventPublish(EVENT_TOPIC, json.dumps(trace.to_dict()))]

    def _deliver(self, trace: BoardTrace) -> None:
        with self._lock:
            self._pending.extend(datalake_samples(trace, self._machine_source))
            del self._pending[: max(0, len(self._pending) - MAX_PENDING_SAMPLES)]
        self._drain()

    def _drain(self) -> bool:
        """Send what is pending in batches the data lake accepts; stop at the first batch it does not. True when nothing is left."""
        if self._sink is None:
            return False
        while True:
            with self._lock:
                batch = self._pending[:BATCH_SAMPLES]
            if not batch:
                return True
            if not self._sink.send(batch):
                return False
            with self._lock:
                del self._pending[: len(batch)]

    def flush(self) -> bool:
        """Try again to send what a data lake that was down has not received."""
        return self._drain()
