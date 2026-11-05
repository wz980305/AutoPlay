# 变更记录

格式参考 Keep a Changelog；版本号从 0.1.0 起，1.0 之前不承诺兼容性。每节第一段是盒子「程序更新」里显示的摘要（最多四行），写短。

## [1.4.1] — 2026-11-05 — 断线后主动请回 iPhone、卡住的画面流 10 秒内重连（借鉴 DashPlay 11.04）；盒子设置页按窗口形状重排，顶部只留要处理的提示

无线 CarPlay 意外断开后，盒子会在 45 秒内主动邀请那部 iPhone 一次；画面流半截卡住时 10 秒内断开重连；短拖动不再变成轻点。盒子设置页重新排版、说明文字改短，检查更新等结果就地显示，顶部只留需要处理的提示。

- **断线后主动请回 iPhone**（DashPlay 2026.11.04 `playport-wireless-session-recovery`，GPL-3.0）：原来盒子要先在 Wi-Fi 上看到 iPhone 才邀请它，可链路断掉后 iPhone 往往离开盒子的 Wi-Fi，要等 CarPlay 经蓝牙邀请才会回来。新的 `WirelessSessionRecovery`：一个正在用的无线会话自己结束时，45 秒内可以不等 Wi-Fi、直接经蓝牙邀请它的主人一次——只一次，只给那部 iPhone，且它仍在配对列表里（`phone-presence.py allowed`，不探测网络）；空闲释放、改显示或定位、关机这些盒子自己做的断开都会取消它；这次邀请没有结果也不会把这部 iPhone 记成"不接受邀请"而退避。
- **画面流读取期限**（同上 `ScreenStream`）：一条视频消息开始到达后必须在 10 秒内收完，否则断开并重连；以前 Wi-Fi 在半帧时断掉，画面会停住而会话仍显示"正在使用"。两条消息之间的安静不受限制（静止画面可以很久不发）。
- **触控**：抬起前若最后的位置还没发出去，先补发它再发抬起——以前短拖动、拖回起点会被当成轻点。
- **投屏页向盒子的请求有期限**：读 2.5 秒、写 6 秒（`ask-box.ts`），盒子不回答时设置面板不再一直转圈，写入失败会报错而不是假装成功。
- **盒子设置页**（`http://100.96.0.1:18080/`）：
  - 顶部的条只留需要处理的状态和错误（`box/docs/STATUS-MODEL.md` 新的一节）：点「检查更新」后不再在顶部出一条"几秒后刷新页面"，「程序更新」里就地显示转圈的「正在检查更新…」，页面每 2 秒自己刷新直到结果出来；邀请、拒绝、升级被拒这些结果写在各自分组下面。提示条改成带圆形符号的卡片（红色错误、橙色提醒）。
  - 每行加上 iOS「设置」式的彩色图标（CarPlay 地址、iPhone、Wi-Fi、OpenWrt、网址、更新、诊断），「已是最新」「有新版本」各有自己的图标；「iPhone」一组合并为一个列表，「添加 iPhone」在列表最后一行，说明在组下面。
  - 按窗口形状核对过 773×601、1256×706、1256×560、1920×1200、390×844、360×740（深浅两色）：窄屏上地址、域名、「交给 iPhone 的 Wi-Fi」不再被截成"…"，地址在端口前换行，"Wi-Fi"不再断成"Wi-"/"Fi"；手机上的连接链字号和图标真正变小（原来的手机规则被后面的同级规则覆盖，没有生效）；宽屏左栏是 CarPlay 地址和 iPhone，右栏是网络、网址、更新、高级；1920 宽时内容限宽 64rem，不再铺满。「立即升级」和「检查更新」之间的分隔线原来画了两条。
  - 小字重写：每条一句话，只说发生了什么、该做什么。去掉了括号里的内部名词（"Marlin3 固件""rfkill""acme.sh""/var/lib/bluetooth"、"上游"），这些仍在诊断记录里；"（重启盒子 / 查看诊断）"改成"可以重启盒子；仍不行请下载诊断记录"；证书行不再写"正式"、不带句号；配对步骤从三句长句改成三个短句；删除、升级、恢复出厂的确认屏各删掉一半说明。
  - 「有新版本」只显示这一版说明的第一段（最多四行，去掉 Markdown 记号），下面一个「完整更新说明」链接到 GitHub 上的这个版本。
