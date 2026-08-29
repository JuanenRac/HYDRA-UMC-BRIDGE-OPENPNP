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

var summary =
    "HYDRA_UMC_OPENPNP_PROFILE=PASS " +
    "machine_class=" + machineClass +
    " heads=" + headCount +
    " cameras=" + cameraCount +
    " drivers=" + driverCount +
    " feeders=" + feederCount;

// `print()` is kept for the OpenPnP console and this dialog makes the same
// read-only result visible to the operator without commanding the machine.
print(summary);
javax.swing.JOptionPane.showMessageDialog(
    null,
    summary,
    "HYDRA-UMC OpenPnP Profile (read-only)",
    javax.swing.JOptionPane.INFORMATION_MESSAGE
);
