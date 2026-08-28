<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP PCB 流程桥
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# HYDRA-UMC-BRIDGE-OPENPNP

[🇺🇸 English](README.md) | [🇪🇸 Español](README_spa.md) | [🇫🇷 Français](README_fra.md) | [🇮🇹 Italiano](README_ita.md) | [🇩🇪 Deutsch](README_deu.md) | 🇨🇳 **简体中文** | [🇯🇵 日本語](README_jpn.md)

HYDRA-UMC 与 OpenPnP 之间的高层 PCB 流程桥。它协调 PCB 准备、机器人装载、
原生贴装、机器人卸载和可追溯完成。它不实现贴装运动学、供料器或原始运动。

## 架构

```text
OpenPnP 任务 <-> BRIDGE-OPENPNP <-> HYDRA-UMC-SDK <-> SERVER <-> 单元安全
```

每次交接需要稳定 `board_id`、任务标识和幂等键。只有外部机器为 `IDLE` 且
HYDRA-UMC 单元为 `READY` 时才计划生产性交接；`ABORT` 可以请求受控停止。

## 构建和测试

在 Windows 运行 `build-test.bat`，Linux 运行 `bash build-test.sh`。它不改变
版本或 CHANGELOG，并测试追溯性与失效安全行为。OpenPnP API 或扩展将在真实
版本和机器配置验证后选择。

## 相关项目

| 项目 | 角色 |
| --- | --- |
| [HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK) | 共享任务与安全门控。 |
| [HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER) | 授权编排边界。 |
| [HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES) | 未来单元区域证据。 |

## 状态

版本 `0.0.1` 具有经过测试的本地 PCB 交接核心。在真实集成测试前不宣称连接
任何 OpenPnP 机器。
