# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Read-only OpenPnP configuration inspection
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Inspect an OpenPnP machine XML file without opening or changing a machine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


_MAX_CONFIGURATION_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class OpenPnpMachineProfile:
    """A non-sensitive, read-only summary of an OpenPnP machine profile."""

    available: bool
    reason: str
    machine_class: str = ""
    head_count: int = 0
    camera_count: int = 0
    driver_count: int = 0
    feeder_count: int = 0


def inspect_machine_configuration(config_path: str | Path) -> OpenPnpMachineProfile:
    """Parse a saved OpenPnP machine configuration without issuing any command.

    The function intentionally returns an unavailable profile for malformed,
    inaccessible or unexpected XML.  A caller must not infer a usable machine
    from a partial configuration parse.
    """

    try:
        path = Path(config_path)
        if path.stat().st_size > _MAX_CONFIGURATION_BYTES:
            return OpenPnpMachineProfile(False, "OpenPnP configuration exceeds the 4 MiB inspection limit")
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw.upper():
            return OpenPnpMachineProfile(False, "OpenPnP configuration declares a prohibited DOCTYPE")
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, OSError, TypeError, ValueError) as error:
        return OpenPnpMachineProfile(False, f"OpenPnP configuration unavailable: {error}")

    machine = root.find("machine") if root.tag == "openpnp-machine" else None
    if machine is None:
        return OpenPnpMachineProfile(False, "OpenPnP configuration has no machine element")

    return OpenPnpMachineProfile(
        True,
        "OpenPnP configuration parsed read-only",
        machine.get("class", ""),
        len(machine.findall(".//head")),
        len(machine.findall(".//camera")),
        len(machine.findall(".//driver")),
        len(machine.findall(".//feeder")),
    )
