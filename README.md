<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP board-flow bridge
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

🇺🇸 **English** | [🇪🇸 Español](README_spa.md) | [🇫🇷 Français](README_fra.md) | [🇮🇹 Italiano](README_ita.md) | [🇩🇪 Deutsch](README_deu.md) | [🇨🇳 简体中文](README_zho.md) | [🇯🇵 日本語](README_jpn.md)

High-level board-flow bridge between HYDRA-UMC and OpenPnP. It coordinates
PCB preparation, robot loading, native placement, robot unloading and
traceable completion. It does not implement placement kinematics, feeder
control or raw motion.

## Architecture

```text
OpenPnP job <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> cell safety
```

Every hand-off needs a stable `board_id`, a correlated job identifier and an
idempotency key. The bridge only plans a productive transfer when the external
machine reports `IDLE` and the HYDRA-UMC cell is `READY`; `ABORT` can still ask
the authorised safety path for a controlled stop.

## Build & Test

Run `build-test.bat` on Windows or `bash build-test.sh` on Linux. The command
performs no version increment and runs board-traceability and fail-safe tests.
The concrete OpenPnP extension/API will be chosen only after testing the
installed OpenPnP version and machine profile.

## Related Projects

| Project | Role |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | Shared jobs and safety gate. |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | Authorised orchestration boundary. |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | Future cell-zone evidence. |

## Status

Version `0.0.1` has a tested local PCB hand-off core. It does not claim a
connection to an OpenPnP machine until that integration is tested.

## ⚙️ Versioned Build

`build-test.bat` / `build-test.sh` validate without modifying the repository.
`build.bat` / `build.sh` run that validation first and, only on success,
synchronize the native package version, manifest and `CHANGELOG.md`. There is
no live machine `run` command until an OpenPnP integration is validated.
