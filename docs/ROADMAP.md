# 路线图：工作包与界面批次对照仓库状态

工作包 WP0–WP10 来自《AutoPlay 日常使用加固路线图》，界面第 1–4 批来自《AutoPlay 界面审查》§六，精简步骤来自《硬件视角审查》§2.4 和《特斯拉专属精简补充》。状态截至 1.5.3（2026-11-13）：1.0.0 已在一辆 2022 款 Model 3 上跑通（画面、触摸、导航播报、证书），1.1.0 把声音默认交给特斯拉蓝牙并引入上游的可靠性修复，1.2.0 重做了两张页面的界面，1.3.0 按车主上车一周后的清单收口设置面板、删掉网页里的声音、修屏幕键盘，1.3.1 接通在线升级（签名的 GitHub Release，接收端从此在 GitHub Actions 上编译和测试），1.4.0 加上可选的车辆定位，1.4.1 借鉴 DashPlay 11.04 的断线恢复并重排盒子设置页，1.4.3 充实行车诊断记录，1.5.0 让坐标系自动、两张页面随日间/夜间换色、显示盒子温度、系统更新后保留 AutoPlay。第一节是 0.1.0 里程碑的记录，第一节甲是之后各版做了什么，第二节是还没做的。


## 一、0.1.0 里程碑已做（2026-10-26，历史记录）

| 项目 | 对应 | 在哪 |
|---|---|---|
| PlayPort 硬分叉，63 个补丁按顺序落成 git 历史（精简第 1 步） | 硬件审查 §2.2 第 1 项、§2.4 步骤 1 | `receiver/`，`git log -- receiver` |
| 分叉基线选 `e3beae4`（10.25），吸收上游修掉的 6 项（解码积压、特斯拉模式断网踢人、JRE jlink、HTTP Date 校时、rebind_domain、重连提速） | 《DashPlay 2026.10.25 变更评估》§四 | `box/`、`openwrt/` |
| **接收端精简**：删有线、macOS、死代码（精简第 3、5、8 步）；删麦克风上行、正在播放/封面/媒体会话（保留 iAP2 封面排空）、小鹏全屏家族、二维码、自定义分辨率、备用媒体键（D3、D5、D8、D9、W1–W4、W6–W8）；车辆标志改常量 `flags.ts` | 硬件审查 §2.4；特斯拉专属补充 §二、§三 | `receiver/docs/TRIM-LOG.md` |
| **接收端修复**：配对文件原子写（WP3）；DSCP AF41（WP5）；性能模式关 / 1920 上限 / 300mm（H1、特斯拉补充 §五）；画布 `alpha:false`（WP5）；duck/unduck 压低音乐（WP6）；触摸最短按压 + 补发全部抬起（WP5 触摸健壮性的一半）；iOS 27 深浅色（dashplay-tesla §三第 2 项） | WP3、WP5、WP6 | 同上，每项一个提交 |
| **界面第 1 批的投屏页部分**：V1 恢复中遮罩、V3 提示按状态、V7 整宽声音解锁条；第 3 批里的 V4 rem 字号 / 触控目标 / 吐司位置、V13 的 iOS 27 部分、V17 全部字符串走 `t()`；V10 驾驶者可读的双语检测页；V2 画面上不再放悬浮按钮；V19/V11 的自定义分辨率和二维码 | 界面审查 §六第 1、2、3 批（部分） | `receiver/web/src/status.ts`、`style.css`、`public/browser-check.js` |
| **盒子侧精简**：拆隐藏耦合（`state.py`、`tesla_checks.py`、独立 `platform_openwrt.py`，精简第 2 步）；删 Debian、N1/玩客云、STA/手机上网、外接路由、公网 IPv6、本地 CA、有线（精简第 2–4、7、9 步；D6、D7、D10、D12、D13） | 硬件审查 §2.4；特斯拉专属补充 §二 | `box/docs/TRIM-LOG.md` |
| **特斯拉常量**：LAN 100.96.0.1/24 安装时写死、DNS 只经 `OfflineChecks`、`answer_tesla_checks` 常量开、车载音频标志常量、设置页 18080、名字派生、uci 7 键（1.2.0 时为 12 键，1.3.0 起 11 键）、LuCI 概览 + 4 标签；安装脚本 `--sim yes` 写 `answer_tesla_checks=0` 的缺陷随之消失（D1、D2、D4、D8、D11、D14、D15、D16） | 特斯拉专属补充 §二、§五 | `openwrt/autoplay/files/90-autoplay-tesla`、`autoplay.config` |
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

## 一甲、0.1.1 → 1.5.3 已做

