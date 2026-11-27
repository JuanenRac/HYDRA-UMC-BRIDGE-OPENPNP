# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests/test_service.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The entry point of the service: its configuration file, --check and the start against a broker library that is not a broker."""
from __future__ import annotations

import json
import os
import sys
import tomllib
import types
from pathlib import Path

import pytest

from hydra_umc_sdk.bridge_contract import CellState

from hydra_umc_bridge_openpnp import service

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "deploy" / "bridge-openpnp.example.toml"


def test_the_example_file_and_an_empty_one_are_accepted_and_default_to_inhibited(tmp_path, capsys) -> None:
    config = service.load_config(EXAMPLE)
    assert config.cell_value is CellState.INHIBITED and config.mqtt.port == 1883
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    assert service.main(["--config", str(empty), "--check"]) == 0
    assert "CONFIG=PASS" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "named"),
    [
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
    ],
)
def test_a_wrong_file_is_refused_by_name(tmp_path, capsys, text: str, named: str) -> None:
    path = tmp_path / "bridge.toml"
    path.write_text(text, encoding="utf-8")
    assert service.main(["--config", str(path), "--check"]) == 2
    assert named in capsys.readouterr().err


def test_a_stale_or_unknown_cell_state_file_is_safe_stop(tmp_path) -> None:
    state = tmp_path / "cell"
    config = service.parse_config({"cell_state": {"source": "file", "path": str(state), "max_age_seconds": 10}})
    now = [1000.0]
    read = service.cell_state_reader(config, clock=lambda: now[0])
    assert read() is CellState.SAFE_STOP  # missing
    state.write_text(CellState.INHIBITED.value, encoding="utf-8")
    os.utime(state, (1000, 1000))
    assert read() is CellState.INHIBITED
    now[0] = 1020.0
    assert read() is CellState.SAFE_STOP  # stale
    now[0] = 1000.0
    state.write_text("FINE", encoding="utf-8")
    os.utime(state, (1000, 1000))
    assert read() is CellState.SAFE_STOP


def test_the_bridge_gets_the_state_source_and_the_simulated_smema_of_the_file(tmp_path) -> None:
    data = tomllib.loads(
        "[state_source]\npath = " + json.dumps(str(tmp_path / "state.json")) + "\n[smema]\nmode = 'simulated'\n"
    )
    bridge = service.build_bridge(service.parse_config(data))
    status = bridge.handle_message(f"{_prefix()}cmd/status", b"{}")
    assert json.loads(status[0].payload)["observed"] is False


def _prefix() -> str:
    from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX

    return TOPIC_PREFIX


def test_the_service_starts_against_a_broker_library_that_refuses_and_exits_non_zero(tmp_path, monkeypatch) -> None:
    started: list[tuple] = []

    def fake_run_forever(bridge, host, port, client_id, **options):
        started.append((host, port, client_id, options["max_connect_attempts"]))
        raise ConnectionRefusedError("no broker here")

    from hydra_umc_bridge_openpnp import mqtt_transport

    monkeypatch.setattr(mqtt_transport, "run_forever", fake_run_forever)
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    path = tmp_path / "bridge.toml"
    path.write_text("[mqtt]\nhost = 'broker.local'\nport = 2000\nmax_connect_attempts = 1\n", encoding="utf-8")
    assert service.main(["--config", str(path)]) == 1
    assert started == [("broker.local", 2000, "hydra-umc-bridge-openpnp", 1)]
