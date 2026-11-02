# 变更记录

格式参考 Keep a Changelog；版本号从 0.1.0 起，1.0 之前不承诺兼容性。

## [未发布] — 2026-11-03 — 发布到 GitHub 前的文档核对与隐私清理

代码没有变（只改了两处用法文本和一句状态页提示）。

- README（中英）重写为可以从头读到尾的说明，并对照代码订正：实测的 F50 原厂固件是 **B13**（按 mu300-linux 刷机），不再写"需要 B16"；视频是 H.264 / H.265；声音默认全走特斯拉蓝牙；三个页面的入口与用途；在线升级目前不可用；加入 2026-11-02 的实车照片（已去元数据、打码）。
- 对照代码逐篇核对 `docs/`、`box/`、`openwrt/`、`receiver/`、`tools/` 的说明：uci 7 键 → 12 键、测试 225 → 263、四个 → 五个检查脚本、LuCI 标签页名、DuckDNS → DuckDNS / DNSPod、`AUTOPLAY_UPDATE_FEED`、`MUSIC_ELEMENT` → `PAGE_PLAYS_MUSIC`；把 0.1.0 时代的"尚未上车""不校验 Host""本地 CA"等现状描述改为 1.2.0 的实情；ADR-4/5/7/9 加"后续"注记；ROADMAP 补 0.1.1–1.2.0 已做、重排待办；SECURITY §1/§4 更新；AUDIT-0.1.1 与 UI-0.1.2 标为历史快照。
- `receiver/README.md` 从上游 PlayPort 的 macOS 说明重写为本分叉的说明；`receiver/identity/README.md`、`receiver/NOTICE.md`、`box/README.md` 不再提示任何取得配件身份的途径（本项目不提供、不下载、不说明）。`box/skills/autoplay-install/SKILL.md`（上游 DashPlay 86 KB 的 B16/N1/玩客云装机向导，含下载共享身份的步骤）换成指向安装说明的短文。
- 隐私：git 历史重写，一处个人邮箱改为 `autoplay@localhost`，CHANGELOG 中车主域名改为"车主自己的域名"；测试与工具里的示例蓝牙地址改用文档保留段；`.gitignore` 排除原始照片与视频目录。
- 待定：`box/scripts/f50-*.py`、`prepare-*.py`、`skills/autoplay-install/downloads.json` 这组上游 B16 刷机/装机脚本按 ADR-11 不是安装路线、未被使用，是删除还是标注保留，待项目组决定。

## [1.2.0] — 2026-11-02 — 车机窗口比例下的界面；下拉与确认框不再交给浏览器

两张页面（`https://…:18443/` 投屏页与设置面板、`http://…:18080/` 盒子设置页）在特斯拉的 773×601 带边框窗口、1256×706 无边框页、1256×560、1920×1200 和手机形状下逐屏截图核对（`docs/UI-1.2.0.md`）。功能、协议、画面几何和接收端都没有变；接收端只改了版本串（仍需在有网的机器上 `./gradlew build`，连同 1.1.0 未编译的四个文件）。

- **投屏页选择器**：夜间模式、语言、CarPlay 内容大小、帧率、视频编码五个原生 `<select>` 下拉改为页内选项表（`src/picker.ts`：居中 `<dialog>`，每项一行 ≥ 3.6rem，当前项打勾并获焦，「取消」；Esc/点背景关闭）。`<select>` 隐藏着保留为值的持有者，选中派发一次 `change`，`main.ts` 的逻辑不变。
- **二级菜单**：两张页面的 `<details>`（画质与兼容、连接与兼容性、备用控制；盒子页的手机行）打开时若超出可视区便自己滚入（放得下对齐底部，放不下从标题开始）。
- **声音走蓝牙时的常用页**：一句散文改为「声音」分组下带蓝牙图标的卡片。
- **盒子设置页**：样式换到投屏页同一套令牌（根字号 `clamp(20px,2.78vmin,24px)`，标签 1.2rem、说明 1rem、行/按钮 ≥ 3.2rem，手机 17px/46px，分隔线 1px，≥1100px 两栏）；配对进行中整页只有配对面板，配对码和「一致 / 不一致」在 773×601 首屏；**「删除此 iPhone」「立即升级」不再用浏览器 `confirm()`**（车机浏览器可能不弹），第一次按下进入确认屏（`?ask=remove|install`），确认按钮带 `confirmed=1`；页尾 6 行脚本做 `<details>` 滚入，无 JS 时页面照常。
- 工具：`box/tools/render_settings_states.py` 渲染盒子页 8 个状态为静态 HTML；`receiver/web/scripts/ui-shots.mjs` 用 Playwright 在所有形状下截两张页面并量字号/行高（本地 mock，不碰设备）。
- 测试：盒子侧 263 个（+2：两个确认屏的往返；3 个旧断言改为两步）；`check-car.mjs` +1 段（选项表）；网页五个检查脚本、类型检查、esbuild 构建通过。
- 版本：接收端、网页包、OpenWrt 包 1.2.0；LuCI 依赖 `autoplay (>=1.2.0)`。ADR-15。