| 版本 | 做了什么 | 在哪 |
|---|---|---|
| 0.1.1（10-31） | 接收端在 JDK 21 上编译并跑通测试；媒体恢复、配对落盘、设置请求、状态并发、安装门禁与回滚签名的一批修复 | `docs/AUDIT-0.1.1.md`、`CHANGELOG.md` |
| 0.1.2（10-31） | 投屏页界面：全屏三页设置工作区、rem 字号尺度、夜间模式简化、"CarPlay 内容大小"命名 | `docs/UI-0.1.2.txt` |
| 1.0.0（11-02） | **实车跑通**（2022 款 Model 3 AMD、iPhone 15 Pro / iOS 27.2）；自有域名证书加腾讯云 DNSPod 路线（ADR-12）；5 GHz 固定 CN / 149–165（ADR-13，特斯拉只在这段搜得到热点） | `docs/TESLA.md` §7、`own_domain.py`、`90-autoplay-tesla` |
| 1.0.1（11-02） | DNSPod 的测试与中文翻译；安装脚本保留车主选的 149–165 信道；`openwrt/tests` | `CHANGELOG.md` |
| 1.1.0（11-02） | 声音默认全部走特斯拉蓝牙，网页不再播音乐（ADR-14）；上游 10.26–11.01 的 F50 蓝牙 rfkill、配对代理代际、空闲宽限、AppCDS、证书申请等待网络等修复；失败原因代码 | `docs/AUDIO.md`、`receiver/docs/UNVERIFIED-KOTLIN.md` |
| 1.2.0（11-02） | 两张页面按车机窗口形状核对；页内选项表替代原生下拉；二级菜单滚入视野；盒子页同一尺度、配对码首屏、页内确认屏（ADR-15） | `docs/UI-1.2.0.md` |
| 1.3.0（11-05） | 设置面板按 iOS「设置」收口（每行图标、无行内小字）；删掉网页播导航的备选和全部页面音频代码（ADR-16）；画布不再持有焦点，修浏览器拉回时弹键盘（ADR-17）；盒子页不再报"上游在线"；发布地址指向 `wz980305/AutoPlay` | `docs/UI-1.3.0.md`、`docs/AUDIO.md` |
| 1.3.1（11-05） | 在线升级接通：项目自己的 Ed25519 发布密钥、单仓库的签名 Release、`release.sh` 与 GitHub Actions（每次推送编译接收端并跑全部测试，推送标签即发布） | `docs/RELEASE.md` |
| 1.3.2（11-05） | 设置面板左栏只留文字、删掉「允许 2560 分辨率」；发布流程修正（`umask`、手动发布已有标签） | `CHANGELOG.md` |
| 1.4.0（11-05） | 车辆定位交给 iPhone（可选，默认关闭；只发新鲜、连续的点，否则什么都不发，ADR-18）；画质的「应用并重连」改成 iOS 式操作行 | `docs/LOCATION.md` |
| 1.4.1（11-05） | 借鉴 DashPlay 11.04：断线后主动请回 iPhone 一次、画面流读取期限 10 秒；短拖动不再变成轻点；投屏页向盒子的请求有期限；盒子设置页按窗口形状重排，顶部只留要处理的提示 | `box/docs/STATUS-MODEL.md`、`CHANGELOG.md` |
| 1.4.2（11-05） | 在线升级先经 GitHub API 下载（github.com 的下载链接返回 502 时也能升级） | `docs/RELEASE.md` |
| 1.4.3（11-10） | 行车诊断记录更完整：各温区和是否降频、车机页面的完整报告、盒子自己的断开与再邀请、Wi-Fi 上的设备 | `CHANGELOG.md` |
| 1.5.0（11-10） | 坐标系默认「自动」（ADR-19；国行 Model 3 实测为 GCJ-02）；盒子设置页重排成设置面板的样子，等待画面、设置面板、盒子设置页的日间/夜间跟随「夜间模式」，「返回」按来路（ADR-20）；盒子温度与过热提醒；诊断记录加处理器占用；mu300-linux 系统更新后保留 AutoPlay | `docs/UI-1.5.0.md`、`docs/LOCATION.md`、`docs/RELEASE.md` |
| 1.5.1（11-11） | 设置面板的标题栏按盒子设置页的位置摆：标题和「完成」在宽屏上跟着内容列，窄窗口和手机用同一套尺寸；两张页面的位置由 `ui-shots.mjs twins` 量 | `docs/UI-1.5.0.md` §七、`CHANGELOG.md` |
| 1.5.2（11-13） | 「性能模式」改名为「增强模式」（车主定；保存的开关不变） | ADR-3、`CHANGELOG.md` |
| 1.5.3（11-13） | 「检查更新」整次最多 60 秒（车主定）：各处轮流起步、同时在问，清单和签名来自同一处；页面等到检查结束，刷新的页面带脚本重新载入 | `docs/RELEASE.md`、`CHANGELOG.md` |

