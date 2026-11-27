# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests of the memory of the remote settings (no broker)
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A restart keeps the replay counter and the stricter switches; a relaxing value is never restored."""

import json
import os
import tempfile
import unittest

from hydra_umc_sdk.signed_commands import sign_command

from hydra_umc_bridge_openpnp.remote_settings import SETTINGS_TOPIC, SettingsVerifier, parse_remote_settings
from hydra_umc_bridge_openpnp.settings_state import STATE_ENVIRONMENT, SettingsState

KEY = b"k" * 64
NOW_MS = 1_800_000_000_000


def message(seq, issued=NOW_MS, **settings):
    body = sign_command(SETTINGS_TOPIC, {"schema": 2, "settings": settings, "seq": seq}, KEY, now_ms=issued, expires_in_ms=60_000)
    return json.dumps(body).encode()


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "state.json")

    def verifier(self, now_ms=NOW_MS):
        return SettingsVerifier(KEY, clock=lambda: now_ms / 1000, state=SettingsState(self.path))

    def apply(self, verifier, payload):
        found = parse_remote_settings(payload, verifier)
        if found:
            verifier.remember(found)
        return found


class StateFileTests(Base):
    def test_the_name_of_the_file_comes_from_the_environment_or_from_the_key_file(self):
        self.assertEqual(str(SettingsState.from_environment("a.key", {STATE_ENVIRONMENT: "x.json"}).path), "x.json")
        self.assertEqual(str(SettingsState.from_environment("a.key", {}).path), "a.key.state.json")
        self.assertIsNone(SettingsState.from_environment("", {}))

    def test_an_unreadable_file_restores_nothing(self):
        for text in ("nope", "[]", '{"seq":-1,"settings":{}}', '{"seq":3,"settings":[]}', "x" * 5000):
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(text)
            self.assertEqual(SettingsState(self.path).load(), (-1, {}), text[:20])

    def test_a_file_that_cannot_be_written_changes_nothing_else(self):
        os.mkdir(self.path)
        self.assertFalse(SettingsState(self.path).save(1, {"a": True}))

    def test_an_expired_message_is_said_and_not_applied(self):
        with self.assertLogs(level="WARNING") as log:
            self.assertIsNone(parse_remote_settings(message(5, issued=NOW_MS - 120_000, boardCode="required"), self.verifier()))
        self.assertIn("arrived expired", "\n".join(log.output))


class RestartTests(Base):
    def test_the_remembered_mode_is_applied_only_when_it_is_stricter(self):
        from hydra_umc_bridge_openpnp.remote_settings import stricter_board_code

        self.assertEqual(stricter_board_code("off", "required"), "required")
        self.assertEqual(stricter_board_code("required", "off"), "required")
        self.assertEqual(stricter_board_code("advisory", "required"), "required")
        self.assertEqual(stricter_board_code("advisory", None), "advisory")
        self.assertEqual(stricter_board_code("off", "nonsense"), "off")

    def test_the_counter_and_the_mode_are_kept(self):
        self.apply(self.verifier(), message(100, boardCode="required"))
        again = self.verifier()
        self.assertEqual(again.remembered, {"boardCode": "required"})
        self.assertIsNone(parse_remote_settings(message(99, boardCode="off"), again))


if __name__ == "__main__":
    unittest.main()
