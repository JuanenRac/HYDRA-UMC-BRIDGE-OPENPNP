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
  hydra/bridges/openpnp/availability        <- "online" / "offline", RETAINED (the broker publishes "offline" if this bridge dies)
  hydra/bridges/openpnp/cmd/<verb>/result   <- published, one JSON result per command above

This bridge does not observe OpenPnP: a `cmd/job` answer is built from the machine state the REQUESTER declares, and
says so ("mode": "simulation-only", "observed": false). A payload larger than 16 KiB, a payload that cannot be read
and any unexpected failure while handling a message are answered with a refusal on the result topic; they never end
the loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Callable

from hydra_umc_sdk.bridge_contract import BridgeError, CellState, JobPhase, job_from_dict
from hydra_umc_sdk.job_intake import IdempotencyStore
from hydra_umc_sdk.bridge_transport import MessageDispatcher as SharedMessageDispatcher
from hydra_umc_sdk.bridge_transport import MqttPublish, connect_with_retry, open_bridge_client

from .board_flow import BoardFlow
from .handoff import BoardIdentity, simulate_board_handoff

TOPIC_PREFIX = "hydra/bridges/openpnp/"
AVAILABILITY_TOPIC = f"{TOPIC_PREFIX}availability"

# A command is a few hundred bytes; anything larger is not a command, and parsing it is how a hostile payload costs the bridge its memory or its stack.
MAX_PAYLOAD_BYTES = 16 * 1024

# This bridge drives nothing, so it has no stop command: every message waits its turn on the one lane.
STOP_VERBS: frozenset[str] = frozenset()

_LOG = logging.getLogger(__name__)


class OpenPnpMqttBridge:
    """Real (simulation-only) command dispatch for this bridge's MQTT topics."""

    def __init__(self, cell_state: Callable[[], CellState], idempotency: IdempotencyStore | None = None) -> None:
        self._cell_state = cell_state
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
        if suffix not in {"cmd/job", "cmd/handoff"}:
            return []
        if len(payload) > MAX_PAYLOAD_BYTES:
            return [self._refusal(suffix, f"payload is larger than {MAX_PAYLOAD_BYTES} bytes")]
        try:
            return [self._handle_job(payload) if suffix == "cmd/job" else self._handle_handoff(payload)]
        except Exception as error:  # noqa: BLE001 - nothing a message does may end the loop
            _LOG.exception("could not handle %s", topic)
            return [self._refusal(suffix, f"the command could not be handled: {type(error).__name__}")]

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
            if not isinstance(board_id, str) or not board_id:
                raise BridgeError("job payload's parameters.board_id is required")
        except (json.JSONDecodeError, BridgeError, UnicodeDecodeError) as error:
            decision = {"allowed": False, "handoff": "none", "reason": f"malformed job payload: {error}", "mode": "simulation-only", "observed": False}
            return MqttPublish(result_topic, json.dumps(decision))
        # one key space per verb: asking the gate with `cmd/job` and then handing off with the same job must run the hand-off
        key = f"job:{job.idempotency_key}"
        repeat = self._repeat(key, result_topic)
        if repeat is not None:
            return repeat
        try:
            decision = self._board_flow.plan(job, self._cell_state(), board_id)
            result = asdict(decision)
            # nothing here looks at OpenPnP: the machine state is whatever the requester claims, and the answer says so
            result["mode"] = "simulation-only"
            result["observed"] = False
            if job.phase is JobPhase.ABORT:
                result["forwarded"] = False
                result["reason"] = "abort acknowledged by the gate only - nothing was stopped; this bridge does not drive OpenPnP"
            return self._answer(key, MqttPublish(result_topic, json.dumps(result)))
        except Exception as error:  # noqa: BLE001
            _LOG.exception("cmd/job failed")
            return self._answer(key, self._refusal("cmd/job", f"the job could not be handled: {type(error).__name__}"))

    def _handle_handoff(self, payload: bytes) -> MqttPublish:
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
            result = {
                "allowed": False,
                "handoff": "none",
                "reason": f"malformed handoff payload: {error}",
                "identity_fingerprint": None,
                "mode": "simulation-only",
            }
            return MqttPublish(result_topic, json.dumps(result))
        key = f"handoff:{job.idempotency_key}"
        repeat = self._repeat(key, result_topic)
        if repeat is not None:
            return repeat
        try:
            result = simulate_board_handoff(job, self._cell_state(), identity)
            return self._answer(key, MqttPublish(result_topic, json.dumps(asdict(result))))
        except Exception as error:  # noqa: BLE001
            _LOG.exception("cmd/handoff failed")
            return self._answer(key, self._refusal("cmd/handoff", f"the hand-off could not be handled: {type(error).__name__}"))

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
        client.loop_forever()
    finally:
        dispatcher.close(wait=False)
