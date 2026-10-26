# 路线图：工作包与界面批次对照仓库状态

工作包 WP0–WP10 来自《AutoPlay 日常使用加固路线图》，界面第 1–4 批来自《AutoPlay 界面审查》§六，精简步骤来自《硬件视角审查》§2.4 和《特斯拉专属精简补充》。状态只有三种：**本里程碑已做**（0.1.0 仓库里有）、**下一步**（第 1–4 周）、**之后**。诚实起见：本里程碑没有一行代码在车上或盒子上运行过。

## 一、本里程碑（0.1.0）已做

| 项目 | 对应 | 在哪 |
|---|---|---|
| PlayPort 硬分叉，63 个补丁按顺序落成 git 历史（精简第 1 步） | 硬件审查 §2.2 第 1 项、§2.4 步骤 1 | `receiver/`，`git log -- receiver` |
| 分叉基线选 `e3beae4`（10.25），吸收上游修掉的 6 项（解码积压、特斯拉模式断网踢人、JRE jlink、HTTP Date 校时、rebind_domain、重连提速） | 《DashPlay 2026.10.25 变更评估》§四 | `box/`、`openwrt/` |
| 阶段 0 探测页 | 技术路径 §六阶段 0；特斯拉专属补充 §四"启动时记录 UA/尺寸/DPR/配色" | `tools/probe/` |
| WP0 盒子侧指标：温区、冷却状态、cpufreq、CPU0 忙碌/软中断、WCN/PCIe 中断、内存、JVM RSS、站点数、`ss -tin`、wlan0 字节；CSV 到 tmpfs，60 秒一次刷盘 | WP0；硬件审查 §六"记录方式" | `tools/f50/measure.sh`、`measure.init`、`measure-report.py` |
| WP0 端到端延迟的相机法 | WP0 | `tools/car/touch-latency.md` |
| WP1 配置项：`dl_reboot=0`、国家码/149/VHT80、启动尝试 6 次或锁定 | WP1、PA#1/#5/#9 | `tools/f50/harden.sh` 第 1–3 项 |
| WP7 三小项中的两项：uhttpd 密钥、adb 关闭（第三项"SSH 提示文字"是代码改动，未做） | WP7、PA#3/#15 | `harden.sh` 第 4–5 项 |
| 第 1 周硬件配置项：A76 限频、去掉 `mali_kbase`、RPS 到大核、`oom_score_adj`、tmpfs 限额、`errors=remount-ro`、LED 关；CPU0 深度睡眠的 A/B 开关 | 硬件审查 §五阶段 1、H1/H3/H5/H7/H9 | `harden.sh` 第 6–8 项、`autoplay-tune` |
| WP6 的 `tcp_notsent_lowat=32768` | WP6 | `autoplay-tune` 的 sysctl |
| 文档：架构（含状态模型）、构建、测试、特斯拉、安全、决策、署名 | — | `docs/`、`NOTICE.md` |

## 二、下一步（第 1–4 周，按路线图 §四的顺序）

### 第 1 周

- [ ] 上车跑探测页，定下画面档位（预期 A 档）和音频模式（预期车载蓝牙）。
- [ ] 装 `measure.sh`，跑 `harden.sh` 的 A/B 顺序（`tools/f50/README.md` 末尾），得到第一组真实的温度、CPU0、延迟数据。
- [ ] 电源和散热件到位（5V ≥3A 随点火通断、散热片 + 风扇、高耐久卡）。
- [ ] **配对文件原子写**（WP3；`CarPlayServer.kt` 启动时原地重写配对文件，断电可能清空所有配对）——代码，小。
- [ ] 界面第 1 批里 F50 专属的 P0：S1（OpenWrt 状态里输出 `wired_capable: false`，一行）、S2（去掉 `--wired` 和"wired CarPlay only"文案，蓝牙故障显示原因）、S3（去掉 root/1234）；V3、V5、V7、V8、V9 的小改动。
- [ ] 接收端启动器给自己写 `oom_score_adj=+500`、加 `-XX:+ExitOnOutOfMemoryError`（WP2）。

### 第 2–3 周

