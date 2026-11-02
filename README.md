# AutoPlay

> **1.1.0（2026-11-02）：** 声音默认全部走特斯拉蓝牙（新 uci `audio_route_navigation`，`carplay` 为备选），网页不再播放音乐；引入 DashPlay 10.26–11.01 的 F50 蓝牙、空闲宽限、AppCDS 和证书申请可靠性修复。四个 Kotlin 文件未经编译（`receiver/docs/UNVERIFIED-KOTLIN.md`）。说明见 [`docs/AUDIO.md`](docs/AUDIO.md)、[`CHANGELOG.md`](CHANGELOG.md)。

> **1.0.1（2026-11-02）：** 1.0.0 的收尾：补齐 DNSPod 的测试与中文翻译、修正两个过期断言、安装脚本保留车主选的 149–165 信道、文档记录实车事实；新增 [`docs/AUDIO.md`](docs/AUDIO.md) 说明哪些声音走蓝牙、哪些走网页。功能与 1.0.0 相同。

> **1.0.0（2026-11-02）：** 首个在特斯拉车内实测通过的版本。新增腾讯云（DNSPod）自有域名证书支持（与 DuckDNS 并存），无线固定为中国区 CN / 信道 149（特斯拉搜不到热点的根因是厂商镜像国家码 TR 不含 149–165）。接收端、网页包、OpenWrt 包版本统一为 1.0.0。下文 0.1.x 说明是历史记录。

[English](README.en.md)

> **0.1.1 更新（2026-10-31）：** 本版已完成 JDK 21 接收端编译与回归、前端类型检查/构建、盒子侧本机回归，并修复媒体恢复、配对持久化、状态与安装边界问题。完整结果与限制见 [0.1.1 审计报告](docs/AUDIT-0.1.1.md)。当前是本机验证过的工程测试版，尚未安装到 F50 或特斯拉。用户的 **F50 B13 不受现有 B16 刷机路径支持**；不得绕过内核校验。下文部分 0.1.0 说明是历史记录。

AutoPlay 是 [PlayPort](https://github.com/youcci/playport) + [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) / [openwrt-dashplay](https://github.com/yizhixiaoheigou/openwrt-dashplay) 的 GPL-3.0 硬分叉，只做**一个**目标：

> 一台刷了 OpenWrt（[mu300-linux](https://github.com/dikeckaan/mu300-linux) 的 `mu300-linux` 镜像，厂商 5.4 内核，紫光展锐 T760）的**中兴 F50** 随身 WiFi，接车上 USB 供电，接收 iPhone 的无线 CarPlay，把画面显示在**特斯拉**车机自带的浏览器里。

**状态：0.1.1 工程测试版，未上车验证。** 已完成接收端编译与本机回归、前端构建和盒子软件测试；基线、具体计数、缺陷清单和剩余风险见 [`docs/AUDIT-0.1.1.md`](docs/AUDIT-0.1.1.md)。本轮以原 0.1.0（提交 `7d8bcca`）为基线，保留 F50 + 特斯拉架构，修复媒体恢复、配对落盘、设置请求、状态并发、安装门禁与回滚签名等问题。F50 B13、AMD Model 3P、iPhone 15 Pro / iOS 27.2 尚未跑过端到端测试，本版不能作为已验证的刷机镜像或成品使用。

**这不是 Apple 认证产品。** 运行需要用户自己提供配件认证身份；仓库、包、文档、测试里都不含身份材料，也不会自动下载。公开流传的共享身份随时可能被撤销（见 `NOTICE.md`、`docs/SECURITY.md`）。

## 它怎么工作（一句话版）

F50 开 5 GHz 热点（100.96.0.1/24），用蓝牙 iAP2 引导 iPhone 连上来，JVM 接收端把 iPhone 发来的 H.264 原样经 WSS 转给车机浏览器，浏览器用 WebCodecs 解码画到 canvas 上；触摸原路回传。音乐、通话、Siri 走特斯拉自己的蓝牙，页面只管画面和导航播报。细节见 `docs/ARCHITECTURE.md`，依据见 `docs/DECISIONS.md`。

## 目录

| 目录 | 内容 | 来源 |
|---|---|---|
| `receiver/` | Kotlin/JVM 接收端（iAP2、AirPlay、MFi 签名接口、WSS 服务）和 TypeScript 投屏页 `receiver/web/`。已按特斯拉裁剪：去掉有线、macOS、麦克风上行、正在播放/封面/媒体会话、小鹏全屏家族；默认性能模式关、1920 上限、300mm 界面；状态驱动的提示、恢复中遮罩、整宽声音解锁条、rem 字号、iOS 27 深浅色、导航播报压低音乐、触摸最短按压。`web/src/flags.ts` 放常量 | PlayPort 硬分叉，DashPlay 的 63 个补丁按顺序落成 git 历史，再加 22 个裁剪与修复提交 |
| `box/` | 盒子侧 Python：procd 守护（`supervision.py` 分组件重启、蓝牙 10/20/40/60 秒重试、接收端存活探测）、F50 蓝牙拉起（私有 BlueZ）、状态模型 `/var/run/autoplay/status.json`（9 个域，每项 `{state, reason, since}`）、设置页（S1/S2 已修：F50 上没有"数据线"文案，蓝牙故障显示红条和原因）、特斯拉常量（LAN 100.96.0.1/24、联网检测常驻应答、7 个 uci 键）、DuckDNS 证书退避与状态、升级日志与回滚、时钟下限、出厂重置、安装脚本、测试 | DashPlay，删掉 Debian/N1/玩客云/STA/外接路由/IPv6/本地 CA/有线之后 |
| `openwrt/` | OpenWrt 25.12 的 apk 包：`autoplay`（`/opt/autoplay`、`/etc/init.d/autoplay`、`/etc/config/autoplay`，postinst 从 `/opt/dashplay` 迁移，`CONFLICTS dashplay`）、`autoplay-jre`（jlink 裁剪的 Temurin 21）、`luci-app-autoplay`（概览 + 4 个标签） | openwrt-dashplay，改名并精简 |
| `tools/` | 本仓库新增：`probe/`（车机浏览器探测页）、`f50/`（加固脚本、测量服务、报告工具）、`car/`（触摸延迟测法） | AutoPlay |
| `docs/` | 架构、构建、测试、路线图、特斯拉专项、安全、决策记录 | AutoPlay |

## 快速入口

- 先摸清车机浏览器：[`tools/probe/`](tools/probe/README.md)（一个 HTML 文件，在车机里打开）。
- 第 1 周的配置加固：[`tools/f50/harden.sh`](tools/f50/README.md)（`--dry-run` 先看）。
- 测量体系：[`tools/f50/measure.sh`](tools/f50/README.md) + `measure-report.py`；触摸延迟：[`tools/car/touch-latency.md`](tools/car/touch-latency.md)。
- 怎么编译：[`docs/BUILD.md`](docs/BUILD.md)；怎么测：[`docs/TEST.md`](docs/TEST.md)。
- 这次裁剪了什么、哪些没编译：[`receiver/docs/TRIM-LOG.md`](receiver/docs/TRIM-LOG.md)、[`receiver/docs/UNVERIFIED-KOTLIN.md`](receiver/docs/UNVERIFIED-KOTLIN.md)、[`box/docs/TRIM-LOG.md`](box/docs/TRIM-LOG.md)；盒子状态的含义：[`box/docs/STATUS-MODEL.md`](box/docs/STATUS-MODEL.md)。
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
