# 路线图：工作包与界面批次对照仓库状态

工作包 WP0–WP10 来自《AutoPlay 日常使用加固路线图》，界面第 1–4 批来自《AutoPlay 界面审查》§六，精简步骤来自《硬件视角审查》§2.4 和《特斯拉专属精简补充》。状态只有三种：**本里程碑已做**（0.1.0 仓库里有）、**下一步**（第 1–4 周）、**之后**。诚实起见：本里程碑没有一行代码在车上或盒子上运行过。

## 一、本里程碑（0.1.0）已做

| 项目 | 对应 | 在哪 |
|---|---|---|
| PlayPort 硬分叉，63 个补丁按顺序落成 git 历史（精简第 1 步） | 硬件审查 §2.2 第 1 项、§2.4 步骤 1 | `receiver/`，`git log -- receiver` |
| 分叉基线选 `e3beae4`（10.25），吸收上游修掉的 6 项（解码积压、特斯拉模式断网踢人、JRE jlink、HTTP Date 校时、rebind_domain、重连提速） | 《DashPlay 2026.10.25 变更评估》§四 | `box/`、`openwrt/` |
| **接收端精简**：删有线、macOS、死代码（精简第 3、5、8 步）；删麦克风上行、正在播放/封面/媒体会话（保留 iAP2 封面排空）、小鹏全屏家族、二维码、自定义分辨率、备用媒体键（D3、D5、D8、D9、W1–W4、W6–W8）；车辆标志改常量 `flags.ts` | 硬件审查 §2.4；特斯拉专属补充 §二、§三 | `receiver/docs/TRIM-LOG.md` |
| **接收端修复**：配对文件原子写（WP3）；DSCP AF41（WP5）；性能模式关 / 1920 上限 / 300mm（H1、特斯拉补充 §五）；画布 `alpha:false`（WP5）；duck/unduck 压低音乐（WP6）；触摸最短按压 + 补发全部抬起（WP5 触摸健壮性的一半）；iOS 27 深浅色（dashplay-tesla §三第 2 项） | WP3、WP5、WP6 | 同上，每项一个提交 |
| **界面第 1 批的投屏页部分**：V1 恢复中遮罩、V3 提示按状态、V7 整宽声音解锁条；第 3 批里的 V4 rem 字号 / 触控目标 / 吐司位置、V13 的 iOS 27 部分、V17 全部字符串走 `t()`；V10 驾驶者可读的双语检测页；V2 画面上不再放悬浮按钮；V19/V11 的自定义分辨率和二维码 | 界面审查 §六第 1、2、3 批（部分） | `receiver/web/src/status.ts`、`style.css`、`public/browser-check.js` |
| **盒子侧精简**：拆隐藏耦合（`state.py`、`tesla_checks.py`、独立 `platform_openwrt.py`，精简第 2 步）；删 Debian、N1/玩客云、STA/手机上网、外接路由、公网 IPv6、本地 CA、有线（精简第 2–4、7、9 步；D6、D7、D10、D12、D13） | 硬件审查 §2.4；特斯拉专属补充 §二 | `box/docs/TRIM-LOG.md` |
| **特斯拉常量**：LAN 100.96.0.1/24 安装时写死、DNS 只经 `OfflineChecks`、`answer_tesla_checks` 常量开、车载音频标志常量、设置页 18080、名字派生、uci 7 键、LuCI 概览 + 4 标签；安装脚本 `--sim yes` 写 `answer_tesla_checks=0` 的缺陷随之消失（D1、D2、D4、D8、D11、D14、D15、D16） | 特斯拉专属补充 §二、§五 | `openwrt/autoplay/files/90-autoplay-tesla`、`autoplay.config` |
| **WP2 的一半**：分组件守护、指数退避、降级态、蓝牙后台重试（10/20/40 秒再每 60 秒）、JVM 存活探测（三次不过重启）、`-XX:+ExitOnOutOfMemoryError`、子进程超时和周期检查的 try/except 计数 | WP2 | `box/scripts/onecloud/supervision.py`、`supervisor_openwrt.py` |
| **WP3 的一半**：日志进内存每 60 秒镜像 5MB 尾部、不再全局 `sync`、状态文件有变化才写、AppCDS 安装时生成、升级日志 + 启动时补完或回滚 + 健康检查 = 接收端应答且蓝牙已上电、证书续期从 60 秒退避并由 WAN/NTP hotplug 触发、证书状态与到期提示、时钟下限 | WP3 | `diagnostics.py`、`update.py`、`own_domain.py`、`clock_floor.py` |
| **状态通道**：`/var/run/autoplay/status.json`，9 个域 `{state, reason, since}`，设置页 `/status.json` 转发；设置页横幅据此显示（S2 蓝牙红条、S7 盒子状态、S8 时效、S14 证书） | ARCHITECTURE §4.2；界面第 2 批的后端 | `status_model.py`、`box/docs/STATUS-MODEL.md` |
| **界面第 1 批的设置页部分**：S1（F50 上无"数据线"文案）、S2（蓝牙故障显示原因）、S3（去掉 root/1234）、S6（验收表移出）、S9 的一部分（升级有日志和回滚） | 界面审查 §三 | `settings_page.py`、`settings_ui.py` |
| **WP7 一行项**：uhttpd 密钥重生成、adb 关闭（`harden.sh`）；`X-Frame-Options: DENY`、Host 白名单、`oom_score_adj`、`PYTHONDONTWRITEBYTECODE`、`-XX:ErrorFile`（盒子侧）；bt-bridge 失败原因码（dashplay-tesla §三第 3 项）；出厂重置并粉碎密钥 | WP7、dashplay-tesla §三 | `settings_page.py`、`factory_reset.py`、`linux/bt-bridge/bridge_reasons.py` |
| **软件包改名** `autoplay` / `autoplay-jre` / `luci-app-autoplay`，`/opt/autoplay`，postinst 从 `/opt/dashplay` 迁移，`CONFLICTS dashplay`（精简第 6 步的"过渡版本"） | 硬件审查 §2.4 步骤 6 | `openwrt/`、`update.py` |
| 阶段 0 探测页 | 技术路径 §六阶段 0；特斯拉专属补充 §四"启动时记录 UA/尺寸/DPR/配色" | `tools/probe/` |
| WP0 盒子侧指标：温区、冷却状态、cpufreq、CPU0 忙碌/软中断、WCN/PCIe 中断、内存、JVM RSS、站点数、`ss -tin`、wlan0 字节；CSV 到 tmpfs，60 秒一次刷盘 | WP0；硬件审查 §六"记录方式" | `tools/f50/measure.sh`、`measure.init`、`measure-report.py` |
| WP0 端到端延迟的相机法 | WP0 | `tools/car/touch-latency.md` |
| WP1 配置项：`dl_reboot=0`、国家码/149/VHT80、启动尝试 6 次或锁定 | WP1、PA#1/#5/#9 | `tools/f50/harden.sh` 第 1–3 项 |
| 第 1 周硬件配置项：A76 限频、去掉 `mali_kbase`、RPS 到大核、tmpfs 限额、`errors=remount-ro`、LED 关、CPU0 深度睡眠的 A/B 开关、`tcp_notsent_lowat` | 硬件审查 §五阶段 1、H1/H3/H5/H7/H9；WP6 | `harden.sh` 第 6–8 项、`autoplay-tune` |
| 文档：架构（含状态模型）、构建、测试、特斯拉、安全、决策、署名；裁剪日志、未编译清单、状态模型说明 | — | `docs/`、`NOTICE.md`、`receiver/docs/`、`box/docs/` |

