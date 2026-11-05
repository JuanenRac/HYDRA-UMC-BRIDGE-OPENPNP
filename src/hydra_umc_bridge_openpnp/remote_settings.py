# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - switches announced by the server
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The board code mode that an administrator sets in Server Admin reaches this bridge on one retained topic.

`hydra/bridges/openpnp/settings` carries `{"schema": 2, "settings": {"boardCode": "off" | "advisory" | "required"}}`. The bridge listens to it only when the host of the
bridge allows it: `HYDRA_UMC_OPENPNP_REMOTE_SETTINGS=1` (off by default). Without that switch the topic is not even subscribed and the bridge keeps what its own
environment says (`HYDRA_UMC_OPENPNP_BOARD_CODE`). A message that is too large, unreadable, of another schema, or that carries an unknown word changes nothing; an unknown
key is ignored. A mode other than `off` has an effect only where a code source is connected: without one there is nothing to compare, as before.

The message is signed with the key of the server for this bridge (the shared signed-command format of the SDK, `hydra_umc_sdk.signed_commands`); the key is in the file named by
`HYDRA_UMC_OPENPNP_SETTINGS_KEY_FILE`, and remote settings need BOTH the host switch and a usable key.
A message is applied only when its signature is valid, it has not expired, it is not from the future and its counter (`seq`) is not older than the last one applied
(a replay of an old message is refused; the same message again changes nothing). An unsigned message or one of the old unsigned format (schema 1) changes nothing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Mapping

from hydra_umc_sdk.signed_commands import CommandSigningError, load_key, verify_command

from .board_code import MODES

REMOTE_ENVIRONMENT = "HYDRA_UMC_OPENPNP_REMOTE_SETTINGS"
SETTINGS_TOPIC = "hydra/bridges/openpnp/settings"
KEY_ENVIRONMENT = "HYDRA_UMC_OPENPNP_SETTINGS_KEY_FILE"
SIGNED_SCHEMA = 2
MAX_SKEW_MS = 5_000
MAX_EXPIRES_MS = 300_000
MAX_SETTINGS_BYTES = 4096
_TRUE = {"1", "true", "yes", "on"}
_LOG = logging.getLogger(__name__)


def remote_settings_allowed(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the host of the bridge switched remote settings on."""
    source = os.environ if environ is None else environ
    return source.get(REMOTE_ENVIRONMENT, "").strip().lower() in _TRUE


class SettingsVerifier:
    """Judges the signed settings message: signature, expiry and counter. Without a key it refuses everything (`usable` is False)."""

    def __init__(self, key: bytes | None, *, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self._clock = clock
        self._last_seq = -1
        self.last_reason = ""

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, *, clock: Callable[[], float] = time.time) -> "SettingsVerifier":
        """The key comes from the file named by `HYDRA_UMC_OPENPNP_SETTINGS_KEY_FILE`; a missing or unusable key gives a verifier that refuses everything."""
        source = os.environ if environ is None else environ
        path = source.get(KEY_ENVIRONMENT, "").strip()
        if not path:
            return cls(None, clock=clock)
        try:
            return cls(load_key(path), clock=clock)
        except CommandSigningError as error:
            _LOG.warning("the key of the signed settings cannot be used, remote settings stay off: %s", error)
            return cls(None, clock=clock)

    @property
    def usable(self) -> bool:
        return self._key is not None

    def accept(self, body: Mapping[str, object]) -> bool:
        """True when the body is signed with the key, current, and not older than the last one accepted."""
        if self._key is None:
            self.last_reason = "no key"
            return False
        verdict = verify_command(SETTINGS_TOPIC, body, self._key, now_ms=int(self._clock() * 1000), max_clock_skew_ms=MAX_SKEW_MS, max_expires_in_ms=MAX_EXPIRES_MS)
        if not verdict.ok:
            self.last_reason = verdict.reason
            return False
        seq = body.get("seq")
        if type(seq) is not int or seq < 0:
            self.last_reason = "the counter is missing"
            return False
        if seq < self._last_seq:
            self.last_reason = "replay: the counter is older than the last one applied"
            return False
        self._last_seq = seq
        self.last_reason = ""
        return True


def parse_remote_settings(payload: bytes, verifier: SettingsVerifier | None = None) -> dict[str, str] | None:
    """The known switches of a message, or None when it is too large, unreadable or of another schema. An unknown word drops the whole message."""
    if verifier is None or len(payload) > MAX_SETTINGS_BYTES:
        return None
    try:
        body = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict) or body.get("schema") != SIGNED_SCHEMA or not isinstance(body.get("settings"), dict):
        return None
    if not verifier.accept(body):
        _LOG.warning("a settings message was refused: %s", verifier.last_reason)
        return None
    found: dict[str, str] = {}
    if "boardCode" in body["settings"]:
        if body["settings"]["boardCode"] not in MODES:
            return None
        found["boardCode"] = body["settings"]["boardCode"]
    return found
