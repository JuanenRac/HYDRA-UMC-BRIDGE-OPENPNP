# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests/test_service.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The entry point of the service: its configuration file, --check and the start against a broker that refuses."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_sdk.bridge_contract import CellState

from hydra_umc_bridge_openpnp import mqtt_transport, service

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "deploy" / "bridge-openpnp.example.toml"


def run_main(*arguments: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = service.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, text: str) -> str:
        path = self.folder / "bridge.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_the_example_file_and_an_empty_one_are_accepted_and_default_to_inhibited(self) -> None:
        config = service.load_config(EXAMPLE)
        self.assertIs(config.cell_value, CellState.INHIBITED)
        self.assertEqual(config.mqtt.port, 1883)
        code, out, _ = run_main("--config", self.write(""), "--check")
        self.assertEqual(code, 0)
        self.assertIn("CONFIG=PASS", out)

    def test_a_wrong_file_is_refused_by_name(self) -> None:
        cases = [
            ("[mqtt]\nhots = 'x'\n", "hots"),
            ("[camera]\n", "camera"),
            ("[mqtt]\nport = 70000\n", "mqtt.port"),
            ("[mqtt]\nport = true\n", "mqtt.port"),
            ("[cell_state]\nsource = 'file'\n", "cell_state.path"),
            ("[cell_state]\nvalue = 'FINE'\n", "cell_state.value"),
            ("[state_source]\nmax_age_seconds = 5\n", "state_source.path"),
            ("[smema]\nmode = 'gpio'\n", "smema"),
            ("[smema]\nmode = 'gpio'\nchip = '/dev/gpiochip0'\nreceiver_input = 4\n", "receiver"),
            ("[smema]\nmode = 'maybe'\n", "smema"),
            ("not toml", "TOML"),
        ]
        for text, named in cases:
            with self.subTest(text=text):
                code, _, err = run_main("--config", self.write(text), "--check")
                self.assertEqual(code, 2)
                self.assertIn(named, err)

    def test_a_stale_or_unknown_cell_state_file_is_safe_stop(self) -> None:
        state = self.folder / "cell"
        config = service.parse_config({"cell_state": {"source": "file", "path": str(state), "max_age_seconds": 10}})
        now = [1000.0]
        read = service.cell_state_reader(config, clock=lambda: now[0])
        self.assertIs(read(), CellState.SAFE_STOP)  # missing
        state.write_text(CellState.INHIBITED.value, encoding="utf-8")
        os.utime(state, (1000, 1000))
        self.assertIs(read(), CellState.INHIBITED)
        now[0] = 1020.0
        self.assertIs(read(), CellState.SAFE_STOP)  # stale
        now[0] = 1000.0
        state.write_text("FINE", encoding="utf-8")
        os.utime(state, (1000, 1000))
        self.assertIs(read(), CellState.SAFE_STOP)

    def test_the_bridge_gets_the_state_source_and_the_simulated_smema_of_the_file(self) -> None:
        data = tomllib.loads("[state_source]\npath = " + json.dumps(str(self.folder / "state.json")) + "\n[smema]\nmode = 'simulated'\n")
        bridge = service.build_bridge(service.parse_config(data))
        status = bridge.handle_message(f"{mqtt_transport.TOPIC_PREFIX}cmd/status", b"{}")
        self.assertFalse(json.loads(status[0].payload)["observed"])

    def test_the_service_starts_and_exits_non_zero_when_the_broker_refuses(self) -> None:
        started: list[tuple] = []

        def refusing(bridge, host, port, client_id, **options):
            started.append((host, port, client_id, options["max_connect_attempts"]))
            raise ConnectionRefusedError("no broker here")

        path = self.write("[mqtt]\nhost = 'broker.local'\nport = 2000\nmax_connect_attempts = 1\n")
        with mock.patch.object(mqtt_transport, "run_forever", refusing), self.assertLogs(service._LOG, "ERROR"):
            code, _, _ = run_main("--config", path)
        self.assertEqual(code, 1)
        self.assertEqual(started, [("broker.local", 2000, "hydra-umc-bridge-openpnp", 1)])


if __name__ == "__main__":
    unittest.main()
