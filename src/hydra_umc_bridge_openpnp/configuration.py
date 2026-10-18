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
from xml.parsers import expat


_MAX_CONFIGURATION_BYTES = 4 * 1024 * 1024


class _DoctypeRefused(Exception):
    """Raised from inside the parser the moment a DOCTYPE declaration starts."""


def _refuse_doctype(*_: object) -> None:
    raise _DoctypeRefused()


def _parse_without_doctype(raw: bytes) -> ElementTree.Element:
    """Parse `raw`, refusing any DOCTYPE. The parser itself says when one starts, so a UTF-16 document (whose bytes
    do not contain the ASCII text `<!DOCTYPE`) is refused as well.

    Plain expat feeding an ElementTree `TreeBuilder`: the C-accelerated `XMLParser` does not expose the expat
    handlers, and a machine.xml has no use for namespaces, entities or external subsets."""
    builder = ElementTree.TreeBuilder()
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = _refuse_doctype
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as error:
        raise ElementTree.ParseError(str(error)) from error
    return builder.close()


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
    # Real OpenPnP concepts, researched against org.openpnp.spi.Machine's
    # own real getActuators()/getSignalers()/getNozzleTips() methods and a
    # real published machine.xml (github.com/openpnp/openpnp/blob/develop/
    # src/test/resources/config/SampleJobTest/machine.xml): actuators
    # control real hardware (vacuum valves, nozzle-tip-changer clamps,
    # feeder actuation) and signalers bind an actuator to a real job/
    # machine state (job-state STOPPED/RUNNING/ERROR/FINISHED, or
    # machine-state ERROR) - both are safety/capability-relevant evidence
    # this profile never surfaced before.
    actuator_count: int = 0
    nozzle_tip_count: int = 0
    signaler_count: int = 0


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
        root = _parse_without_doctype(raw)
    except _DoctypeRefused:
        return OpenPnpMachineProfile(False, "OpenPnP configuration declares a prohibited DOCTYPE")
    except (ElementTree.ParseError, OSError, TypeError, ValueError) as error:
        return OpenPnpMachineProfile(False, f"OpenPnP configuration unavailable: {error}")

    machine = root.find("machine") if root.tag == "openpnp-machine" else None
    if machine is None:
        return OpenPnpMachineProfile(False, "OpenPnP configuration has no machine element")

    signalers = machine.find("signalers")
    # signalers are a real, polymorphic OpenPnP concept (ActuatorSignaler,
    # SoundSignaler, ...): each subtype serializes under its own XML tag
    # name, so counting direct children here (rather than a fixed tag)
    # is the only way to count "how many signalers are configured"
    # without hardcoding one subtype's name.
    signaler_count = len(list(signalers)) if signalers is not None else 0

    return OpenPnpMachineProfile(
        True,
        "OpenPnP configuration parsed read-only",
        machine.get("class", ""),
        len(machine.findall(".//head")),
        len(machine.findall(".//camera")),
        len(machine.findall(".//driver")),
        len(machine.findall(".//feeder")),
        len(machine.findall(".//actuator")),
        len(machine.findall(".//nozzle-tip")),
        signaler_count,
    )