**做了但没验证**：以上接收端的每一项都没有编译（`receiver/docs/UNVERIFIED-KOTLIN.md`）；盒子侧只有单元测试（225 个通过），没有在 F50 上装过；`UNVERIFIED-KOTLIN.md` 的"需要一台盒子或一辆车"列了 6 件要在车上看的事（封面排空、iOS 27 深浅色、duck 的音量映射、配对 `.bak`、DSCP、触摸释放）。

## 二、下一步（第 1–4 周，按路线图 §四的顺序）

### 第 1 周

- [ ] **编译接收端**：`cd receiver && ./gradlew build`，按 `UNVERIFIED-KOTLIN.md` 逐文件排查；打一个 `autoplay-bundle.tar`，装到 F50 上。
- [ ] 上车跑探测页，定下画面档位（预期 A 档）和音频模式（预期车载蓝牙）。
- [ ] 装 `measure.sh`，跑 `harden.sh` 的 A/B 顺序（`tools/f50/README.md` 末尾），得到第一组真实的温度、CPU0、延迟数据。
- [ ] 电源和散热件到位（5V ≥3A 随点火通断、散热片 + 风扇、高耐久卡）。
- [ ] 补盒子侧没做完的：重写 `box/skills/autoplay-install/SKILL.md`（还是 N1/DashPlay 时代的）；导入或说明 `box/tools/` 的 `spd_dump`/`lz4`；更新源 URL 从占位符改成真实发布页，`PKG_HASH` 填上。
- [ ] 接收端侧的两个小项：`/time` 提示喂给时钟下限；`receiver-access.json` 挪进 tmpfs（H7）。
- [ ] V5（宽高比相差 >2.5% 时等比缩放加黑边）、V8 面板里的跳转确认文案、V12 吐司排队——界面第 1 批剩下的小项。

### 第 2–3 周