此前列在"下一步"而已经做掉的：信道不在 36–48 / 149–165 时告警（`supervisor_openwrt.channel_warning`）、无边框按视口判断（`main.ts`）、上游 B16 刷机/装机脚本与 SKILL.md 按 ADR-11 删除（2026-11-03）、探测页之外的 Tesla 检测。

**做了但没验证**：1.3.0 的键盘修复要上车确认；1.5.0 的日间/夜间配色和盒子设置页的「返回」只在电脑的浏览器里核对过；mu300-linux 系统更新后装回 AutoPlay 没有在真机上跑过；探测页还没在车上跑过（`docs/TESLA.md` §7 的表仍是空的）；没有长期浸泡数据。车主已确认：声音全走蓝牙在车上可用（这是删掉备选的依据）；国行 Model 3 浏览器给的坐标是 GCJ-02（1.5.0 默认「自动」的依据）。1.1.0 到 1.3.0 没有编译就写下的 Kotlin 改动，已在 1.3.1 的第一次 GitHub Actions 运行里编译并通过测试（`receiver/docs/UNVERIFIED-KOTLIN.md` 留作记录）。

## 二、下一步

### 上车前

- [x] **编译接收端**：1.3.1 起每次推送都在 GitHub Actions 上 `./gradlew build`（编译两个模块并跑全部测试），安装包由发布流程打出（`docs/RELEASE.md`）。
- [x] 项目自己的发布密钥与软件源（1.3.1）：Ed25519 发布密钥，公钥在 `update-key.pem`；单仓库 Release；`release.sh` + GitHub Actions 工作流（`docs/RELEASE.md`）。
- [ ] apk 包本身的签名（现在靠清单哈希 + 清单签名，安装仍要 `--allow-untrusted`；WP9 剩下的一项）。

### 车上要测的

- [ ] 停车跑一次 `tools/probe/`，填满 `docs/TESLA.md` §7 的表（车机版本、UA、DPR、两种窗口尺寸）。
- [ ] 声音：播报的第一个字有没有被吃；来电、Siri 是否照常；故意不连车机蓝牙时声音去了哪（走蓝牙本身车主已确认可用）。
- [ ] 1.2.0 的界面：选项表在车机浏览器里是否出现（嵌套 `showModal()`）；盒子页删除手机的确认屏。
- [ ] 1.3.0：从后台拉回浏览器十次，键盘不再出现（`docs/UI-1.3.0.md` §六）；三页设置的图标和当前值在两种窗口下对齐。
- [ ] 1.4.0 车辆定位：行驶中打开调试浮层，「车辆定位 n/s」是否在 1/s 左右，导航时会不会长时间停在 0（`docs/LOCATION.md`）。坐标系已在一辆国行 Model 3 上核对（GCJ-02，1.5.0 起默认「自动」）。
- [ ] 1.5.0：等待画面、设置面板、盒子设置页的日间/夜间是否跟着「夜间模式」；盒子设置页的「返回」是否回到面板的「连接」（`docs/UI-1.5.0.md` §六）。
- [ ] 1.5.4（未发布）：CarPlay 主屏「AutoPlay 设置」图标的名字是否完整；浏览器检测的新样子在特斯拉浏览器里的字号；配对完成后 iPhone 连上时那行字是否自己消失（`docs/UI-1.5.4.md` §四）。
- [ ] 1.5.0：不急着用车时按安装说明第十二节做一次 mu300-linux 系统更新，看 AutoPlay 是否被装回。
- [ ] 装 `measure.sh`，跑 `harden.sh` 的 A/B 顺序，拿到第一组温度、CPU0、延迟数据；相机法测触摸延迟。
- [ ] 电源和散热件到位（5V ≥3A 随点火通断、散热片 + 风扇、高耐久卡）。

### 盒子侧

- [ ] WP2 剩下的：Wi-Fi 看门狗、hci0 复位时重跑蓝牙初始化、`/var/run/autoplay/session` 会话钩子（`autoplay-tune session on|off` 已就位）、`/healthz` 心跳。
- [ ] WP3 剩下的：时区和 fake-hwclock 式的第二时间源；`e2fsck -n` 健康检查；证书到期日显示在投屏页。
- [ ] 接收端侧的两个小项：`/time` 提示喂给时钟下限；`receiver-access.json` 挪进 tmpfs（H7）。
- [ ] `run-receiver.py` 仍给 JVM 传 `--car-voice --audio-route-navigation bluetooth`，为的是 1.3.0 之前编译的接收端；每台盒子都换上 1.3.0 的接收端之后这两个参数可以去掉（`receiver-access.json` 的旧字段 1.3.0 已不再写）。