- 测试：接收端 `ScreenStreamReadDeadlineTest`（4 个）、`WirelessSessionRecoveryTest`（6 个）；盒子侧 243（+4）；投屏页 `check.mjs` 加短拖动、拖回起点、静止手指和请求期限。
- 版本：接收端、网页包、OpenWrt 包 1.4.1；LuCI 依赖 `autoplay (>=1.4.1)`；安装说明改名 `AutoPlay-1.4.1-安装使用说明.md`。

## [1.4.0] — 2026-11-05 — 车辆定位交给 iPhone（可选，默认关闭）；画质的应用按钮改成 iOS 式操作行

做法由调研定下，而不是实车试错（`docs/LOCATION.md` §一，ADR-18）：iPhone 自己定位差时会改用车机的位置，坏的、晚的、冻住的也照用；特斯拉浏览器给的是车的位置、带速度航向，但精度可能是占位值 9999.99、时间戳可能是不走的常数；已有方案没有一个默认打开它。

- **投屏页**「常用 → 导航 → 使用车辆定位」（默认关）：打开时才请求浏览器授权，拒绝则开关回到关；页面可见时每秒 `getCurrentPosition` 一次（Tesla Android 在特斯拉上用了三年的做法），经已有的 WSS 送到盒子。中国大陆境内多一个「坐标系」（WGS-84 / GCJ-02），两项下面各写出换算后交给 iPhone 的位置，写法同 iPhone「指南针」，停车对照一次即可。调试浮层多一行「车辆定位 n/s · 车速」；`stats` 多 `locSent`/`locFailed`/`locAcc`/`locDenied`。
- **接收端** `CarLocation`：位置变了才算新点（浏览器重复给的、冻住的都不算），NMEA 时间用盒子收到的时刻，精度 9999 以上当未报、真实精度差于 100 m 的丢掉，跳出"70 m/s × 间隔 + 100 m"的点扣住到下一个点确认，2.5 s 没有新点就什么都不发（iPhone 用回自己的定位）；GCJ-02 按公式换回 WGS-84（与特斯拉自己给深圳一辆车的 GCJ-02 相差约 1 m）。位置只在 Wi-Fi 的 iAP2 隧道上声明（蓝牙引导链路不声明，DiPlay PR #157），开关打开时 CarPlay 重连一次；关掉立即停发。开关和坐标系存在 `config.json`（`carLocation`、`carLocationDatum`），`GET /api/display` 带出，`POST /api/location` 修改。每分钟一行 `car location: … new= repeated= jumped= dropped= sent= …`，不记坐标。
- **协议**：新的 `Iap2LocationReporter`（形状取自 DiPlay）每 250 ms 向位置来源要一次、每个点只发一次，替换上游循环"每收到一个 iPhone 消息就重发最后一个位置"的写法；NMEA 时间带百分之一秒，海拔、航向未知时留空（不再写 0.0 / 0.00）。不发 `$PASCD`。
- **「显示 → 画质」的应用按钮**：原来那块常驻的蓝色实心「应用并重连」按钮改成 iOS 式的操作行——只有选了和当前不同的「CarPlay 内容大小」或「帧率」时，卡片底部才出现一行蓝字「应用并重连」（CarPlay 没在用时是「应用」），点后变灰直到盒子回答，应用完就收起；状态句从卡片里移到卡片下方作脚注，「已保存，正在重新连接 CarPlay」6 秒后自动消失。两行之间补上了一直缺的分隔线（它们在 `fieldset` 里，没吃到分组的分隔规则）。
- **盒子**：`run-receiver.py` 每次启动都重建 `config.json`，现在把 `carLocation`、`carLocationDatum` 带过去（否则重启一次开关就回到关）；恢复出厂删掉整个 `state/`，开关随之回到关。
- 测试：接收端 `CarLocationTest`（16 个）、`Iap2LocationReporterTest`（7 个），在 GitHub Actions 上编译并通过；盒子侧 239（+1）；投屏页 `check-location.mjs`（特斯拉浏览器的占位精度与常数时间戳、GCJ-02 与特斯拉的对照、指南针写法、一次只读一个、隐藏时不读）。
- 版本：接收端、网页包、OpenWrt 包 1.4.0；LuCI 依赖 `autoplay (>=1.4.0)`；安装说明改名 `AutoPlay-1.4.0-安装使用说明.md`，加第九节。