- [ ] WP2 剩下的：Wi-Fi 看门狗、hci0 复位时重跑蓝牙初始化、`/var/run/autoplay/session` 会话钩子（`autoplay-tune session on|off` 已就位）、`/healthz` 心跳。
- [ ] WP3 剩下的：时区和 fake-hwclock 式的第二时间源；`e2fsck -n` 健康检查；证书到期日显示在投屏页。
- [ ] 投屏页消费 `status.json`：`waiting-iphone` 的原因、`overheating`、`box-restarting`、`busy`（界面第 2 批的前端一半，V22、V6 报错体系、S4 配对独立页）。
- [ ] WP5 触摸健壮性的另一半：HID 单线程执行器、触摸租约。
- [ ] 特斯拉专属 §四新增项：信道不在 36–48/149–165 时告警、无边框按视口判断、"行驶中保持连接"提醒、"音乐从页面出来了"提示、解析 `tesla-dns.log` 里未知的检测域名、跳转 URL 国际化。

### 第 3–4 周

- [ ] WP4 底座决策：在 5.4 上浸泡 v2026.10.19.3，还是去验证 6.18（Wi-Fi 稳定性修复只进了主线）；温度监控和过热策略（≥80°C 页面提示并降分辨率，≥95°C 有序释放）。
- [ ] 界面第 3 批剩下的：对比度和次要控件（V15）、欢迎页两栏（V14）、夜间修饰对界面本身的变暗（V13 的页面侧）、面板重组为"常用 / 高级"（V11）。
- [ ] 特斯拉专属 W10：设置面板瘦身到 22 行；W5/F3 视图区域的两形状复活要先有实测。

### 第 4–6 周

- [ ] WP5/WP6 剩下的，每项前后测量：JCA ChaCha20 替换 BouncyCastle、`CICompilerCount`/G1 或 Serial 的选择、解码器出错回退后请求关键帧、发送队列满时请求关键帧、LagGate 调优、音频优先出队、语音 AudioWorklet 自适应缓冲、音乐缓冲 PI 微调、页面隐藏时暂停视频。
- [ ] 界面第 4 批：首次使用 9 屏、设置页信息架构、设置页双语（投屏页已双语，LuCI 已有概览）。

## 三、之后

| 项目 | 对应 | 前置 |
|---|---|---|
| `autoplayd`：一个原生守护进程替掉全部 Python（路线 B） | 硬件审查 §四第一阶段、WP2/WP3 | 先冻结四个接口：蓝牙桥命令行、探测命令行、状态 JSON、签名器接口 |
| 原生引擎 `engine=native`（复用 LIVI 的 Rust 协议栈，路线 C） | 硬件审查 §四第三阶段 | 三个去风险原型通过：Unix socket 喂原生 WSS 转发器、LIVI crate 用稳定版 Rust 编成 aarch64-musl、iAP2 引导对等比对 |
| C′ 档（WebRTC + 直接 Canvas） | 技术路径 §3.4 | 探测页证明 HTTP 页面下主线程 `MediaStreamTrackProcessor` 可用且行车时画面刷新 |
| 双手机连接规则、走开再回来自动接回 | dashplay-tesla 分析 §三第 1、5 项 | 状态机落在 `autoplayd` 里，防火墙用 nft 集合 |
| 服务器端续期证书 + 盒子领取 | dashplay-tesla 分析 §三第 7 项、WP3/WP9 | 先验证 DuckDNS/Let's Encrypt 从国内 SIM 卡是否可达 |
| 复活两形状视图区域（带边框 ↔ 无边框 300ms 切换） | 特斯拉专属补充 F3 | 实测两种形状的尺寸和重启后浏览器的默认形状 |
| WP7 其余：配对/删除/升级要 PIN、单控制端、每设备令牌、私有 BlueZ 随升级重建、apk 签名 | WP7、SECURITY.md | — |
| WP9：CI（构建、单元测试、台架）、确定性打包、签名 apk 源 | WP9 | — |
| WP8：多 iPhone 优先级、一键导出日志包、开机目录序号命名 | WP8 | 状态通道 |
| WP10：跟进 DashPlay（每 2–3 天一版）、mu300-linux（单维护者）、iOS 测试版、特斯拉更新说明；修复回馈上游 | WP10 | 每周对照一次 |

## 四、明确不做

有线 CarPlay、F50 连别人的热点、MJPEG 转码、MSE/WebRTC 当主链路、2.4 GHz 热点、一开始就原生重写、GraalVM 原生编译（aarch64 musl 没有静态 JDK 库）、用 C 从 UxPlay 改、Android Automotive 车型、比亚迪 DiLink 路线、catplay 的代码（无许可证）。理由见技术路径 §五和硬件审查 §四。
