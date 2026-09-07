// =============================================================================
// HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP live profile inspection (read-only)
// Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
// GPL-3.0-or-later - see LICENSE
// =============================================================================
// This OpenPnP menu script only reads the documented `machine` global. It does
// not call enable(), home(), moveTo(), actuate(), feeder actions, or write any
// OpenPnP configuration or HYDRA-UMC state.

var machineClass = machine.getClass().getName();
var headCount = machine.getHeads().size();
var cameraCount = machine.getCameras().size();
var driverCount = machine.getDrivers().size();
var feederCount = machine.getFeeders().size();
// getAllActuators()/getSignalers()/getNozzleTips() are real org.openpnp.spi.
// Machine methods - actuators control real hardware (vacuum valves,
// nozzle-tip-changer clamps, feeder actuation) and signalers bind an
// actuator to a real job/machine state, both safety/capability-relevant
// evidence this profile never surfaced before. getAllActuators() (not
// getActuators()) is used deliberately, matching the offline
// configuration.py parser's own ".//actuator" scan: it includes
// head-mounted actuators, not just machine-level ones.
var actuatorCount = machine.getAllActuators().size();
var signalerCount = machine.getSignalers().size();
var nozzleTipCount = machine.getNozzleTips().size();

var summary =
    "HYDRA_UMC_OPENPNP_PROFILE=PASS " +
    "machine_class=" + machineClass +
    " heads=" + headCount +
    " cameras=" + cameraCount +
    " drivers=" + driverCount +
    " feeders=" + feederCount +
    " actuators=" + actuatorCount +
    " signalers=" + signalerCount +
    " nozzle_tips=" + nozzleTipCount;

// `print()` is kept for the OpenPnP console and this dialog makes the same
// read-only result visible to the operator without commanding the machine.
print(summary);
javax.swing.JOptionPane.showMessageDialog(
    null,
    summary,
    "HYDRA-UMC OpenPnP Profile (read-only)",
    javax.swing.JOptionPane.INFORMATION_MESSAGE
);
