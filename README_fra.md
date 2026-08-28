<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Pont de flux de cartes OpenPnP
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | [🇪🇸 Español](README_spa.md) | 🇫🇷 **Français** | [🇮🇹 Italiano](README_ita.md) | [🇩🇪 Deutsch](README_deu.md) | [🇨🇳 简体中文](README_zho.md) | [🇯🇵 日本語](README_jpn.md)

Pont de flux de cartes de haut niveau entre HYDRA-UMC et OpenPnP. Il coordonne
préparation PCB, chargement robotisé, placement natif, déchargement et clôture
traçable. Il ne fournit ni cinématique de placement, ni feeders, ni mouvement brut.

## Architecture

```text
Travail OpenPnP <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> sécurité cellule
```

Chaque transfert exige un `board_id` stable, un identifiant de travail et une clé
d'idempotence. Le pont ne planifie un transfert productif que si la machine est
`IDLE` et la cellule `READY`; `ABORT` peut demander un arrêt contrôlé.

## Compiler et tester

Exécutez `build-test.bat` sous Windows ou `bash build-test.sh` sous Linux. Il ne
change ni version ni CHANGELOG et teste traçabilité et comportement fail-safe.
L'API ou extension OpenPnP concrète sera choisie après essai réel.

## Projets liés

| Projet | Rôle |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | Travaux et porte de sécurité partagés. |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | Limite d'orchestration autorisée. |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | Future preuve de zones de cellule. |

## État

La version `0.0.1` possède un noyau local de transfert PCB testé. Elle n'affirme
aucune connexion à une machine OpenPnP avant essai de cette intégration.
