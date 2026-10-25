# 变更记录

格式参考 Keep a Changelog；版本号从 0.1.0 起，1.0 之前不承诺兼容性。

## [0.1.0] — 2026-10-26 — 里程碑：工程骨架

**未上车验证。** 这个版本把上游快照、工具和文档放进一个仓库，建立测量和加固的起点；没有在任何车上运行过，Kotlin 改动没有编译过（见 `receiver/docs/UNVERIFIED-KOTLIN.md`）。

### 新增

- 单一仓库：`receiver/`（PlayPort `9a0882d` 硬分叉，DashPlay 的 63 个补丁按顺序落成提交）、`box/`（DashPlay `e3beae4`）、`openwrt/`（openwrt-dashplay `5f17702`）。
- `tools/probe/index.html`：阶段 0 车机浏览器能力探测页（单文件、zh/en、≥26px）：WebCodecs/MSE/WebRTC/MediaStreamTrackProcessor、音频解码、自动播放策略、全屏、Wake Lock、麦克风、多点触控、行车中的画布动画计数、私网/CGNAT 可达性、复制和 POST 结果。无头 Chromium 141 渲染验证，截图在 `docs/images/probe.png`。
- `tools/f50/harden.sh`：第 1 周配置加固（`dl_reboot=0`、国家码/149/VHT80、启动回退策略、uhttpd 密钥重生成、adb 关闭、去掉 GPU 等模块、`autoplay-tune` 开机服务：CPU0 深度睡眠、RPS、A76 限频、`dmesg -n 1`、`oom_score_adj`、tmpfs、核心转储关闭、`tcp_notsent_lowat`、LED 关、可选的 `tune2fs -e remount-ro`），带 `--dry-run`/`--revert`/`--status`。
- `tools/f50/measure.sh` + `measure.init`：procd 测量服务，10 秒一行 CSV 到 tmpfs，60 秒追加到 SD 卡；`measure-report.py` 生成摘要，带单元测试。
- `tools/car/touch-latency.md`：240 fps 手机相机测触摸到画面延迟的步骤和评分表。
- 文档：`README.md`、`README.en.md`、`docs/ARCHITECTURE.md`、`BUILD.md`、`TEST.md`、`ROADMAP.md`、`TESLA.md`、`SECURITY.md`、`DECISIONS.md`、`NOTICE.md`、`.gitignore`、`LICENSE`。

### 与上游默认值不同的决定（见 `docs/DECISIONS.md`）

- 只支持 F50 + 特斯拉；局域网固定 100.96.0.1/24。
- 性能模式默认关；分辨率按温度门限回退（H1）。
- 保留并放大"轻点开启声音"提示。
- MSE 音乐路径和视图区域代码冻结不删。
- 无边框跳转保留代码、默认关闭。
- JVM 接收端先用，Rust 原生引擎以协议对等验证为门槛在后。
- 证书续期保留"服务器端续期 + 盒子领取"的选项。

### 已知缺口

- 没有任何 F50 实测数据（功耗、温度、CPU、延迟）；`tools/f50/measure.sh` 和探测页就是为了补这一块。
- 接收端还没有 `/probe` 接口和 `/var/run/autoplay/session` 会话钩子；探测页的 POST 和 `autoplay-tune` 的会话模式为它们预留。
- 界面审查的 S1/S2（F50 设置页推荐数据线、蓝牙故障被说成只能用数据线）仍在上游代码里，本里程碑未修。
- 无 SIM 时的证书路径不存在；DuckDNS 从国内 SIM 卡是否可达未验证。
