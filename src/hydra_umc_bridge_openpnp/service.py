# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - The service: one entry point, one configuration file
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Run the bridge as a service: ``python -m hydra_umc_bridge_openpnp --config /etc/hydra-umc-bridge-openpnp/bridge-openpnp.toml``.

What depends on the machine lives in the configuration file: the MQTT broker, where the state of the cell comes from, the state file the
OpenPnP event scripts write, the SMEMA lines and the idempotency store. The file is TOML; a key the service does not know is refused, so a
typo cannot silently leave a safeguard unconfigured. Credentials do not go in the file: the MQTT user, password and TLS come from the
service environment (``HYDRA_MQTT_*``). The other switches of the bridge (global stop, board code, remote settings, limits of the
transport) keep their environment variables.

Fail-closed: the state of the cell comes from ``[cell_state]``. Its default is a fixed ``INHIBITED``; a state file that is missing,
unknown or stale is ``SAFE_STOP``. The bridge only simulates a job: it never moves a machine.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from hydra_umc_sdk.bridge_contract import CellState
from hydra_umc_sdk.job_intake import IdempotencyStore

from .observation import DEFAULT_MAX_AGE_MS, OpenPnpStateSource
from .smema import (
    MODE_ENVIRONMENT,
    SimulatedSmemaNeighbour,
    SmemaConfigError,
    smema_from_environment,
)

CONFIG_ENVIRONMENT = "HYDRA_UMC_BRIDGE_OPENPNP_CONFIG"
DEFAULT_CONFIG_PATH = "/etc/hydra-umc-bridge-openpnp/bridge-openpnp.toml"
_SMEMA_NUMBERS = ("receiver_input", "receiver_output", "sender_input", "sender_output")
_SMEMA_FLAGS = ("input_active_low", "output_active_low")

_LOG = logging.getLogger(__name__)


class ConfigError(ValueError):
    """The configuration file is wrong; the message names the key."""


@dataclass(frozen=True)
class MqttSettings:
    host: str = "127.0.0.1"
    port: int = 1883
    client_id: str = "hydra-umc-bridge-openpnp"
    max_connect_attempts: int = 5
    connect_retry_delay_seconds: float = 2.0


@dataclass(frozen=True)
class ServiceConfig:
    mqtt: MqttSettings = field(default_factory=MqttSettings)
    cell_source: str = "fixed"
    cell_value: CellState = CellState.INHIBITED
    cell_path: str | None = None
    cell_max_age_seconds: float = 30.0
    state_path: str | None = None
    state_max_age_seconds: float = DEFAULT_MAX_AGE_MS / 1000
    smema: dict[str, str] = field(default_factory=dict)  # the settings of smema_from_environment, from the [smema] table
    idempotency_path: str | None = None


def _table(data: dict, name: str, allowed: set[str]) -> dict:
    table = data.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] must be a table")
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown key in [{name}]: {', '.join(unknown)}")
    return table


def _value(table: dict, name: str, key: str, kind: type, default: Any = None) -> Any:
    if key not in table:
        return default
    value: Any = table[key]
    numbers = (int, float) if kind is float else (kind,)
    if not isinstance(value, numbers) or (kind is not bool and isinstance(value, bool)):
        raise ConfigError(f"{name}.{key} must be a {kind.__name__}")
    return float(table[key]) if kind is float else table[key]


def _positive(value: float, what: str) -> float:
    if not 0 < value < 1e9:
        raise ConfigError(f"{what} must be positive")
    return value


def _smema_settings(table: dict) -> dict[str, str]:
    if not table:
        return {}
    env = {MODE_ENVIRONMENT: str(_value(table, "smema", "mode", str, "off"))}
    chip = _value(table, "smema", "chip", str)
    if chip:
        env[f"{MODE_ENVIRONMENT}_CHIP"] = chip
    for key in _SMEMA_NUMBERS:
        number = _value(table, "smema", key, int)
        if number is not None:
            env[f"{MODE_ENVIRONMENT}_{key.upper()}"] = str(number)
    for key in _SMEMA_FLAGS:
        if _value(table, "smema", key, bool, False):
            env[f"{MODE_ENVIRONMENT}_{key.upper()}"] = "1"
    # the same rules the lines are opened with, tried against lines that exist only in memory: nothing real is touched
    try:
        smema_from_environment(env, open_gpio=_no_lines)
    except SmemaConfigError as error:
        raise ConfigError(f"smema: {error}") from error
    return env


def _no_lines(chip: str, **_: object):
    neighbour = SimulatedSmemaNeighbour()
    return neighbour.board_available_line(), neighbour.output()


