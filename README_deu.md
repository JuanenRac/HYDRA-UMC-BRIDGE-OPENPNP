<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP-Platinenflussbrücke
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | [🇪🇸 Español](README_spa.md) | [🇫🇷 Français](README_fra.md) | [🇮🇹 Italiano](README_ita.md) | 🇩🇪 **Deutsch** | [🇨🇳 简体中文](README_zho.md) | [🇯🇵 日本語](README_jpn.md)

Hochrangige Platinenflussbrücke zwischen HYDRA-UMC und OpenPnP. Sie koordiniert
PCB-Vorbereitung, Roboterladen, natives Platzieren, Entladen und nachverfolgbaren
Abschluss. Sie implementiert weder Platzierkinematik, Feeder noch Rohbewegung.

## Architektur

```text
OpenPnP-Job <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> Zellensicherheit
```

Jede Übergabe braucht stabile `board_id`, Jobkennung und Idempotenzschlüssel.
Produktive Übergaben werden nur bei Maschine `IDLE` und Zelle `READY` geplant;
`ABORT` kann einen kontrollierten Stopp anfordern.

## Bauen und testen

`build-test.bat` unter Windows oder `bash build-test.sh` unter Linux ausführen.
Version und CHANGELOG bleiben unverändert. OpenPnP-API oder Erweiterung folgt
erst nach Test der realen Version und des Maschinenprofils.

## Verwandte Projekte

| Projekt | Rolle |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | Gemeinsame Jobs und Sicherheitsgate. |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | Autorisierte Orchestrierungsgrenze. |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | Künftiger Nachweis von Zellenzonen. |

## Status

Version `0.0.1` hat einen getesteten lokalen PCB-Übergabekern. Eine Verbindung
zu einer OpenPnP-Maschine wird erst nach einem realen Integrationstest behauptet.

## ⚙️ Versionierter Build

`build-test.bat` / `build-test.sh` validieren ohne das Repository zu ändern.
`build.bat` / `build.sh` führen zuerst diese Validierung aus und
synchronisieren nur bei Erfolg native Version, Manifest und `CHANGELOG.md`.
Vor einer validierten OpenPnP-Integration gibt es keinen Maschinen-`run`-Befehl.
