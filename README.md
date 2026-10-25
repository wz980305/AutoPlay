# AutoPlay

[English](README.en.md)

AutoPlay 是 [PlayPort](https://github.com/youcci/playport) + [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) / [openwrt-dashplay](https://github.com/yizhixiaoheigou/openwrt-dashplay) 的 GPL-3.0 硬分叉，只做**一个**目标：

> 一台刷了 OpenWrt（[mu300-linux](https://github.com/dikeckaan/mu300-linux) 的 `mu300-linux` 镜像，厂商 5.4 内核，紫光展锐 T760）的**中兴 F50** 随身 WiFi，接车上 USB 供电，接收 iPhone 的无线 CarPlay，把画面显示在**特斯拉**车机自带的浏览器里。

**状态：工程骨架，未上车验证。** 仓库里的接收端、盒子侧和 OpenWrt 包来自上游 2026-10-25 的快照（DashPlay `e3beae4`、openwrt-dashplay `5f17702`、PlayPort `9a0882d` + 63 个补丁），加上本仓库的工具和文档。本里程碑没有在任何一辆车上跑过；Kotlin 侧的改动也没有在编写环境里编译过（见 `receiver/docs/UNVERIFIED-KOTLIN.md`）。把它当成一份带代码的设计文档，而不是能直接装的产品。

**这不是 Apple 认证产品。** 运行需要用户自己提供配件认证身份；仓库、包、文档、测试里都不含身份材料，也不会自动下载。公开流传的共享身份随时可能被撤销（见 `NOTICE.md`、`docs/SECURITY.md`）。

## 它怎么工作（一句话版）

F50 开 5 GHz 热点（100.96.0.1/24），用蓝牙 iAP2 引导 iPhone 连上来，JVM 接收端把 iPhone 发来的 H.264 原样经 WSS 转给车机浏览器，浏览器用 WebCodecs 解码画到 canvas 上；触摸原路回传。音乐、通话、Siri 走特斯拉自己的蓝牙，页面只管画面和导航播报。细节见 `docs/ARCHITECTURE.md`，依据见 `docs/DECISIONS.md`。

## 目录

| 目录 | 内容 | 来源 |
|---|---|---|
| `receiver/` | Kotlin/JVM 接收端（iAP2、AirPlay、MFi 签名接口、WSS 服务）和 TypeScript 投屏页 `receiver/web/` | PlayPort 硬分叉，DashPlay 的补丁已按顺序落成 git 历史 |
| `box/` | 盒子侧 Python：procd 守护、F50 蓝牙拉起（私有 BlueZ）、设置页、特斯拉模式、DuckDNS 证书、升级、安装脚本、测试 | DashPlay |
| `openwrt/` | OpenWrt 25.12 的 apk 包：程序、jlink 裁剪的 Temurin 21 JRE、LuCI 插件 | openwrt-dashplay |
| `tools/` | 本仓库新增：`probe/`（车机浏览器探测页）、`f50/`（加固脚本、测量服务、报告工具）、`car/`（触摸延迟测法） | AutoPlay |
| `docs/` | 架构、构建、测试、路线图、特斯拉专项、安全、决策记录 | AutoPlay |

## 快速入口

- 先摸清车机浏览器：[`tools/probe/`](tools/probe/README.md)（一个 HTML 文件，在车机里打开）。
- 第 1 周的配置加固：[`tools/f50/harden.sh`](tools/f50/README.md)（`--dry-run` 先看）。
- 测量体系：[`tools/f50/measure.sh`](tools/f50/README.md) + `measure-report.py`；触摸延迟：[`tools/car/touch-latency.md`](tools/car/touch-latency.md)。
- 怎么编译：[`docs/BUILD.md`](docs/BUILD.md)；怎么测：[`docs/TEST.md`](docs/TEST.md)。
- 特斯拉要注意什么：[`docs/TESLA.md`](docs/TESLA.md)。
- 接下来做什么、什么已经做了：[`docs/ROADMAP.md`](docs/ROADMAP.md)、[`CHANGELOG.md`](CHANGELOG.md)。
- 为什么这样决定：[`docs/DECISIONS.md`](docs/DECISIONS.md)。
- 安全边界：[`docs/SECURITY.md`](docs/SECURITY.md)。

## 硬件前提

- 中兴 F50（型号 MU300），原厂固件 **B16**（DashPlay 的安装流程只认这一版），64GB 或 32GB 均可。
- 刷机、root、回安卓：只看 mu300-linux 自己的文档（wiki：Installation、Going-Back-to-Android、Updating），本仓库不重复、不另写。
- 车上：5V ≥3A、打火时不断电的 USB 供电，短而粗的线；散热片加小风扇，装在晒不到的地方；高耐久或工业级 microSD。这些不是建议，是前提——热和供电是 F50 在车里的两个最大风险（《硬件视角审查》H1、H2）。
- 特斯拉：给盒子的 Wi-Fi 打开"行驶中保持连接"；iPhone 同时连特斯拉蓝牙并选为媒体来源；SIM 卡（证书续期和车机联网检测都需要）。

## 许可证

GPL-3.0，见 `LICENSE`。衍生自 PlayPort、DashPlay、openwrt-dashplay，它们又衍生自 DiPlay、xcertplay、WheelPlay，完整署名链见 `NOTICE.md`。CarPlay、iPhone、AirPlay、MFi 是 Apple Inc. 的商标；本项目与 Apple 及上述项目的作者无隶属或背书关系。