## [1.1.0] — 2026-11-02 — 声音走蓝牙；上游 10.26–11.01 的可靠性修复

**接收端四个 Kotlin 文件改动未经编译**（没有 Gradle 网络），清单见 `receiver/docs/UNVERIFIED-KOTLIN.md`；拿到有网的机器先 `cd receiver && ./gradlew build`。

- **声音（ADR-14，`docs/AUDIO.md`）**：新增 uci `audio_route_navigation`，**默认 `bluetooth`**——接收端不向 iPhone 提供任何 CarPlay 音频（`AirPlayConfig.disableAudioOutput`），音乐、导航播报、通话、Siri 全部经特斯拉蓝牙播出，页面无声、隐藏解锁条和音量、不打开音频输出；`carplay` 为备选（页面播导航，1.0.x 的做法）。LuCI「iPhone → 导航播报」切换；盒子设置页新增「声音」格显示当前模式；`run-receiver --audio-route-navigation`、`receiver-access.json` 的 `audioRouteNavigation`、`boot.ts playportPageAudio`。
- **网页不再播放音乐**（两种模式都如此；上游 2026-11-01 实车：行驶中的特斯拉对播音乐的网页弹横幅→页面尺寸变化→CarPlay 每约 10 秒重协商）：`media` 类型的流丢弃并计数（`musicDropped`），提示一次"请在 iPhone 控制中心把音频输出选为特斯拉"；删除 `music-output.ts`、`aac-mp4.ts`、`MUSIC_ELEMENT`（ADR-5 冻结项结束）。
- **F50 蓝牙与接收端（上游 10.25.1–10.31.3）**：hci0 出现后解除所有蓝牙 rfkill 的软阻塞（BlueZ 5.83 会让 hci0 带阻塞上线），硬阻塞给出 `rfkill-hard` 原因；蓝牙桥 ConnectProfile 超时后先清掉 BlueZ 残留的挂起请求再做链路恢复；配对代理加"代际"保护，BlueZ 取消一次确认后上一次尝试的迟到回调不能确认或清掉下一部手机的请求；每个被接受的 AirPlay 连接拿到完整的空闲宽限（`IdleReleaseTimer`，首次配对/换手机不再被上一部手机的空闲时间切断）；`cds.log` 出现 "invalid archive" 时删除被截断的 AppCDS 归档（否则每次启动多约 3 秒）。
- **域名证书（上游 10.26–10.31）**：申请前先确认有默认路由、DNS 服务商和 CA 都能解析，否则 15 秒后再看且不计失败（开机首轮不再白白吃掉 60 秒退避）；acme.sh 的每个请求经 curl 壳加 `--connect-timeout 10 --max-time 90 --retry 2`（固定版本的 acme.sh 本身不改）；失败原因改为代码（`curl<N>`、`timeout`、`network`、`certificate`、`acme`），设置页据此给出文字；`box/docs/STATUS-MODEL.md` 同步。
- 测试：盒子侧 261 个（+12），网页 `check-car` 的音乐段改为"丢弃音乐"规则并修正兼容显示段对 `document` 的隐式依赖；Kotlin 测试 +6（未运行）。
- 版本：接收端、网页包、OpenWrt 包 1.1.0；LuCI 依赖 `autoplay (>=1.1.0)`。

## [1.0.1] — 2026-11-02 — 1.0.0 的收尾

以 1.0.0 的实车版本为基线，不改功能和架构；接收端只改了一个版本字符串，需要重新编译才会得到 `server-1.0.1.jar`。

- 测试：修正 1.0.0 加 DNSPod 时没跟上的两个断言（`test_openwrt` 默认键 7 → 11 个，`test_own_domain` 的 `own_config()` 返回带 `provider`）；为 DNSPod 分支新增 6 个单元测试（字段校验、uci 读取、域名拼法、不更新记录、acme.sh 走 `dns_dp` 且凭证只在环境变量里）；出厂重置测试覆盖 4 个新键；新增 `openwrt/tests/test_uci_defaults.py`，用假 `uci` 跑安装脚本（4 个用例）。盒子侧 249 个测试全部通过。
- LuCI：补齐 1.0.0 新增的 13 条中文翻译，去掉 4 条过期词条；"自己的域名（DNSPod）"的说明改为建议同时在 DNSPod 控制台加一条指向 100.96.0.1 的 A 记录，并提示 API Token 是账号级凭证。
- 安装脚本 `90-autoplay-tesla`：5 GHz 仍设 CN，但信道已在 149–165 的保留（车主在 LuCI 里选的 153–165 不再被升级改回 149）；提示文字相应调整。
- 文案：`own_domain.py` 的日志和设置页提示不再只说 DuckDNS；模块说明写明两条路线和 A 记录建议。
- 文档：`docs/AUDIO.md`（哪些声音走蓝牙、哪些走网页，及其原因与代码位置）；`docs/TESLA.md` 记录 1.0.0 实车确认的事实（149–165、DNSPod 证书、播报出声）并留出待填的车机版本/UA 表；`docs/DECISIONS.md` ADR-12（DNSPod）、ADR-13（CN/149–165）；装机说明改为 1.0.1：在线升级在项目有自己的发布密钥和软件源之前不可用，只能手动装 apk；`docs/TEST.md` 加 `openwrt/tests`。
- 版本：接收端、网页包、OpenWrt 包统一 1.0.1；`Main.kt` 的回退版本串从 0.1.1 改为 1.0.1。

