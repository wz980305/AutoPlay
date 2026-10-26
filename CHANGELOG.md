# 变更记录

格式参考 Keep a Changelog；版本号从 0.1.0 起，1.0 之前不承诺兼容性。

## [0.1.0] — 2026-10-26 — 里程碑：工程骨架

**未上车验证。** 这个版本在上游快照上完成了接收端和盒子侧的特斯拉裁剪、第一批审计修复、工具和文档；没有在任何 F50 或车上运行过，Kotlin 改动没有编译过（`receiver/docs/UNVERIFIED-KOTLIN.md`）。

### 仓库

- 单一仓库：`receiver/`（PlayPort `9a0882d` 硬分叉，DashPlay 的 63 个补丁按顺序落成提交）、`box/`（DashPlay `e3beae4`）、`openwrt/`（openwrt-dashplay `5f17702`），三条分支（`receiver-trim`、`box-trim`、`tools-docs`）合并进 `main`。
- `LICENSE`（GPL-3.0）、`NOTICE.md`（署名链）、`.gitignore`（身份、构建产物、设备状态）。

### 接收端（`receiver/`，22 个提交，`receiver/docs/TRIM-LOG.md`）

- 删除：有线（USB）CarPlay 的全部传输类和 `--usb-bridge`、kxml2；macOS 构建（bt-bridge、`WifiInfo`、dns-sd）；死代码（远程 MFi 客户端、仪表显示、播放状态）；麦克风上行整条链（`mic.ts`、`MicUplink.kt`、`MicrophonePacketizer.kt`，`/info` 不再提供输入格式）；正在播放/封面/媒体会话（**保留** iAP2 封面排空，避免 256 个未消费传输切断隧道）；小鹏 DOM 全屏家族、倒车恢复、画面上的毛玻璃按钮；作者二维码块（`index.html` 从 41 KB 降到 9.4 KB）；自定义分辨率开关和宽高输入；备用的上一曲/播放/下一曲按钮。
- 常量：`web/src/flags.ts`（`CAR_MUSIC`、`TESLA`、`MUSIC_ELEMENT`、`PROMPT_BOOST = 3`）；`carVoice` 变成常量。
- 修复（各一个提交）：配对文件原子写（临时文件 + fsync + rename，保留 `.bak`，加载时不回写）；投屏连接打 DSCP AF41（Netty `childOption(IP_TOS, 0x88)`）；特斯拉默认值（性能模式关、自动分辨率上限 1920 除非显式允许 2560、界面 300mm）；恢复中状态（保留画面 + 40% 遮罩 + 常驻提示，V1）；提示语按状态生成（`src/status.ts`，加 `renegotiating`，V3）；整宽底部声音解锁条，只在 AudioContext 挂起且确实收到页面要播的流时显示（V7）；画布 `alpha:false` 并记录 `desynchronized` 是否生效；`html{font-size:clamp(18px,1.9vmin,26px)}` 的 rem 字号体系、≥3.5rem 触控目标、吐司移到底部（V4）；iOS 27 深浅色（`enablesUIAppearance`/`enablesMapAppearance` + `uiAppearanceUpdate`/`mapAppearanceUpdate`，去掉四个 DiPlay 的 `*AppearanceMode=0` 键）；`duckAudio`/`unduckAudio` 转发给页面按时长渐变音量；触摸最短按压 30ms、页面隐藏或盒子暂停时补发全部抬起；驾驶者可读的双语浏览器检测页；所有可见字符串走 `t()`；品牌字符串 DashPlay → AutoPlay。
- 冻结不删：MSE 音乐路径（`MUSIC_ELEMENT` 开关后）、视图区域代码。
- 规模：Kotlin 主代码 16,908 → 12,941 行；网页 3,040 → 2,732 行。
- 离线构建：`web/scripts/build-esbuild.mjs`、`tsconfig.offline.json`、`web/README-build.md`。

### 盒子侧（`box/`，`box/docs/TRIM-LOG.md`）

- 先拆隐藏耦合（`state.py`、`tesla_checks.py`、独立的 `platform_openwrt.py`），再删除：Debian/Armbian 守护与平台、N1/玩客云固件工具、STA/手机热点上网、外接路由、公网 IPv6、本地 CA、有线 CarPlay、实验室探针，以及它们的测试。
- 特斯拉常量：LAN 100.96.0.1/24 由 uci-defaults 在安装时写入；DNS 记录只经 `OfflineChecks`；联网检测常驻应答；车载音频标志为常量；设置页端口 18080；名字派生（DuckDNS 或 `autoplay.lan`）；uci 只剩 7 个键；LuCI 概览 + 4 个标签。
- 可靠性：分组件守护（`supervision.py`：`BluetoothManager` 10/20/40 秒再每 60 秒重试、`ReceiverManager` 带退避和降级态、三次不过的存活探测）；状态模型 `/var/run/autoplay/status.json`（bluetooth / wifi / uplink / identity / phone / certificate / update / system / tesla，每项 `{state, reason, since}`，`box/docs/STATUS-MODEL.md`）和设置页横幅——**S1、S2 已修**：F50 上没有任何"数据线"文案，蓝牙故障显示带原因的红条；存储与日志卫生（tmpfs 日志环 60 秒镜像到卡、5MB 上限、不再全局 `sync`、在线状态文件只在变化时写、`PYTHONDONTWRITEBYTECODE`、`-XX:ErrorFile`、安装时预生成 AppCDS）；升级日志、启动时补完或回滚、`healthy()` = 接收端应答 + 蓝牙已上电、包缓存；DuckDNS/acme 60/120/300/900 秒退避再每小时、WAN 和 NTP 的 hotplug 触发、证书状态和 30 天内橙条；时钟下限文件；bt-bridge 失败原因词和 stdin 挂断取消、连续两次认证失败提示"删除后重新添加"；出厂重置（密钥粉碎，身份要二次确认）。
- 安全一行项：`X-Frame-Options: DENY`、Host 白名单、去掉 root/1234 文案、JVM `oom_score_adj` +500 / bluetoothd −500、`-XX:+ExitOnOutOfMemoryError`。
- 规模：程序 13,837 → 8,807 行，测试 6,435 → 4,046 行；onecloud 测试 375 → 225（通过），bluetooth 7 个可运行。新增测试：`test_platform_openwrt`、`test_supervision`、`test_status_and_reset`、`test_clock_floor`、`test_factory_reset`、`bluetooth/test_reason`，以及 `test_update` 的迁移和日志用例。

