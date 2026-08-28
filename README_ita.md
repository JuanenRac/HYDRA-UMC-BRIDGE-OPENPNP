<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Bridge di flusso schede OpenPnP
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | [🇪🇸 Español](README_spa.md) | [🇫🇷 Français](README_fra.md) | 🇮🇹 **Italiano** | [🇩🇪 Deutsch](README_deu.md) | [🇨🇳 简体中文](README_zho.md) | [🇯🇵 日本語](README_jpn.md)

Bridge di flusso schede ad alto livello tra HYDRA-UMC e OpenPnP. Coordina
preparazione PCB, carico robotizzato, piazzamento nativo, scarico e chiusura
tracciabile. Non implementa cinematica di piazzamento, feeder o movimento diretto.

## Architettura

```text
Lavoro OpenPnP <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> sicurezza cella
```

Ogni passaggio richiede `board_id` stabile, identificatore lavoro e chiave di
idempotenza. Il bridge pianifica trasferimenti produttivi solo con macchina
`IDLE` e cella `READY`; `ABORT` può chiedere una fermata controllata.

## Compilare e testare

Eseguire `build-test.bat` su Windows o `bash build-test.sh` su Linux. Non cambia
versione né CHANGELOG e prova tracciabilità e fail-safe. API o estensione OpenPnP
saranno scelte dopo prova di versione e profilo reali.

## Progetti correlati

| Progetto | Ruolo |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | Lavori e porta di sicurezza condivisi. |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | Confine di orchestrazione autorizzato. |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | Evidenza futura delle zone di cella. |

## Stato

La versione `0.0.1` ha un nucleo locale testato di passaggio PCB. Non dichiara
connessione a una macchina OpenPnP prima della prova dell'integrazione.