## [1.3.2] — 2026-11-05 — 设置面板左栏只留文字、删掉 2560 开关；发布流程修正

第一个经在线升级送到盒子的版本（装着 1.3.1 的盒子会在一天内看到它）。

- 投屏页设置面板：左侧「常用 / 显示 / 连接」去掉图标，只留文字（右侧各行的图标保留）。
- 删除「允许 2560 分辨率」开关：它只在解码够快时把最长边上限从 1920 提到 2560，为 2.5K 屏准备；特斯拉最宽的无边框页（1256 CSS px × 1.53）是 1922 px，打开它只多 2 px，而 MCU2（Atom）车机绝不能收到 2560（硬件审查 H1）。上限固定 1920，浏览器里残留的 `f50-allow-2560` 标记启动时清掉。
- 盒子设置页「检查更新」按钮下不再显示「上次检查 …」/「还没有检查过」；检查结果（已是最新、有新版本、检查没有成功）照常显示在按钮上方。
- v1.3.1 标签的发布运行两次失败在 OpenWrt 打包：工作流在调用 `release.sh` 前设了 `umask 077`（本意只为私钥文件），交给 SDK 容器的源文件和程序包于是只有属主可读，容器里的构建用户读不到。现在 `umask` 只作用于写私钥那一行，`build-packages.sh` 也把交给容器的副本统一设为可读。
- 工作流可以手动发布一个已有标签（Run workflow，`tag` 填 `vX.Y.Z`），用当前分支上的工作流构建并发布它；v1.3.1 由此发布，版本号不变。
- `openwrt/scripts/build-packages.sh`：SDK 容器里的网络步骤（luci feed、Temurin 下载）失败时重试三次，任何一步失败都打印日志尾部（上面那次失败没有留下任何原因）。
- 版本：接收端、网页包、OpenWrt 包 1.3.2；LuCI 依赖 `autoplay (>=1.3.2)`；安装说明改名 `AutoPlay-1.3.2-安装使用说明.md`，需要手动安装的盒子写成"1.3.1 或更新的版本"。

## [1.3.1] — 2026-11-05 — 在线升级接通：自己的发布密钥、单仓库 Release、GitHub Actions 发布

功能和界面与 1.3.0 相同。这一版是第一个带安装包和签名的正式发布：装着 1.3.0 或更早版本的盒子手动装一次 1.3.1，之后的版本在设置页点一下就能升级（`docs/RELEASE.md`）。