### OpenWrt 包（`openwrt/`）

- 改名 `autoplay`、`autoplay-jre`、`luci-app-autoplay`（含 zh-cn）；`/opt/autoplay`、`/etc/init.d/autoplay`、`/etc/config/autoplay`；postinst 从 `/opt/dashplay/{state,identity}` 和私有 BlueZ 根迁移并复制旧 uci 选项；`CONFLICTS:=dashplay`；`update.py` 先卸 DashPlay 包，首次升级失败则装回并把状态搬回去。
- 新文件：`90-autoplay-tesla`（uci-defaults）、`hotplug-iface`、`hotplug-ntp`、`autoplay-update`。

### 工具（`tools/`）

- `tools/probe/index.html`：阶段 0 车机浏览器能力探测页（单文件、zh/en、≥26px）：WebCodecs/MSE/WebRTC/MediaStreamTrackProcessor、音频解码、自动播放策略、全屏、Wake Lock、麦克风、多点触控、行车中的画布动画计数、私网/CGNAT 可达性、复制和 POST 结果。无头 Chromium 141 渲染验证，截图在 `docs/images/probe.png`。
- `tools/f50/harden.sh`：第 1 周配置加固，带 `--dry-run`/`--revert`/`--status`。
- `tools/f50/measure.sh` + `measure.init`：procd 测量服务；`measure-report.py` 生成摘要，带单元测试。
- `tools/car/touch-latency.md`：240 fps 手机相机测触摸到画面延迟。

### 文档

`README.md`、`README.en.md`、`docs/ARCHITECTURE.md`、`BUILD.md`、`TEST.md`、`ROADMAP.md`、`TESLA.md`、`SECURITY.md`、`DECISIONS.md`，以及 `receiver/docs/TRIM-LOG.md`、`UNVERIFIED-KOTLIN.md`、`receiver/web/README-build.md`、`box/docs/TRIM-LOG.md`、`STATUS-MODEL.md`、`TEST-BASELINE.md`。

### 与上游默认值不同的决定（见 `docs/DECISIONS.md`）

- 只支持 F50 + 特斯拉；局域网固定 100.96.0.1/24。
- 性能模式默认关；自动分辨率上限 1920；界面 300mm。
- 保留并放大"轻点开启声音"提示。
- MSE 音乐路径和视图区域代码冻结不删。
- 无边框跳转保留代码、默认关闭。
- JVM 接收端先用，Rust 原生引擎以协议对等验证为门槛在后。
- 证书续期保留"服务器端续期 + 盒子领取"的选项。

### 已知缺口

- **Kotlin 未编译**：`receiver/docs/UNVERIFIED-KOTLIN.md` 逐文件列出改动和要看的编译风险；第一步是 `cd receiver && ./gradlew build`。
- 接收端按计划没做的：HID 单线程执行器（触摸报文仍在 WebSocket 读线程上写）；`IphoneUsbException.kt`、`Iap2LocationClient.kt`、`Iap2ArtworkReceiver` 因为有调用方而保留。
- 盒子侧没做完的：`box/skills/autoplay-install/SKILL.md` 只改了名，内容还是 N1/DashPlay 时代的；`box/tools/`（固定版本的 `spd_dump`/`lz4`）没有导入，安装脚本的 `check`/`flash` 阶段要从 DashPlay 的检出里拿；dbus-next 的蓝牙测试（`test_bluez`、`test_recovery`）需要装了 dbus-next 0.2.3 的机器；时钟下限的 `/time` 提示和把 `receiver-access.json` 挪进 tmpfs 是接收端侧的待办；更新源和清单 URL 是 `openwrt-autoplay` 占位符；`openwrt/autoplay/Makefile` 的 `PKG_HASH:=skip`。
- 没有任何 F50 实测数据（功耗、温度、CPU、延迟）；`tools/f50/measure.sh` 和探测页就是为了补这一块。
- 接收端还没有 `/probe` 接口和 `/var/run/autoplay/session` 会话钩子；探测页的 POST 和 `autoplay-tune` 的会话模式为它们预留。
- 无 SIM 时的证书路径不存在；DuckDNS 从国内 SIM 卡是否可达未验证。
