# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests of the board code mode announced by the server (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The retained settings of the server: listened to only when the host allows it, validated, and applied to the board code mode."""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.signed_commands import sign_command

from hydra_umc_bridge_openpnp import OpenPnpMqttBridge
from hydra_umc_bridge_openpnp.mqtt_transport import MessageDispatcher, _on_connected
from hydra_umc_bridge_openpnp.remote_settings import KEY_ENVIRONMENT, REMOTE_ENVIRONMENT, SETTINGS_TOPIC, SettingsVerifier, parse_remote_settings, remote_settings_allowed


KEY = b"k" * 64
NOW_MS = 1_800_000_000_000
_counter = [1000]


def message(*, key=KEY, seq=None, issued=NOW_MS, expires=60_000, **settings):
    """A settings message signed like the server signs it; `seq` counts up unless given."""
    if seq is None:
        _counter[0] += 1
        seq = _counter[0]
    body = sign_command(SETTINGS_TOPIC, {"schema": 2, "settings": settings, "seq": seq}, key, now_ms=issued, expires_in_ms=expires)
    return json.dumps(body).encode()


def verifier(key=KEY, now_ms=NOW_MS):
    return SettingsVerifier(key, clock=lambda: now_ms / 1000)


def make_bridge(remote, with_source=True, mode="off", key=KEY):
    return OpenPnpMqttBridge(lambda: CellState.READY, code_source=(lambda: ["B1"]) if with_source else None, code_mode=mode, remote_settings=remote, settings_verifier=verifier(key))


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
        self.assertEqual(parse_remote_settings(message(boardCode="required", other=1), verifier()), {"boardCode": "required"})
        for payload in (b"", b"nope", b"[]", b'{"schema":2,"settings":{}}', message(boardCode="maybe"), message(boardCode=True), b" " * 5000):
            self.assertIsNone(parse_remote_settings(payload, verifier()), payload[:30])

    def test_an_unsigned_or_old_format_message_is_refused(self):
        for payload in (json.dumps({"schema": 1, "settings": {"boardCode": "required", "publishState": True}}).encode(), json.dumps({"schema": 2, "settings": {"boardCode": "required", "publishState": True}, "seq": 1}).encode()):
            self.assertIsNone(parse_remote_settings(payload, verifier()))

    def test_without_a_verifier_nothing_is_accepted(self):
        self.assertIsNone(parse_remote_settings(message(boardCode="required")))

    def test_a_signature_made_with_another_key_or_altered_afterwards_is_refused(self):
        self.assertIsNone(parse_remote_settings(message(key=b'z' * 64, boardCode="required"), verifier()))
        forged = json.loads(message(boardCode="required"))
        forged["settings"] = {"x": 1}
        self.assertIsNone(parse_remote_settings(json.dumps(forged).encode(), verifier()))

    def test_an_expired_message_is_refused_and_a_fresh_one_is_accepted(self):
        self.assertIsNone(parse_remote_settings(message(expires=1_000, boardCode="required"), verifier(now_ms=NOW_MS + 5_000)))
        self.assertEqual(parse_remote_settings(message(expires=60_000, boardCode="required"), verifier(now_ms=NOW_MS + 5_000)), {"boardCode": "required"})

    def test_a_message_from_the_future_or_asking_too_long_a_life_is_refused(self):
        self.assertIsNone(parse_remote_settings(message(issued=NOW_MS + 60_000, boardCode="required"), verifier()))
        self.assertIsNone(parse_remote_settings(message(expires=3_600_000, boardCode="required"), verifier()))

    def test_an_older_message_is_a_replay_and_the_same_one_again_changes_nothing_new(self):
        judge = verifier()
        newer, older = message(seq=50, boardCode="required"), message(seq=49, boardCode="required")
        self.assertEqual(parse_remote_settings(newer, judge), {"boardCode": "required"})
        self.assertIsNone(parse_remote_settings(older, judge))
        self.assertEqual(parse_remote_settings(newer, judge), {"boardCode": "required"})

    def test_the_key_file_is_the_only_source_of_the_key(self):
        self.assertFalse(SettingsVerifier.from_environment({}).usable)
        self.assertFalse(SettingsVerifier.from_environment({KEY_ENVIRONMENT: os.path.join(tempfile.gettempdir(), "no-such-key-file")}).usable)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.key")
            with open(path, "wb") as handle:
                handle.write(KEY + b"\n")
            os.chmod(path, 0o600)
            self.assertTrue(SettingsVerifier.from_environment({KEY_ENVIRONMENT: path}).usable)
            with open(path, "wb") as handle:
                handle.write(b"short")
            self.assertFalse(SettingsVerifier.from_environment({KEY_ENVIRONMENT: path}).usable)


class ApplyTests(unittest.TestCase):
    def test_without_the_host_switch_the_mode_stays(self):
        bridge = make_bridge(remote=False)
        self.assertEqual(bridge.note_remote_settings(message(boardCode="required")), {})
        self.assertEqual(bridge._code_mode, "off")

    def test_with_the_host_switch_but_no_key_nothing_is_followed(self):
        bridge = make_bridge(remote=True, key=None)
        self.assertFalse(bridge.remote_settings)
        self.assertEqual(bridge.note_remote_settings(message(boardCode="required")), {})
        self.assertEqual(bridge._code_mode, "off")
        self.assertIsNone(_on_connected(bridge, None))

    def test_a_replayed_message_does_not_undo_a_newer_one(self):
        bridge = make_bridge(remote=True)
        self.assertEqual(bridge.note_remote_settings(message(seq=10, boardCode="required")), {"boardCode": "required"})
        self.assertEqual(bridge.note_remote_settings(message(seq=9, boardCode="off")), {})
        self.assertEqual(bridge._code_mode, "required")

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
