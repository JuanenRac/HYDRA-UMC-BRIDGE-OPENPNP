<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Contribution guide
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Contributing

Keep this bridge a coordinated board-flow layer: OpenPnP remains responsible
for its placement workflow and machine motion, while HYDRA-UMC auxiliaries must
pass the shared SDK gate.

Before opening a change, run `build-test.bat` on Windows or `bash build-test.sh`
on Linux. Add a focused test for every board identity, hand-off or admission
rule changed. Hardware behavior must name its validated interface and safe
failure mode; untested machine support is not ready support.