未动的已知事项（见 `docs/AUDIT-0.1.1.md` §五和《AutoPlay 1.0.0 修改审阅》§五）：升级断电恢复过早标记完成、恢复出厂与写入者的竞态、项目自己的发布密钥与软件源、DNSPod 最小权限凭证（`dns_tencent`）、HID 发送线程、发送队列字节上限。

## [1.0.0] — 2026-11-02 — 实车验证版

首个在特斯拉车内实测通过的版本：F50（原厂固件 B13，按 mu300-linux 刷成 OpenWrt 25.12，5.4 内核；0.1.1 记录的"B13 无安装链"到此不再成立）+ 特斯拉浏览器，无线 CarPlay 画面、触摸、导航播报已验证可用。

- 域名证书：新增**腾讯云（DNSPod）**作为自有域名证书的签发源，与 DuckDNS 并存（`dns_provider` 切换）。`own_domain.py` 增加 `dnspod` 分支（acme.sh `dns_dp` 插件 + `DP_Id`/`DP_Key`）；新增 `own_domain`/`dnspod_id`/`dnspod_token` 配置项与 LuCI「访问名称」表单；工厂重置会清除这些凭证。
- 无线：安装时把 5 GHz 无线固定为中国区 `CN` / 信道 `149`（`90-autoplay-tesla`），解决厂商镜像国家码 `TR`（法规不含 149–165、信道锁在 36–48）导致特斯拉搜不到热点的问题。
- 打包：acme.sh 额外携带 `dns_dp.sh`（校验哈希）；`autoplay-2*` 通配符改为 `autoplay-[0-9]*`，兼容语义化版本。
- 版本号统一为 1.0.0（接收端 `server-1.0.0.jar`、网页包、OpenWrt 包 `autoplay-1.0.0-r1.apk`）。
- 实车状态：蓝牙上电、iPhone 无线 CarPlay 已连接（`phone: live`）、证书 `ok`（Let's Encrypt，车主自己的域名）。

## [0.1.2] — 2026-10-31 — 网页界面迭代

- 设置改为常用、显示、连接三页；改善中文字号、行距、触控尺寸和窄屏布局。
- 精简双语说明，区分 CarPlay 内容大小与设置页字号；将即时应用的编码选项放入高级区。
- 保持保存结果可见，修正模态设置遮挡通知与浏览器检测的问题；保存期间锁定竞争的画质选项。
- 前端回归、类型检查、生产构建及四种视口的中英文布局检查通过；未实机验证。
- 网页包版本 0.1.2；接收端与盒子业务代码仍为 0.1.1。本次不提供新的固件/接收端二进制。
- 详情见 `docs/UI-0.1.2.txt`。

## [0.1.1] — 2026-10-31 — 本机回归与可靠性修订

以 0.1.0 的 `7d8bcca` 为基线，原版本未覆盖。F50 B13、特斯拉 AMD Model 3P、iPhone 15 Pro / iOS 27.2 未做实机测试。

- 接收端：JDK 21 构建条件统一；配对有效性与双副本持久化；视频队列丢帧后等待关键帧；视频配置去掉多余尾字节；NAL 长度避免整型溢出；二进制静态资源按字节响应；iOS 27.2 分支回归。
- 前端：关闭时使异步解码初始化失效；新解码器等待关键帧；HEVC 初始化后补请求；媒体负载使用视图减少复制，丢帧先于格式转换；短包校验；快速连点释放顺序；断线音频休眠和 duck 重置；不完整 PCM 帧不再越界。
- 盒子：状态写入改文件与目录 fsync；状态发布有序、失败可重试、since 不随温度刷新；旧进程探测结果不误伤新进程；证书异常进入重试；时钟下限单调保存；POST 长度、编码、读取超时边界；回滚 SHA256SUMS 必须有 Ed25519 签名。
- 安装与打包：flash 增加 B16 声明门禁并保留实际内核哈希验证，明确拒绝 B13；认证只接收用户本地文件；程序包不再锁死 server-0.1.0.jar 或漏掉新 Python 模块。
- 测量：正整数间隔验证；各输出文件独立状态；网卡计数器重置留空；滚动不重复表头；刷盘偏移兼容空白。
- 测试结果、性能微基准与尚未修复的发布阻断项见 `docs/AUDIT-0.1.1.md`。

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
