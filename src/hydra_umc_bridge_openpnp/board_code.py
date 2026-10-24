# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - The code printed on the board
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Read the DataMatrix on a board and compare it with the board the job names.

A job says which board it is for (``parameters.board_id``). A board that arrives with another code printed on it is the wrong
board, and a hand-over that trusts the job message alone puts it into the fixture. This module compares the two:

- ``match``: the code read is the board of the job;
- ``filled``: the job did not say which board it is (no ``board_id``) and exactly one code was read, so that is the board;
- ``mismatch``: a code was read and none of them is the board of the job (or several different ones were read);
- ``no_code``: no code could be read.

How strict the cell is, is a setting (``HYDRA_UMC_OPENPNP_BOARD_CODE``): ``off`` (the default: the job is believed, as before),
``advisory`` (a code that was read must agree, one that could not be read changes nothing) and ``required`` (a board with no
readable code, or with another code, is refused). Anything read is checked with the same identifier rule as every board id, so
a code with spaces, a path or markup in it is not a board.

The code comes from ``CodeSource``: anything that returns the strings decoded from the camera over the fixture. The one that
exists is ``VisionNodeCodeSource``, which sends a frame to HYDRA-UMC-VISION-NODE's ``POST /read-code`` and gets the decoded
codes back; the frame comes from a ``frame_provider`` (HYDRA-UMC-VISION-STREAMER, or a file).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Sequence

from .board_flow import IDENTIFIER

MODE_OFF = "off"
MODE_ADVISORY = "advisory"
MODE_REQUIRED = "required"
MODES = (MODE_OFF, MODE_ADVISORY, MODE_REQUIRED)
MODE_ENVIRONMENT = "HYDRA_UMC_OPENPNP_BOARD_CODE"
MAX_CODES = 16
MAX_RESPONSE_BYTES = 64 * 1024

CodeSource = Callable[[], Sequence[str]]


def board_code_mode_from_environment(environment: dict[str, str] | None = None) -> str:
    """The configured mode; an unset or unknown value is ``off``, which is the behaviour without this check."""
    value = (environment if environment is not None else os.environ).get(MODE_ENVIRONMENT, "").strip().lower()
    return value if value in MODES else MODE_OFF


@dataclass(frozen=True)
class CodeCheck:
    """The result of comparing the code on the board with the job."""

    outcome: str  # match, filled, mismatch, no_code, skipped
    board_id: str | None
    allowed: bool
    reason: str


def clean_codes(raw: object) -> list[str]:
    """The readable board identifiers among what a decoder returned: strings that are stable identifiers, once each, in order."""

    if not isinstance(raw, (list, tuple)):
        return []
    codes: list[str] = []
    for item in raw[:MAX_CODES]:
        if isinstance(item, str):
            text = item.strip()
            if IDENTIFIER.fullmatch(text) and text not in codes:
                codes.append(text)
    return codes


def check_board_code(declared: str | None, codes: Sequence[str], mode: str) -> CodeCheck:
    """Compare the board the job names with the codes read from the board.

    ``declared`` is ``parameters.board_id`` (None when the job has none). In mode ``off`` nothing is checked and ``declared``
    stands.
    """

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == MODE_OFF:
        return CodeCheck("skipped", declared, True, "the code on the board is not checked")
    readable = clean_codes(list(codes))
    if not readable:
        if mode == MODE_REQUIRED:
            return CodeCheck("no_code", declared, False, "no readable code was found on the board, and this cell requires one")
        return CodeCheck("no_code", declared, declared is not None, "no readable code was found on the board" if declared is not None else "the job names no board and no code was read")
    if declared is None:
        if len(readable) == 1:
            return CodeCheck("filled", readable[0], True, "the job names no board: the code on the board is used")
        return CodeCheck("mismatch", None, False, "the job names no board and several different codes were read")
    if declared in readable:
        if len(readable) > 1:
            return CodeCheck("mismatch", declared, False, "several different codes were read on the board, one of them the job's: it cannot be told which board this is")
        return CodeCheck("match", declared, True, "the code on the board is the board of the job")
    return CodeCheck("mismatch", declared, False, f"the code on the board ({readable[0]}) is not the board of the job ({declared})" if len(readable) == 1 else "none of the codes read on the board is the board of the job")


class VisionNodeCodeSource:
    """Gets the codes from HYDRA-UMC-VISION-NODE: sends one frame to ``POST /read-code`` and returns what it decoded.

    ``frame_provider() -> (raw_pixels, width, height, channels)`` gives the frame of the camera over the fixture (from
    HYDRA-UMC-VISION-STREAMER, or a file). ``post(url, body, headers) -> (status, response_bytes)`` is the transport; the
    default uses ``urllib`` with a timeout. A failure of any kind is "no code was read", never an exception: what the check does
    with that is the mode's business.
    """

    def __init__(
        self,
        base_url: str,
        frame_provider: Callable[[], tuple[bytes, int, int, int]],
        token: str | None = None,
        *,
        timeout_s: float = 5.0,
        post: Callable[[str, bytes, dict[str, str]], tuple[int, bytes]] | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http or https URL")
        self._base_url = base_url.rstrip("/")
        self._frame_provider = frame_provider
        self._token = token
        self._timeout = timeout_s
        self._post = post if post is not None else self._urllib_post

    def _urllib_post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - the scheme was checked
                return int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            return int(error.code), b""

    def __call__(self) -> list[str]:
        try:
            pixels, width, height, channels = self._frame_provider()
            url = f"{self._base_url}/read-code?width={int(width)}&height={int(height)}&channels={int(channels)}"
            headers = {"Content-Type": "application/octet-stream"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            status, body = self._post(url, pixels, headers)
            if status != 200 or len(body) > MAX_RESPONSE_BYTES:
                return []
            payload = json.loads(body)
        except Exception:  # noqa: BLE001 - a camera or a service that fails is a board whose code was not read
            return []
        return clean_codes(payload.get("codes") if isinstance(payload, dict) else None)
