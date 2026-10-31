# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Real MQTT transport over HYDRA-UMC-MQTT-BROKER
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Reach this bridge's already-real logic over the real MQTT broker.

Unlike the sibling CNC/LASER/PRINTER3D bridges, there is no real machine
transport to reach here at all: this bridge never imports OpenPnP, opens
a port, starts a process, or sends a motion/feeder/actuator command
(`handoff.py`'s own module docstring) - `simulate_board_handoff()`/
`simulate_board_cycle()` are explicitly trace-only, and their results are
always tagged `mode="simulation-only"`. So there is deliberately no
`hydra/bridges/openpnp/state` topic here either - publishing one would
imply this bridge observes a real machine, and it does not. What this
module exposes is exactly this bridge's real (simulated) evidence
generation, reachable over a new transport (MQTT, per the ecosystem's
own "MQTT via the real broker, real commands included" decision) - not a
new capability the bridge doesn't already have.

`OpenPnpMqttBridge.handle_message()` is the one real place topic routing
happens, and it is a pure dispatcher over `BoardFlow`/
`simulate_board_handoff` - fully testable with plain in-memory payloads,
no real MQTT broker required. `run_forever()` is the thin real-I/O glue
that lazily imports `paho-mqtt`.

Topic scheme (see HYDRA-UMC-MQTT-BROKER's own `hydra/bridges/<name>/...`
convention, `docs/BRIDGE_TOPICS.md`):
  hydra/bridges/openpnp/cmd/job             -> BridgeJob JSON (job_to_dict shape) with
                                                 parameters.board_id set - the shared
                                                 bridge-contract gate (BoardFlowDecision)
  hydra/bridges/openpnp/cmd/handoff         -> {"job": <job_to_dict>, "identity": {"board_id",
                                                 "recipe_id", "revision", "lot_id", and optionally
                                                 "slot_id", "rack_id", "table_id"}} - one
                                                 traceable, always simulation-only hand-off
  hydra/bridges/openpnp/cmd/status          -> (empty) read the state file the OpenPnP event scripts write (only with a `state_source`) and publish `state`
  hydra/bridges/openpnp/state               <- published, RETAINED, only with a `state_source`: the machine state OpenPnP last reported, with `observed`, `event`, `job` and `observed_at`
  hydra/bridges/openpnp/cmd/smema_status    -> (empty) read the SMEMA lines (only with a receiver or a sender) and publish `smema`
  hydra/bridges/openpnp/cmd/smema_ready     -> {"ready": bool, "fixture_empty": bool} tell the upstream machine that the cell can take a board (the shared gate decides)
  hydra/bridges/openpnp/cmd/smema_offer     -> {"available": bool, "board_staged": bool} tell the downstream machine that a finished board can leave (the shared gate decides)
  hydra/bridges/openpnp/smema               <- published, RETAINED: what the neighbours assert and what the cell asserts (see smema.py)
  hydra/bridges/openpnp/event/board         <- published, QoS 1, not retained, only with a `trace_recorder`: the trace of a board when its cycle ends (see traceability.py)
  hydra/bridges/openpnp/availability        <- "online" / "offline", RETAINED (the broker publishes "offline" if this bridge dies)
  hydra/bridges/openpnp/cmd/<verb>/result   <- published, one JSON result per command above

Without a `state_source` this bridge does not observe OpenPnP: a `cmd/job` answer is built from the machine state the
REQUESTER declares, and says so ("mode": "simulation-only", "observed": false). With one (the state file that the
OpenPnP event scripts write, see `observation.py`) the gate uses what OpenPnP itself reported, a reading that is old,
missing or not from those scripts is an OFFLINE machine that refuses the job, and the answer says "observed": true. A payload larger than 16 KiB, a payload that cannot be read
and any unexpected failure while handling a message are answered with a refusal on the result topic; they never end
the loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Any, Callable

from hydra_umc_sdk.bridge_contract import BridgeError, CellState, JobPhase, MachineState, job_from_dict
from hydra_umc_sdk.job_intake import IdempotencyStore
from hydra_umc_sdk.bridge_transport import MessageDispatcher as SharedMessageDispatcher
from hydra_umc_sdk.bridge_transport import MqttPublish, connect_with_retry, open_bridge_client  # noqa: F401

from .board_flow import BoardFlow
from .handoff import BoardIdentity, SimulatedBoardHandoff, simulate_board_handoff
from .board_code import CodeCheck, CodeSource, MODE_OFF, board_code_mode_from_environment, check_board_code
from .observation import OpenPnpObservation
from .smema import SmemaDecision, SmemaReceiver, SmemaSender
from .traceability import BoardTraceRecorder

TOPIC_PREFIX = "hydra/bridges/openpnp/"
AVAILABILITY_TOPIC = f"{TOPIC_PREFIX}availability"

# A command is a few hundred bytes; anything larger is not a command, and parsing it is how a hostile payload costs the bridge its memory or its stack.
MAX_PAYLOAD_BYTES = 16 * 1024

# This bridge drives nothing, so it has no stop command: every message waits its turn on the one lane.
STOP_VERBS: frozenset[str] = frozenset()

_LOG = logging.getLogger(__name__)


class OpenPnpMqttBridge:
    """Real (simulation-only) command dispatch for this bridge's MQTT topics."""

    def __init__(
        self,
        cell_state: Callable[[], CellState],
        idempotency: IdempotencyStore | None = None,
        *,
        state_source: Callable[[], OpenPnpObservation] | None = None,
        clock: Callable[[], float] = time.time,
        smema_receiver: SmemaReceiver | None = None,
        smema_sender: SmemaSender | None = None,
        fixture_empty: Callable[[], bool] | None = None,
        board_staged: Callable[[], bool] | None = None,
        trace_recorder: BoardTraceRecorder | None = None,
        code_source: CodeSource | None = None,
        code_mode: str | None = None,
    ) -> None:
        self._cell_state = cell_state
        # reads the state OpenPnP last reported (observation.OpenPnpStateSource); None keeps the old behaviour: the claim of the job
        self._state_source = state_source
        self._clock = clock
        # the SMEMA lines toward the neighbours of the cell (smema.py); `fixture_empty` / `board_staged` are sensors: when given they
        # decide, and what a requester writes in a message is ignored
        self._smema_receiver = smema_receiver
        self._smema_sender = smema_sender
        self._fixture_empty = fixture_empty
        self._board_staged = board_staged
        # keeps the story of each board and hands it to the data lake and the OEE report when its cycle ends (traceability.py)
        self._trace_recorder = trace_recorder
        # the DataMatrix on the board (board_code.py): `code_mode` is off, advisory or required; when it is not given it is read
        # from HYDRA_UMC_OPENPNP_BOARD_CODE (default off: the job is believed, as before)
        self._code_source = code_source
        self._code_mode = code_mode if code_mode is not None else board_code_mode_from_environment()
        if self._code_mode != MODE_OFF and code_source is None:
            self._code_mode = MODE_OFF  # nothing reads codes here: there is nothing to compare
        self._board_flow = BoardFlow()
        # docs/BRIDGE_CONTRACT.md: the idempotency key of a job is handled once; a repeat gets the answer that was given, nothing is run again
        self._idempotency = idempotency

    def handle_message(self, topic: str, payload: bytes, retained: bool = False) -> list[MqttPublish]:
        """Route one real inbound MQTT message. An unrecognised `cmd/`
        sub-topic (this bridge subscribes to `cmd/#`, a wildcard) is
        silently ignored, never an error - a future sibling topic this
        version does not know about yet must never crash the message loop.

        A RETAINED message is ignored: the broker replays it at every
        reconnect, so acting on it would repeat a command nobody sent again.

        This never raises: an oversized payload and any failure while handling
        the message come back as a refusal on the verb's result topic."""

        if retained or not topic.startswith(TOPIC_PREFIX):
            return []
        suffix = topic[len(TOPIC_PREFIX) :]
        if suffix in {"cmd/smema_status", "cmd/smema_ready", "cmd/smema_offer"}:
            if self._smema_receiver is None and self._smema_sender is None:
                return []
            if len(payload) > MAX_PAYLOAD_BYTES:
                return [self._refusal(suffix, f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")]
            try:
                return self._handle_smema(suffix, payload)
            except Exception as error:  # noqa: BLE001 - nothing a message does may end the loop
                _LOG.exception("could not handle %s", topic)
                self._withdraw_smema()
                return [self._refusal(suffix, f"the command could not be handled: {type(error).__name__}")]
        if suffix == "cmd/status":
            return [self._handle_status()] if self._state_source is not None else []
        if suffix not in {"cmd/job", "cmd/handoff"}:
            return []
        if len(payload) > MAX_PAYLOAD_BYTES:
            return [self._refusal(suffix, f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")]
        try:
            return [self._handle_job(payload)] if suffix == "cmd/job" else self._handle_handoff(payload)
        except Exception as error:  # noqa: BLE001 - nothing a message does may end the loop
            _LOG.exception("could not handle %s", topic)
            return [self._refusal(suffix, f"the command could not be handled: {type(error).__name__}")]

    def _read_state(self) -> OpenPnpObservation | None:
        """What OpenPnP last reported, or None without a state source. A source that fails is an OFFLINE machine, never an idle one."""
        if self._state_source is None:
            return None
        try:
            return self._state_source()
        except Exception:  # noqa: BLE001
            _LOG.exception("could not read the state OpenPnP reported")
            return OpenPnpObservation(MachineState.OFFLINE, "", "", None, None, "the state OpenPnP reported could not be read")

    def _handle_status(self) -> MqttPublish:
        observation = self._read_state()
        assert observation is not None
        payload: dict[str, object] = {
            "machine_state": observation.machine_state.value,
            "observed": observation.observed,
            "event": observation.event,
            "job": observation.job,
            "generation": observation.generation,
            "observed_at": observation.observed_at_ms,
            "published_at": int(self._clock() * 1000),
            "mode": "observed-from-openpnp-events",
        }
        if observation.reason:
            payload["reason"] = observation.reason
        return MqttPublish(f"{TOPIC_PREFIX}state", json.dumps(payload), retain=True)

    # --- SMEMA ---------------------------------------------------------------------------------------------------

    def _smema_inputs(self, claimed: dict[str, object]) -> tuple[bool, bool]:
        """`fixture_empty` and `board_staged`: a sensor decides when there is one; otherwise the requester's word, which must be literally true."""
        empty = self._fixture_empty() if self._fixture_empty is not None else claimed.get("fixture_empty") is True
        staged = self._board_staged() if self._board_staged is not None else claimed.get("board_staged") is True
        return empty is True, staged is True

    def _withdraw_smema(self) -> None:
        for output in (self._smema_receiver, self._smema_sender):
            if output is not None:
                output.withdraw()

    def _reconcile_smema(self, observed: MachineState | None, empty: bool, staged: bool) -> None:
        """Withdraw any SMEMA output whose condition has stopped being true (the cell not READY, the machine not idle, the fixture full)."""
        if self._smema_receiver is not None:
            self._smema_receiver.reconcile(self._cell_state(), observed, fixture_empty=empty)
        if self._smema_sender is not None:
            self._smema_sender.reconcile(self._cell_state(), observed, board_staged=staged)

    def _smema_state(self, extra: dict[str, object] | None = None) -> MqttPublish:
        payload: dict[str, object] = {"published_at": int(self._clock() * 1000)}
        if self._smema_receiver is not None:
            payload["board_waiting"] = self._smema_receiver.board_waiting()
            payload["machine_ready_asserted"] = self._smema_receiver.asserted
        if self._smema_sender is not None:
            payload["downstream_ready"] = self._smema_sender.downstream_ready()
            payload["board_available_asserted"] = self._smema_sender.asserted
        if extra:
            payload.update(extra)
        return MqttPublish(f"{TOPIC_PREFIX}smema", json.dumps(payload), retain=True)

    def _handle_smema(self, suffix: str, payload: bytes) -> list[MqttPublish]:
        result_topic = f"{TOPIC_PREFIX}{suffix}/result"
        request: dict[str, object] = {}
        if suffix != "cmd/smema_status":
            try:
                decoded = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": False, "reason": f"malformed payload: {error}"}))]
            if not isinstance(decoded, dict):
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": False, "reason": "the payload must be a JSON object"}))]
            request = decoded
        observation = self._read_state()
        observed = observation.machine_state if observation is not None and observation.observed else None
        empty, staged = self._smema_inputs(request)
        # first of all, withdraw what is no longer allowed: whatever the command is, the outputs follow the cell
        self._reconcile_smema(observed, empty, staged)
        if suffix == "cmd/smema_status":
            return [self._smema_state()]
        decision: SmemaDecision
        if suffix == "cmd/smema_ready":
            if self._smema_receiver is None:
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": False, "reason": "this cell has no SMEMA receiver"}))]
            wanted = request.get("ready")
            if not isinstance(wanted, bool):
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": self._smema_receiver.asserted, "reason": "ready must be true or false"}))]
            decision = self._smema_receiver.set_ready(wanted, self._cell_state(), observed, fixture_empty=empty)
        else:
            if self._smema_sender is None:
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": False, "reason": "this cell has no SMEMA sender"}))]
            wanted = request.get("available")
            if not isinstance(wanted, bool):
                return [MqttPublish(result_topic, json.dumps({"allowed": False, "asserted": self._smema_sender.asserted, "reason": "available must be true or false"}))]
            decision = self._smema_sender.offer(wanted, self._cell_state(), observed, board_staged=staged)
        result = {"allowed": decision.allowed, "asserted": decision.asserted, "reason": decision.reason, "observed": observed is not None}
        return [MqttPublish(result_topic, json.dumps(result)), self._smema_state()]

    # --- the code on the board -------------------------------------------------------------------------------------

    def _check_code(self, phase: JobPhase, declared: str | None) -> CodeCheck | None:
        """Compare the board of the job with the code on the board, for the phases in which a board arrives. None when it is not checked."""
        if self._code_mode == MODE_OFF or self._code_source is None or phase not in (JobPhase.PREPARE, JobPhase.LOAD):
            return None
        try:
            codes = list(self._code_source())
        except Exception:  # noqa: BLE001 - a camera that fails is a board whose code was not read
            _LOG.exception("could not read the code on the board")
            codes = []
        return check_board_code(declared, codes, self._code_mode)

    @staticmethod
    def _refusal(suffix: str, reason: str) -> MqttPublish:
        result: dict[str, object] = {"allowed": False, "handoff": "none", "reason": reason, "mode": "simulation-only"}
        if suffix == "cmd/handoff":
            result["identity_fingerprint"] = None
        return MqttPublish(f"{TOPIC_PREFIX}{suffix}/result", json.dumps(result))

    def _handle_job(self, payload: bytes) -> MqttPublish:
        result_topic = f"{TOPIC_PREFIX}cmd/job/result"
        try:
            job = job_from_dict(json.loads(payload))
            board_id = job.parameters.get("board_id")
            code_check = None
            if not isinstance(board_id, str) or not board_id:
                code_check = self._check_code(job.phase, None)
                if code_check is None or not code_check.allowed or not code_check.board_id:
                    raise BridgeError("job payload's parameters.board_id is required")
                board_id = code_check.board_id
            else:
                code_check = self._check_code(job.phase, board_id)
        except (json.JSONDecodeError, BridgeError, UnicodeDecodeError) as error:
            decision: Any = {"allowed": False, "handoff": "none", "reason": f"malformed job payload: {error}", "mode": "simulation-only", "observed": False}
            return MqttPublish(result_topic, json.dumps(decision))
        # one key space per verb: asking the gate with `cmd/job` and then handing off with the same job must run the hand-off
        key = f"job:{job.idempotency_key}"
        repeat = self._repeat(key, result_topic)
        if repeat is not None:
            return repeat
        try:
            observation = self._read_state()
            decision = self._board_flow.plan(job, self._cell_state(), board_id, observation.machine_state if observation is not None else None)
            result = asdict(decision)
            if code_check is not None:
                result["code_check"] = {"outcome": code_check.outcome, "board_id": code_check.board_id}
                if not code_check.allowed and job.phase is not JobPhase.ABORT:
                    result["allowed"] = False
                    result["reason"] = code_check.reason
            # without a state source nothing here looks at OpenPnP: the machine state is whatever the requester claims, and the answer says so
            result["mode"] = "simulation-only"
            result["observed"] = observation is not None and observation.observed
            if observation is not None and not observation.observed:
                result["observation_reason"] = observation.reason
            if job.phase is JobPhase.ABORT:
                result["forwarded"] = False
                result["reason"] = "abort acknowledged by the gate only - nothing was stopped; this bridge does not drive OpenPnP"
                # the one thing this bridge CAN do for an abort: stop telling its neighbours that a board may move
                self._withdraw_smema()
                if self._smema_receiver is not None or self._smema_sender is not None:
                    result["smema_withdrawn"] = True
            return self._answer(key, MqttPublish(result_topic, json.dumps(result)))
        except Exception as error:  # noqa: BLE001
            _LOG.exception("cmd/job failed")
            return self._answer(key, self._refusal("cmd/job", f"the job could not be handled: {type(error).__name__}"))

    def _handle_handoff(self, payload: bytes) -> list[MqttPublish]:
        result_topic = f"{TOPIC_PREFIX}cmd/handoff/result"
        try:
            request = json.loads(payload)
            if not isinstance(request, dict):
                raise ValueError("handoff payload must be a JSON object")
            job = job_from_dict(request["job"])
            identity_raw = request["identity"]
            identity = BoardIdentity(
                identity_raw["board_id"],
                identity_raw["recipe_id"],
                identity_raw["revision"],
                identity_raw["lot_id"],
                # which physical placement this hand-off used: without them two hand-offs through different slots share one fingerprint
                identity_raw.get("slot_id", ""),
                identity_raw.get("rack_id", ""),
                identity_raw.get("table_id", ""),
            )
        except (json.JSONDecodeError, BridgeError, KeyError, ValueError, TypeError, UnicodeDecodeError) as error:
            result: Any = {
                "allowed": False,
                "handoff": "none",
                "reason": f"malformed handoff payload: {error}",
                "identity_fingerprint": None,
                "mode": "simulation-only",
            }
            return [MqttPublish(result_topic, json.dumps(result))]
        key = f"handoff:{job.idempotency_key}"
        repeat = self._repeat(key, result_topic)
        if repeat is not None:
            return [repeat]
        try:
            observation = self._read_state()
            result = simulate_board_handoff(job, self._cell_state(), identity, observation.machine_state if observation is not None else None)
            answer = asdict(result)
            code_check = self._check_code(job.phase, identity.board_id)
            if code_check is not None:
                answer["code_check"] = {"outcome": code_check.outcome, "board_id": code_check.board_id}
                if not code_check.allowed:
                    answer["allowed"] = False
                    answer["identity_fingerprint"] = None
                    answer["reason"] = code_check.reason
                    result = SimulatedBoardHandoff(False, result.handoff, code_check.reason, None, observed=result.observed)
            answer["observed"] = observation is not None and observation.observed
            if observation is not None and not observation.observed:
                answer["observation_reason"] = observation.reason
            published = [self._answer(key, MqttPublish(result_topic, json.dumps(answer)))]
            if self._trace_recorder is not None:
                try:
                    published.extend(self._trace_recorder.on_handoff(job.phase, result, identity))
                except Exception:  # noqa: BLE001 - a trace that cannot be kept must never change the answer to the hand-off
                    _LOG.exception("could not record the trace of the board")
            return published
        except Exception as error:  # noqa: BLE001
            _LOG.exception("cmd/handoff failed")
            return [self._answer(key, self._refusal("cmd/handoff", f"the hand-off could not be handled: {type(error).__name__}"))]

    def _repeat(self, key: str, result_topic: str) -> MqttPublish | None:
        """None when this key is new (it is claimed now); otherwise the answer given the first time, which is sent again instead of running the job a second time."""
        if self._idempotency is None or self._idempotency.claim(key):
            return None
        stored = self._idempotency.recall(key)
        if stored is None:
            stored = json.dumps({"allowed": False, "handoff": "none", "reason": "this idempotency_key was already handled"})
        return MqttPublish(result_topic, stored)

    def _answer(self, key: str, publish: MqttPublish) -> MqttPublish:
        if self._idempotency is not None:
            self._idempotency.remember(key, publish.payload)
        return publish


class MessageDispatcher(SharedMessageDispatcher):
    """Takes the messages off the network thread, one at a time and in order; `stop_verbs` (none for this bridge) would get a lane of their own."""

    def __init__(self, bridge: object, stop_verbs: frozenset[str] = STOP_VERBS) -> None:
        super().__init__(bridge, TOPIC_PREFIX, stop_verbs)  # type: ignore[arg-type]


def run_forever(
    bridge: OpenPnpMqttBridge,
    host: str,
    port: int = 1883,
    client_id: str = "hydra-umc-bridge-openpnp",
    *,
    max_connect_attempts: int = 5,
    connect_retry_delay_seconds: float = 2.0,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Connect to a real HYDRA-UMC-MQTT-BROKER and dispatch forever.

    The only place this module imports paho-mqtt - lazily, so the rest of
    this module (and every test) works on a host without it installed.

    The bridge announces itself on `availability`: "online" once connected, and
    the broker publishes "offline" (the Last Will) if the connection is lost.
    """

    if password is not None and username is None:
        raise ValueError("password was given without a username - MQTT credentials need both")

    dispatcher = MessageDispatcher(bridge)
    try:
        client = open_bridge_client(
            host,
            port,
            client_id=client_id,
            topic_prefix=TOPIC_PREFIX,
            dispatcher=dispatcher,
            username=username,
            password=password,
            max_connect_attempts=max_connect_attempts,
            connect_retry_delay_seconds=connect_retry_delay_seconds,
        )
        client.loop_forever()  # type: ignore[attr-defined]
    finally:
        dispatcher.close(wait=False)