- **发布密钥**：项目自己的 Ed25519 密钥对，公钥替换了上游 DashPlay 的 `box/scripts/onecloud/update-key.pem`（指纹 `2d53ecc5bdb9c382`）；私钥不进仓库，存在 GitHub Actions secret `AUTOPLAY_RELEASE_KEY` 和车主的密码管理器里。
- **单仓库**：更新清单、程序包、OpenWrt 包、`SHA256SUMS` 都挂在 `wz980305/AutoPlay` 的同一个 Release 上（DashPlay 用两个仓库）。`update.py` 的 `FEED_REPO` 默认等于 `REPO`；`make-update-manifest.py` 默认 owner `wz980305`、包地址指向同一个 Release，`--feed-repo` 保留两仓库布局的可能。
- **`box/scripts/release.sh`**：一条命令完成版本号一致性检查（五处 + CHANGELOG 小节）→ 接收端 `./gradlew build :server:installDist` → 网页 `npm ci && npm run build` → 程序包 → Docker SDK 打 apk → 更新清单（说明取 CHANGELOG 对应小节）→ 清单与哈希核对；`--publish` 再用私钥签清单和 `SHA256SUMS`、用仓库里的公钥反验、`gh release create`。
- **`.github/workflows/release.yml`**：每次推送和 PR 跑盒子、OpenWrt、F50 工具的测试和投屏页检查，再用 `release.sh` 完整构建（产物保留 14 天，不签名不发布）；推送 `v*` 标签时签名并发布 Release。接收端从此在 GitHub 的 JDK 21 上编译——1.1.0 以来没编译过的 Kotlin 改动第一次在这里接受编译器检查。
- `receiver/gradlew` 在 git 里标为可执行。
- 排练：本地用一把临时密钥走完"生成清单 → 核对 → 签名 → 盒子 `update.py check` 从本地 HTTP 服务器取清单、验签、比较版本"的全程，换成盒子的公钥时正确拒绝；Mac 上的私钥与仓库公钥配对已核对。
- 文档：新增 `docs/RELEASE.md`；README（中英）、`box/README*`、`openwrt/README*`、`docs/BUILD.md`、`docs/ROADMAP.md`、`docs/SECURITY.md`（信任根一条）、安装说明（改名 `AutoPlay-1.3.1-安装使用说明.md`，加"直接下载 Release"和第八节在线升级）不再说"在线升级不可用"。
- 版本：接收端、网页包、OpenWrt 包 1.3.1；LuCI 依赖 `autoplay (>=1.3.1)`。

## [1.3.0] — 2026-11-05 — 设置面板按 iOS「设置」收口；网页不再有声音；修屏幕键盘

车主上车一周后的清单（`docs/UI-1.3.0.md`）。接收端的 Kotlin 又改了三个文件，仍未编译（`receiver/docs/UNVERIFIED-KOTLIN.md`）。

- **屏幕键盘（ADR-17）**：浏览器从后台拉回 CarPlay 页面时有时弹出车机键盘。画布不再可聚焦、不再在每次按下时 `focus()`（按键一直在 `window` 上监听）；页面重新可见、`pageshow`、窗口获焦时把浏览器恢复的焦点 `blur()` 掉（本页的对话框打开时除外）；`interactive-widget=overlays-content` + VirtualKeyboard API，万一键盘出现也不改变页面尺寸（否则 CarPlay 会重协商）。`check.mjs`/`check-runtime.mjs` 断言控制器绝不聚焦画布。台架上无法复现车机键盘，要上车确认。
- **只剩"全部走特斯拉蓝牙"（ADR-16，`docs/AUDIO.md`）**：车主在车上确认默认模式可用后，删除 1.1.0 的备选 `carplay` 及其全部代码——网页 `audio.ts`、`audio-timing.ts`、`check-audio.mjs`、解锁条、音量滑杆、「声音」分组、duck、`?promptgain=`、`CAR_MUSIC`/`PAGE_PLAYS_MUSIC`/`PROMPT_BOOST`、`boot.ts playportPageAudio`、调试浮层的声音行、`stats` 的音频字段、浏览器检测的 Web Audio / AudioDecoder 两项；盒子 uci `audio_route_navigation`（升级时由 `90-autoplay-tesla` 与守护进程删掉旧键）、`supervisor_openwrt.audio_route_of()`、`run-receiver --audio-route-navigation`、`receiver-access.json` 的 `audioRouteNavigation`/`carMusic`/`tesla`、盒子页「声音」格、LuCI 下拉与译文、恢复出厂的键表；接收端 `ServerConfig.audioRouteNavigation`/`audioOverBluetooth`，`disableAudioOutput` 固定为 `true`。`run-receiver.py` 仍给 JVM 传 `--car-voice --audio-route-navigation bluetooth`，让 1.3.0 之前编译的接收端也全走蓝牙；新接收端接受并忽略。**代价**：某辆车经蓝牙听不到播报时没有开关可切，只能回 `v1.2.0`。
- **设置面板（投屏页）**：每一行和左侧三个分类都有 iOS 式彩色圆角图标，选中的分类蓝色填充；行内不再有任何小字——删掉「当前请求：夜间」、页脚「本页语言与音量保存在此浏览器…」、「定时：18:30–06:30 使用夜间外观」（时间段进了选项名）、「改变 iPhone 输出的 CarPlay 文字与图标大小…」、永久的「1920 × 998 / 30 fps / H.265」状态行（只在应用过程中说话）、「高分辨率、编码与调试」、「分辨率随窗口自动调整…」、无边框模式 / 视频编码 / 四个开关的说明、「将离开当前画面…」；删掉整个「备用控制」（主屏幕 / 返回 / 刷新画面及 `knob` 发送代码）。标签不折行、当前值过长时截断；左栏 12rem → 11rem。「画质设置」改称「画质」；「连接与兼容性」的当前画面行加上编码。
- **盒子设置页**：不再显示「上游在线；特斯拉自带音乐、地图可以上网。」和开机头几秒的"检测中"，只有上游不可用才有横幅；「声音」分组随音频路径删除。
- 版本：接收端、网页包、OpenWrt 包 1.3.0；LuCI 依赖 `autoplay (>=1.3.0)`；OpenWrt 包与 `update.py` 的发布地址指向 `github.com/wz980305/AutoPlay`（尚无签名发布）。测试：盒子侧 238（删一个音频路由测试、声音格的测试换成"无声音分组、无在线横幅"、加一个"仍给旧接收端传蓝牙参数"的测试），网页四个检查脚本（−`check-audio`），类型检查、esbuild 构建、`ui-shots` 四形状截图通过。安装说明改名 `AutoPlay-1.3.0-安装使用说明.md`。