- [ ] WP2 进程守护重做：组件独立重启、指数退避、蓝牙后台重试、JVM 心跳 `/healthz`、`/var/run/autoplay/session` 会话钩子（`autoplay-tune session on|off` 已就位）。
- [ ] WP3：日志进内存只落尾部、状态文件有变化才写、证书续期在 WAN 连上/NTP 同步时触发并从 60 秒退避、时区和 fake-hwclock。
- [ ] 状态通道 `status.json`（ARCHITECTURE §4.2）的后端，界面第 2 批（共用状态模型 V1/V22/S7/S8/S14、配对独立页 S4、报错体系 V6、检测页改版 V10）。
- [ ] 精简第 2–4 步：拆 Debian 继承、删有线、删 N1/手机上网/macOS/死代码（硬件审查 §2.4）。
- [ ] 特斯拉专属 D1–D17 里不碰 `web/` 的部分：局域网常量、`answer_tesla_checks` 常量、公网 IPv6 删除、uci 7 键、LuCI 4 标签、安装脚本修 `--sim yes` 写 `answer_tesla_checks=0` 的缺陷。

### 第 3–4 周

- [ ] WP4 底座决策：在 5.4 上浸泡 v2026.10.19.3，还是去验证 6.18（Wi-Fi 稳定性修复只进了主线）；温度监控和过热策略（≥80°C 页面提示并降分辨率，≥95°C 有序释放）。
- [ ] 界面第 3 批：字号和触控令牌（V4/V15，`html{font-size:clamp(18px,1.9vmin,26px)}`）、欢迎页（V14）、悬浮按钮策略（V2，默认隐藏）、吐司（V12）、夜间（V13，含 iOS 27 的 `uiAppearanceUpdate`）、面板重组（V11）。
- [ ] 特斯拉专属的网页端 W1–W10：删麦克风、媒体会话、小鹏全屏家族、二维码、自定义分辨率；MSE 音乐放编译开关后（F1）。

### 第 4–6 周

- [ ] WP5/WP6 按收益逐项做，每项前后测量：DSCP AF41、画布 `alpha:false`、JCA ChaCha20、G1/Serial 的选择、封面改走 HTTP、LagGate 调优、duck/unduck、音频优先出队、自适应缓冲。
- [ ] 界面第 4 批：首次使用 9 屏、设置页信息架构、LuCI 概览页、双语。

## 三、之后

| 项目 | 对应 | 前置 |
|---|---|---|
| `autoplayd`：一个原生守护进程替掉全部 Python（路线 B） | 硬件审查 §四第一阶段、WP2/WP3 | 先冻结四个接口：蓝牙桥命令行、探测命令行、状态 JSON、签名器接口 |
| 原生引擎 `engine=native`（复用 LIVI 的 Rust 协议栈，路线 C） | 硬件审查 §四第三阶段 | 三个去风险原型通过：Unix socket 喂原生 WSS 转发器、LIVI crate 用稳定版 Rust 编成 aarch64-musl、iAP2 引导对等比对 |
| C′ 档（WebRTC + 直接 Canvas） | 技术路径 §3.4 | 探测页证明 HTTP 页面下主线程 `MediaStreamTrackProcessor` 可用且行车时画面刷新 |
| 双手机连接规则、走开再回来自动接回 | dashplay-tesla 分析 §三第 1、5 项 | 状态机落在 `autoplayd` 里，防火墙用 nft 集合 |
| 服务器端续期证书 + 盒子领取 | dashplay-tesla 分析 §三第 7 项、WP3/WP9 | 先验证 DuckDNS/Let's Encrypt 从国内 SIM 卡是否可达 |
| 复活两形状视图区域（带边框 ↔ 无边框 300ms 切换） | 特斯拉专属补充 F3 | 实测两种形状的尺寸和重启后浏览器的默认形状 |
| WP7 其余：配对/删除/升级要 PIN、Host 白名单、单控制端、每设备令牌、CA `nameConstraints`、恢复出厂、apk 签名 | WP7、SECURITY.md | — |
| WP9：CI（应用补丁、构建、单元测试、台架）、确定性打包、签名 apk 源、事务式升级 | WP9 | — |
| WP8：多 iPhone 优先级、一键导出日志包、开机目录序号命名 | WP8 | 状态通道 |
| WP10：跟进 DashPlay（每 2–3 天一版）、mu300-linux（单维护者）、iOS 测试版、特斯拉更新说明；修复回馈上游 | WP10 | 每周对照一次 |

## 四、明确不做

有线 CarPlay、F50 连别人的热点、MJPEG 转码、MSE/WebRTC 当主链路、2.4 GHz 热点、一开始就原生重写、GraalVM 原生编译（aarch64 musl 没有静态 JDK 库）、用 C 从 UxPlay 改、Android Automotive 车型、比亚迪 DiLink 路线、catplay 的代码（无许可证）。理由见技术路径 §五和硬件审查 §四。
