# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests of the board code mode announced by the server (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The retained settings of the server: listened to only when the host allows it, validated, and applied to the board code mode."""

import json
import unittest
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import CellState

from hydra_umc_bridge_openpnp import OpenPnpMqttBridge
from hydra_umc_bridge_openpnp.mqtt_transport import MessageDispatcher, _on_connected
from hydra_umc_bridge_openpnp.remote_settings import REMOTE_ENVIRONMENT, SETTINGS_TOPIC, parse_remote_settings, remote_settings_allowed


def message(**settings):
    return json.dumps({"schema": 1, "settings": settings}).encode()


def make_bridge(remote, with_source=True, mode="off"):
    return OpenPnpMqttBridge(lambda: CellState.READY, code_source=(lambda: ["B1"]) if with_source else None, code_mode=mode, remote_settings=remote)


class FakeClient:
    def __init__(self):
        self.subscribed = []

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))


class ParseTests(unittest.TestCase):
    def test_the_host_allows_remote_settings_only_with_its_own_switch(self):
        self.assertFalse(remote_settings_allowed({}))
        self.assertFalse(remote_settings_allowed({REMOTE_ENVIRONMENT: "0"}))
        self.assertTrue(remote_settings_allowed({REMOTE_ENVIRONMENT: "1"}))

    def test_a_valid_message_gives_the_mode_and_anything_else_changes_nothing(self):
        self.assertEqual(parse_remote_settings(message(boardCode="required", other=1)), {"boardCode": "required"})
        for payload in (b"", b"nope", b"[]", b'{"schema":2,"settings":{}}', message(boardCode="maybe"), message(boardCode=True), b" " * 5000):
            self.assertIsNone(parse_remote_settings(payload), payload[:30])


class ApplyTests(unittest.TestCase):
    def test_without_the_host_switch_the_mode_stays(self):
        bridge = make_bridge(remote=False)
        self.assertEqual(bridge.note_remote_settings(message(boardCode="required")), {})
        self.assertEqual(bridge._code_mode, "off")

    def test_the_mode_follows_the_server_when_a_code_source_exists(self):
        bridge = make_bridge(remote=True)
        self.assertEqual(bridge.note_remote_settings(message(boardCode="advisory")), {"boardCode": "advisory"})
        self.assertEqual(bridge._code_mode, "advisory")
        bridge.note_remote_settings(message(boardCode="off"))
        self.assertEqual(bridge._code_mode, "off")

    def test_without_a_code_source_there_is_nothing_to_compare(self):
        bridge = make_bridge(remote=True, with_source=False)
        bridge.note_remote_settings(message(boardCode="required"))
        self.assertEqual(bridge._code_mode, "off")

    def test_an_invalid_message_changes_nothing(self):
        bridge = make_bridge(remote=True, mode="advisory")
        self.assertEqual(bridge.note_remote_settings(message(boardCode="maybe")), {})
        self.assertEqual(bridge._code_mode, "advisory")

    def test_the_dispatcher_reads_the_settings_before_the_retained_check_and_only_when_allowed(self):
        for remote, expected in ((True, "required"), (False, "off")):
            bridge = make_bridge(remote=remote)
            dispatcher = MessageDispatcher(bridge)
            try:
                dispatcher.on_message(FakeClient(), None, SimpleNamespace(topic=SETTINGS_TOPIC, payload=message(boardCode="required"), retain=True))
            finally:
                dispatcher.close(wait=False)
            self.assertEqual(bridge._code_mode, expected)

    def test_the_settings_topic_is_subscribed_after_a_connect_only_when_allowed(self):
        client = FakeClient()
        _on_connected(make_bridge(remote=True), None)(client)
        self.assertEqual(client.subscribed, [(SETTINGS_TOPIC, 1)])
        self.assertIsNone(_on_connected(make_bridge(remote=False), None))


if __name__ == "__main__":
    unittest.main()
