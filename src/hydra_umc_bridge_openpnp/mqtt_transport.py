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
                                                 "recipe_id", "revision", "lot_id"}} - one
                                                 traceable, always simulation-only hand-off
  hydra/bridges/openpnp/cmd/<verb>/result   <- published, one JSON result per command above
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Callable

from hydra_umc_sdk.bridge_contract import BridgeError, CellState, job_from_dict

from .board_flow import BoardFlow
from .handoff import BoardIdentity, simulate_board_handoff

TOPIC_PREFIX = "hydra/bridges/openpnp/"


class MqttPublish:
    """One real outbound MQTT publish this module decided to make."""

    __slots__ = ("topic", "payload", "retain")

    def __init__(self, topic: str, payload: str, retain: bool = False) -> None:
        self.topic = topic
        self.payload = payload
        self.retain = retain

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, MqttPublish)
            and (self.topic, self.payload, self.retain) == (other.topic, other.payload, other.retain)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MqttPublish(topic={self.topic!r}, payload={self.payload!r}, retain={self.retain!r})"


class OpenPnpMqttBridge:
    """Real (simulation-only) command dispatch for this bridge's MQTT topics."""

    def __init__(self, cell_state: Callable[[], CellState]) -> None:
        self._cell_state = cell_state
        self._board_flow = BoardFlow()

    def handle_message(self, topic: str, payload: bytes) -> list[MqttPublish]:
        """Route one real inbound MQTT message. An unrecognised `cmd/`
        sub-topic (this bridge subscribes to `cmd/#`, a wildcard) is
        silently ignored, never an error - a future sibling topic this
        version does not know about yet must never crash the message loop."""

        if not topic.startswith(TOPIC_PREFIX):
            return []
        suffix = topic[len(TOPIC_PREFIX) :]

        if suffix == "cmd/job":
            return [self._handle_job(payload)]
        if suffix == "cmd/handoff":
            return [self._handle_handoff(payload)]
        return []

    def _handle_job(self, payload: bytes) -> MqttPublish:
        result_topic = f"{TOPIC_PREFIX}cmd/job/result"
        try:
            job = job_from_dict(json.loads(payload))
            board_id = job.parameters.get("board_id")
            if not isinstance(board_id, str) or not board_id:
                raise BridgeError("job payload's parameters.board_id is required")
        except (json.JSONDecodeError, BridgeError, UnicodeDecodeError) as error:
            decision = {"allowed": False, "handoff": "none", "reason": f"malformed job payload: {error}"}
            return MqttPublish(result_topic, json.dumps(decision))
        decision = self._board_flow.plan(job, self._cell_state(), board_id)
        return MqttPublish(result_topic, json.dumps(asdict(decision)))

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
        result = simulate_board_handoff(job, self._cell_state(), identity)
        return MqttPublish(result_topic, json.dumps(asdict(result)))


def run_forever(
    bridge: OpenPnpMqttBridge,
    host: str,
    port: int = 1883,
    client_id: str = "hydra-umc-bridge-openpnp",
) -> None:
    """Connect to a real HYDRA-UMC-MQTT-BROKER and dispatch forever.

    The only place this module imports paho-mqtt - lazily, so the rest of
    this module (and every test) works on a host without it installed.
    """

    try:
        import paho.mqtt.client as mqtt  # type: ignore[import-untyped]
    except ImportError as error:
        raise RuntimeError(
            "paho-mqtt is not installed - install it to connect to a real HYDRA-UMC-MQTT-BROKER "
            "(this module's topic-dispatch/gating logic works and is tested without it)"
        ) from error

    def on_connect(client: object, userdata: object, flags: object, reason_code: object, properties: object = None) -> None:
        client.subscribe(f"{TOPIC_PREFIX}cmd/#")  # type: ignore[attr-defined]

    def on_message(client: object, userdata: object, message: object) -> None:
        for publish in bridge.handle_message(message.topic, message.payload):  # type: ignore[attr-defined]
            client.publish(publish.topic, publish.payload, retain=publish.retain)  # type: ignore[attr-defined]

    client = mqtt.Client(client_id=client_id)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port)
    client.loop_forever()
