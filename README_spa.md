<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Puente de flujo de placas OpenPnP
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | 🇪🇸 **Español** | [🇫🇷 Français](README_fra.md) | [🇮🇹 Italiano](README_ita.md) | [🇩🇪 Deutsch](README_deu.md) | [🇨🇳 简体中文](README_zho.md) | [🇯🇵 日本語](README_jpn.md)

Puente de flujo de placas de alto nivel entre HYDRA-UMC y OpenPnP. Coordina
preparación de PCB, carga robotizada, colocación nativa, descarga robotizada y
finalización trazable. No implementa cinemática de colocación, feeders ni movimiento bruto.

## Arquitectura

```text
Trabajo OpenPnP <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> seguridad de celda
```

Cada entrega necesita un `board_id` estable, identificador de trabajo y clave de
idempotencia. Solo planifica transferencias productivas si la máquina externa
está `IDLE` y la celda HYDRA-UMC está `READY`; `ABORT` puede pedir parada controlada.

## Compilar y probar

Ejecuta `build-test.bat` en Windows o `bash build-test.sh` en Linux. No cambia
versión ni CHANGELOG y prueba trazabilidad y comportamiento fail-safe. La API o
extensión concreta de OpenPnP se elegirá tras probar versión y perfil reales.

## Proyectos relacionados

| Proyecto | Función |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | Trabajos y puerta de seguridad compartidos. |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | Límite de orquestación autorizado. |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | Evidencia futura de zonas de celda. |

## Estado

La versión `0.0.1` tiene un núcleo local probado de entrega de PCB. No afirma
una conexión a máquina OpenPnP hasta probar esa integración.

## ⚙️ Compilación con versión

`build-test.bat` / `build-test.sh` validan sin modificar el repositorio.
`build.bat` / `build.sh` ejecutan primero esa validación y, solo si es
correcta, sincronizan la versión nativa, el manifiesto y `CHANGELOG.md`. No
existe un comando `run` de máquina hasta validar la integración con OpenPnP.
