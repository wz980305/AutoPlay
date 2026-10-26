# AutoPlay — 声明与署名

AutoPlay 以 GNU General Public License v3.0 分发（见 `LICENSE`）。它是下列项目的衍生作品，必须保持同一许可证。

## 代码来源（署名链）

- **PlayPort** — <https://github.com/youcci/playport>（GPL-3.0），youcci。`receiver/` 是它在提交 `9a0882dd0ffe48e467b59d58b12d81391df55ade` 上的硬分叉：Kotlin/JVM 接收端（iAP2、AirPlay、MFi 签名接口、WSS）和 TypeScript 投屏页。
- **DashPlay** — <https://github.com/yizhixiaoheigou/DashPlay>（GPL-3.0），yizhixiaoheigou。`box/` 来自其 v2026.10.25（`e3beae4`）；它对 PlayPort 的 63 个补丁已按原顺序逐个提交进 `receiver/` 的 git 历史（含两个有线 CarPlay 补丁，F50 用不到，后续精简时删除），补丁头里的说明保留在各提交信息中。F50 的蓝牙初始化、特斯拉模式、浏览器兼容修复、解码积压保护、重连提速等都来自这里。
- **openwrt-dashplay** — <https://github.com/yizhixiaoheigou/openwrt-dashplay>（GPL-3.0），同一作者。`openwrt/` 来自其 `5f17702`：apk 包定义、jlink 裁剪的 JRE 包、LuCI 插件。
- **DiPlay** — <https://github.com/shihabal3amri/DiPlay>（GPL-3.0），shihabal3amri。PlayPort 的 AirPlay、iAP2 和配件认证代码移植自它；视图区域的做法沿用其 PR #246 和 `docs/VIEW_AREAS.md`。
- **xcertplay** — <https://github.com/shilapi/xcertplay>（GPL-3.0），shilapi。DiPlay 的上游协议栈；其 MSE 兼容档和悬浮控件的隐藏策略是本项目相关决定的参考。
- **WheelPlay** — <https://github.com/fython/wheelplay>（GPL-3.0），fython。PlayPort/DashPlay 从其提交 `c1bd07717c8e87a3130ef03477d2ca318fb66caa` 移植了 iAP2 文件传输（专辑封面）接收器；本项目的画面状态机（等待 / 显示 / 恢复中，帧和触控带会话号）、WebRTC + 直接 Canvas 的 C′ 档评估、分段延迟测法参考其 `docs/ARCHITECTURE.md`、`MEDIA_PRESENTATION.md`、`WEBRTC_RECOVERY.md`、`VALIDATION.md`。
- **mu300-linux** — <https://github.com/dikeckaan/mu300-linux>，dikeckaan。F50 的 Linux 移植：OpenWrt 镜像、厂商 5.4 内核、`mu300-*` 工具。本项目不包含它的代码；`tools/f50/harden.sh` 调用其 `mu300-next-boot`、`mu300-usb`、`mu300-led`，并修改其 `extra-modules` 脚本（保留备份）。刷机和回安卓只以它的文档为准。
- **acme.sh** — <https://github.com/acmesh-official/acme.sh>（GPL-3.0），3.1.6，未修改的主脚本和 DuckDNS 钩子，随 `box/` 的程序包分发，仅在用户配置自己的 DuckDNS 名称时使用。
- **dbus-next** — <https://github.com/altdesktop/python-dbus-next>（MIT），0.2.3，未修改，蓝牙桥使用；许可证文本在 `box/licenses/`。
- **Eclipse Temurin 21 JRE**（Alpine/musl 构建，Eclipse Adoptium，GPL-2.0 with Classpath Exception）由 `openwrt/dashplay-jre` 打包，去掉 `libjsound.so` 并以 jlink 裁剪。

## 设计参考（未复制代码）

- **LIVI** — <https://github.com/f-io/LIVI>（GPL-3.0-or-later），f-io。Rust 的 CarPlay 协议栈，是 `docs/DECISIONS.md` 里"JVM 先行、Rust 在后"路线第三阶段的候选来源；导航播报压低音乐（duck/unduck）的处理方式参考了它。目前没有引入其代码。
- **dashplay-tesla 优化版** — 一个匿名的、非官方的 DashPlay 分支（基于 DashPlay v2026.10.20，面向斐讯 N1 + 特斯拉，GPL-3.0，NOTICE 保留了上述署名链）。本项目**没有采用它的代码**（见《dashplay-tesla 优化版分析》第四、五节的原因），但参考了它实车得出的：双手机连接规则和常数、iOS 27 的深浅色命令、蓝牙桥的失败原因码、走开再回来的自动接回、"只用带边框窗口"的选项、服务器端续期证书的思路，以及它删掉"轻点开启声音"提示的做法为什么不该学。作者未署名，无法在此具名；如作者愿意，请联系以补署名。

## 身份材料

本仓库、生成的软件包、文档和测试都**不包含**任何配件认证身份、配件证书或私钥；测试在运行时生成合成身份。接收端在没有用户自行放置的身份文件时拒绝启动，不会自动下载。公开流传的共享身份是全网共用的，Apple 一次撤销就会让所有安装同时失效；分发它在法律上有风险。本项目不是 Apple 认证产品，仅供个人实验；不要出售或再分发认证身份。签名接口做成可替换（本地文件、远程签名服务、硬件芯片），正是为了身份被撤销时能换实现。

## 商标

CarPlay、iPhone、AirPlay、MFi 是 Apple Inc. 的商标。Tesla 是 Tesla, Inc. 的商标。中兴、F50 是中兴通讯的商标。本项目是独立项目，与 Apple、Tesla、中兴、PlayPort、DashPlay、DiPlay、xcertplay、WheelPlay、LIVI、mu300-linux 的作者均无隶属或背书关系。产品名和图标不使用 CarPlay 商标。