### 界面

- [ ] 投屏页消费 `status.json`：`waiting-iphone` 的原因、`overheating`、`box-restarting`、`busy`（界面第 2 批的前端一半，V22、V6 报错体系）。
- [ ] "行驶中保持连接"提醒（一趟里两次 3–10 秒、以 `online` 结束的断链）；解析 `tesla-dns.log` 里未知的检测域名。
- [ ] V5（宽高比相差 >2.5% 时等比缩放加黑边）、V12 吐司排队；界面第 3 批剩下的对比度和次要控件（V15）、欢迎页两栏（V14）。
- [ ] WP5 触摸健壮性的另一半：HID 单线程执行器、触摸租约。
- [ ] WP4 底座决策：在 5.4 上浸泡，还是去验证 6.18；温度监控和过热策略（≥80°C 页面提示并降分辨率，≥95°C 有序释放）。已做的一半：诊断记录有各温区和降频状态（1.4.3），盒子设置页显示盒子温度、系统因过热降速时在顶部提醒（1.5.0）；投屏页上的提示、主动降分辨率和有序释放未做。
- [ ] WP5/WP6 剩下的，每项前后测量：JCA ChaCha20 替换 BouncyCastle、`CICompilerCount`/G1 或 Serial 的选择、解码器出错回退后请求关键帧、发送队列满时请求关键帧、LagGate 调优。
- [ ] 界面第 4 批：首次使用引导、设置页双语（投屏页已双语，LuCI 已有概览）。

## 三、之后

| 项目 | 对应 | 前置 |
|---|---|---|
| `autoplayd`：一个原生守护进程替掉全部 Python（路线 B） | 硬件审查 §四第一阶段、WP2/WP3 | 先冻结四个接口：蓝牙桥命令行、探测命令行、状态 JSON、签名器接口 |
| 原生引擎 `engine=native`（复用 LIVI 的 Rust 协议栈，路线 C） | 硬件审查 §四第三阶段 | 三个去风险原型通过：Unix socket 喂原生 WSS 转发器、LIVI crate 用稳定版 Rust 编成 aarch64-musl、iAP2 引导对等比对 |
| C′ 档（WebRTC + 直接 Canvas） | 技术路径 §3.4 | 探测页证明 HTTP 页面下主线程 `MediaStreamTrackProcessor` 可用且行车时画面刷新 |
| 双手机连接规则、走开再回来自动接回 | dashplay-tesla 分析 §三第 1、5 项 | 状态机落在 `autoplayd` 里，防火墙用 nft 集合 |
| 服务器端续期证书 + 盒子领取 | dashplay-tesla 分析 §三第 7 项、WP3/WP9 | ADR-12 后不再需要：盒子直接向 Let's Encrypt 签发已在国内 SIM 上验证（DNSPod 路线）；只剩 DuckDNS 接口从国内 SIM 的可达性未验证 |
| 复活两形状视图区域（带边框 ↔ 无边框 300ms 切换） | 特斯拉专属补充 F3 | 实测两种形状的尺寸和重启后浏览器的默认形状 |
| WP7 其余：配对/删除/升级要 PIN、单控制端、每设备令牌、私有 BlueZ 随升级重建、apk 签名 | WP7、SECURITY.md | — |
| WP9：CI（构建和单元测试已做，1.3.1 起每次推送都跑；台架未做）、确定性打包、签名 apk 源（发布清单和 `SHA256SUMS` 已签名，apk 本身未签） | WP9 | — |
| WP8：多 iPhone 优先级、一键导出日志包、开机目录序号命名 | WP8 | 状态通道 |
| WP10：跟进 DashPlay（每 2–3 天一版）、mu300-linux（单维护者）、iOS 测试版、特斯拉更新说明；修复回馈上游 | WP10 | 每周对照一次 |

## 四、明确不做

有线 CarPlay、F50 连别人的热点、MJPEG 转码、MSE/WebRTC 当主链路、2.4 GHz 热点、一开始就原生重写、GraalVM 原生编译（aarch64 musl 没有静态 JDK 库）、用 C 从 UxPlay 改、Android Automotive 车型、比亚迪 DiLink 路线、catplay 的代码（无许可证）。理由见技术路径 §五和硬件审查 §四。
