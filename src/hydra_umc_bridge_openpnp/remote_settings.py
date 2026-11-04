# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - switches announced by the server
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The board code mode that an administrator sets in Server Admin reaches this bridge on one retained topic.

`hydra/bridges/openpnp/settings` carries `{"schema": 1, "settings": {"boardCode": "off" | "advisory" | "required"}}`. The bridge listens to it only when the host of the
bridge allows it: `HYDRA_UMC_OPENPNP_REMOTE_SETTINGS=1` (off by default). Without that switch the topic is not even subscribed and the bridge keeps what its own
environment says (`HYDRA_UMC_OPENPNP_BOARD_CODE`). A message that is too large, unreadable, of another schema, or that carries an unknown word changes nothing; an unknown
key is ignored. A mode other than `off` has an effect only where a code source is connected: without one there is nothing to compare, as before.
"""

from __future__ import annotations

import json
import os
from typing import Mapping

from .board_code import MODES

REMOTE_ENVIRONMENT = "HYDRA_UMC_OPENPNP_REMOTE_SETTINGS"
SETTINGS_TOPIC = "hydra/bridges/openpnp/settings"
MAX_SETTINGS_BYTES = 4096
_TRUE = {"1", "true", "yes", "on"}


def remote_settings_allowed(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the host of the bridge switched remote settings on."""
    source = os.environ if environ is None else environ
    return source.get(REMOTE_ENVIRONMENT, "").strip().lower() in _TRUE


def parse_remote_settings(payload: bytes) -> dict[str, str] | None:
    """The known switches of a message, or None when it is too large, unreadable or of another schema. An unknown word drops the whole message."""
    if len(payload) > MAX_SETTINGS_BYTES:
        return None
    try:
        body = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict) or body.get("schema") != 1 or not isinstance(body.get("settings"), dict):
        return None
    found: dict[str, str] = {}
    if "boardCode" in body["settings"]:
        if body["settings"]["boardCode"] not in MODES:
            return None
        found["boardCode"] = body["settings"]["boardCode"]
    return found