### 2026-11-03 — 发布到 GitHub 前的文档核对与隐私清理（随 1.3.0 发布）

功能代码没有变（只改了两处用法文本和一句状态页提示）；删掉了一组从未使用的上游脚本。

- README（中英）重写为可以从头读到尾的说明，并对照代码订正：实测的 F50 原厂固件是 **B13**（按 mu300-linux 刷机），不再写"需要 B16"；视频是 H.264 / H.265；声音默认全走特斯拉蓝牙；三个页面的入口与用途；在线升级目前不可用；加入 2026-11-02 的实车照片（已去元数据、打码）。
- 对照代码逐篇核对 `docs/`、`box/`、`openwrt/`、`receiver/`、`tools/` 的说明：uci 7 键 → 12 键、测试 225 → 263、四个 → 五个检查脚本、LuCI 标签页名、DuckDNS → DuckDNS / DNSPod、`AUTOPLAY_UPDATE_FEED`、`MUSIC_ELEMENT` → `PAGE_PLAYS_MUSIC`；把 0.1.0 时代的"尚未上车""不校验 Host""本地 CA"等现状描述改为 1.2.0 的实情；ADR-4/5/7/9 加"后续"注记；ROADMAP 补 0.1.1–1.2.0 已做、重排待办；SECURITY §1/§4 更新；AUDIT-0.1.1 与 UI-0.1.2 标为历史快照。
- `receiver/README.md` 从上游 PlayPort 的 macOS 说明重写为本分叉的说明；`receiver/identity/README.md`、`receiver/NOTICE.md`、`box/README.md` 不再提示任何取得配件身份的途径（本项目不提供、不下载、不说明）。`box/skills/autoplay-install/SKILL.md`（上游 DashPlay 86 KB 的 B16/N1/玩客云装机向导，含下载共享身份的步骤）换成指向安装说明的短文。
- 隐私：git 历史重写，一处个人邮箱改为 `autoplay@localhost`，CHANGELOG 中车主域名改为"车主自己的域名"；测试与工具里的示例蓝牙地址改用文档保留段；`.gitignore` 排除原始照片与视频目录。
- 删除未使用的上游 B16 刷机/装机流程（项目组 2026-11-03 决定）：`box/scripts/f50-install.py`、`f50-backup.py`、`f50-root-plan.py`、`f50-root-bootstrap.sh`、`prepare-f50-*.py`、`prepare-mu300-panel-installer.py`、`verify-f50-tos-candidate.py`、`fetch-install-assets.py`、`install_progress.py`、`build-playport.sh`、`fetch-java.py`、`box/skills/`，连同 4 个测试文件；盒子侧测试 263 → 238。刷机只看 mu300-linux（ADR-11）。

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
