<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP PCB フローブリッジ
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | [🇪🇸 Español](README_spa.md) | [🇫🇷 Français](README_fra.md) | [🇮🇹 Italiano](README_ita.md) | [🇩🇪 Deutsch](README_deu.md) | [🇨🇳 简体中文](README_zho.md) | 🇯🇵 **日本語**

HYDRA-UMC と OpenPnP 間の高レベル PCB フローブリッジです。PCB 準備、
ロボット搬入、ネイティブ実装、搬出、追跡可能な完了を協調します。実装運動学、
フィーダー、直接動作は実装しません。

## アーキテクチャ

```text
OpenPnP ジョブ <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> セル安全
```

各受け渡しには安定した `board_id`、ジョブ識別子、冪等キーが必要です。生産的
受け渡しは機械 `IDLE` とセル `READY` の場合のみ計画され、`ABORT` は制御停止を要求できます。

## ビルドとテスト

Windows では `build-test.bat`、Linux では `bash build-test.sh` を実行します。
バージョンと CHANGELOG は変更しません。OpenPnP API または拡張は、実際の
バージョンと機械プロファイルの試験後に選定されます。

## 関連プロジェクト

| プロジェクト | 役割 |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | 共有ジョブと安全ゲート。 |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | 認可済みオーケストレーション境界。 |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | 将来のセルゾーン証拠。 |

## 状態

バージョン `0.0.1` はテスト済みのローカル PCB 受け渡しコアです。実際の統合
試験前に OpenPnP 機への接続を主張しません。

## ⚙️ バージョン付きビルド

`build-test.bat` / `build-test.sh` はリポジトリを変更せず検証します。
`build.bat` / `build.sh` は最初にその検証を実行し、成功した場合のみネイティブ
パッケージ版、マニフェスト、`CHANGELOG.md` を同期します。OpenPnP 統合の検証前に
マシン `run` コマンドはありません。