def parse_config(data: dict) -> ServiceConfig:
    """Turn the parsed TOML into the configuration, refusing what is unknown or wrong."""

    unknown = sorted(set(data) - {"mqtt", "cell_state", "state_source", "smema", "idempotency"})
    if unknown:
        raise ConfigError(f"unknown key in the file: {', '.join(unknown)}")
    table = _table(data, "mqtt", {"host", "port", "client_id", "max_connect_attempts", "connect_retry_delay_seconds"})
    base = MqttSettings()
    mqtt = MqttSettings(
        _value(table, "mqtt", "host", str, base.host),
        _value(table, "mqtt", "port", int, base.port),
        _value(table, "mqtt", "client_id", str, base.client_id),
        _value(table, "mqtt", "max_connect_attempts", int, base.max_connect_attempts),
        _value(table, "mqtt", "connect_retry_delay_seconds", float, base.connect_retry_delay_seconds),
    )
    if not 0 < mqtt.port <= 65535:
        raise ConfigError("mqtt.port must be 1 to 65535")

    cell = _table(data, "cell_state", {"source", "value", "path", "max_age_seconds"})
    source = _value(cell, "cell_state", "source", str, "fixed")
    if source not in ("fixed", "file"):
        raise ConfigError("cell_state.source must be fixed or file")
    try:
        value = CellState(_value(cell, "cell_state", "value", str, CellState.INHIBITED.value))
    except ValueError as error:
        raise ConfigError(f"cell_state.value must be one of {', '.join(item.value for item in CellState)}") from error
    path = _value(cell, "cell_state", "path", str)
    if source == "file" and not path:
        raise ConfigError("cell_state.path is required when the source is file")
    cell_age = _positive(_value(cell, "cell_state", "max_age_seconds", float, 30.0), "cell_state.max_age_seconds")

    state = _table(data, "state_source", {"path", "max_age_seconds"})
    state_path = _value(state, "state_source", "path", str)
    if state and not state_path:
        raise ConfigError("state_source.path is required in the [state_source] table")
    state_age = _positive(_value(state, "state_source", "max_age_seconds", float, DEFAULT_MAX_AGE_MS / 1000), "state_source.max_age_seconds")

    smema = _smema_settings(_table(data, "smema", {"mode", "chip", *_SMEMA_NUMBERS, *_SMEMA_FLAGS}))
    idempotency = _table(data, "idempotency", {"path"})
    return ServiceConfig(mqtt, source, value, path, cell_age, state_path, state_age, smema, _value(idempotency, "idempotency", "path", str))


def load_config(path: str | os.PathLike[str]) -> ServiceConfig:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror or error}") from error
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    return parse_config(data)


def cell_state_reader(config: ServiceConfig, *, clock: Callable[[], float] = time.time) -> Callable[[], CellState]:
    """The ``cell_state`` callable of the bridge: the current reading, and ``SAFE_STOP`` whenever it cannot be trusted."""

    if config.cell_source == "fixed":
        value = config.cell_value
        return lambda: value
    path, max_age = config.cell_path or "", config.cell_max_age_seconds

    def read() -> CellState:
        try:
            age = clock() - os.stat(path).st_mtime
            if not -max_age <= age <= max_age:
                return CellState.SAFE_STOP
            with open(path, encoding="utf-8") as handle:
                words = handle.read(256).split()
            return CellState(words[0])
        except (OSError, UnicodeDecodeError, ValueError, IndexError):
            return CellState.SAFE_STOP

    return read


def build_bridge(config: ServiceConfig, *, open_gpio=None, clock: Callable[[], float] = time.time):
    """The bridge the file asks for; ``open_gpio`` and ``clock`` are for tests."""

    from .mqtt_transport import OpenPnpMqttBridge

    receiver = sender = None
    if config.smema:
        receiver, sender = smema_from_environment(config.smema, open_gpio=open_gpio)
    state_source = None
    if config.state_path:
        state_source = OpenPnpStateSource(config.state_path, max_age_ms=int(config.state_max_age_seconds * 1000), clock=clock)
    store = IdempotencyStore(config.idempotency_path) if config.idempotency_path else IdempotencyStore()
    return OpenPnpMqttBridge(
        cell_state_reader(config, clock=clock),
        store,
        state_source=state_source,
        clock=clock,
        smema_receiver=receiver,
        smema_sender=sender,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra_umc_bridge_openpnp", description="HYDRA-UMC OpenPnP bridge service (simulation only: it never moves a machine)")
    parser.add_argument("--config", default=os.environ.get(CONFIG_ENVIRONMENT, DEFAULT_CONFIG_PATH), help=f"configuration file (default: ${CONFIG_ENVIRONMENT} or {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--check", action="store_true", help="read and validate the configuration, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"hydra-umc-bridge-openpnp: configuration error: {error}", file=sys.stderr)
        return 2
    from hydra_umc_sdk.bridge_transport import hardening_from_environment

    from .mqtt_transport import GLOBAL_STOP_ENVIRONMENT_NAME, run_forever

    # a misspelt limit of the transport must not be taken for no limit: it stops the start here (and `--check` says so too)
    try:
        hardening = hardening_from_environment(GLOBAL_STOP_ENVIRONMENT_NAME)
    except ValueError as error:
        print(f"hydra-umc-bridge-openpnp: configuration error: {error}", file=sys.stderr)
        return 2
    if args.check:
        print(f"CONFIG=PASS {args.config}")
        return 0
    try:
        bridge = build_bridge(config)
    except (RuntimeError, OSError, ValueError) as error:  # gpiod missing, a line or a store that cannot be opened
        print(f"hydra-umc-bridge-openpnp: {error}", file=sys.stderr)
        return 3
    mqtt = config.mqtt
    try:
        run_forever(
            bridge,
            mqtt.host,
            mqtt.port,
            mqtt.client_id,
            max_connect_attempts=mqtt.max_connect_attempts,
            connect_retry_delay_seconds=mqtt.connect_retry_delay_seconds,
            hardening=hardening,
        )
    except Exception:  # noqa: BLE001
        _LOG.exception("the bridge stopped")
    # Restart=on-failure: a non-zero exit when the loop ends brings the service back
    return 1
