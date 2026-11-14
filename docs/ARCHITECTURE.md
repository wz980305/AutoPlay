# 架构

本文描述 1.3.0 的实际形态（1.0.0 起在车上跑通）和已经定下来的目标形态；两者不同的地方标出来。2026-10-26 写成，之后按各版修订：DNSPod 路线（1.0.0）、声音默认全走蓝牙（1.1.0）、页内选项表与确认屏（1.2.0）、声音只剩蓝牙一种、画布不持有焦点、uci 11 键（1.3.0）。依据：《F50 车机浏览器 CarPlay 技术路径》§三、《硬件视角审查》§2.3、§四、《界面审查》§五、审计笔记 `viewer_ui_audit.md` §12。

## 1. 拓扑

```
 iPhone
  ├─① 蓝牙 iAP2：配对、MFi 认证、交出热点名/密码/信道 ─────────▶ F50 (hci0, 私有 BlueZ)
  ├─② 5 GHz Wi-Fi (ch149, WPA2)：AirPlay RTSP:7000、H.264 / H.265 视频流（无音频流） ─▶ F50 (wlan0, 100.96.0.1)
  │     ◀──────────────── HID 触摸、iAP2 控制隧道 ──────────────────── F50
  └─④ 特斯拉蓝牙：音乐、导航播报、通话、Siri、方向盘按键（原生） ──────▶ 车机

 F50（OpenWrt 25.12 / mu300-linux，5.4 内核；热点 100.96.0.1/24；5G SIM 给车机上网和证书续期）
  └─③ HTTPS/WSS :18443：H.264 / H.265 原样转发（二进制帧）、状态 ─────────────▶ 车机浏览器（WebCodecs → canvas）
        ◀──────────── WSS 文本帧：触摸、按键、显示设置 ───────────────── 车机浏览器
```

拓扑是硬件定死的（技术路径 §一第 2 条）：SC2355 同一时间只能开一个 Wi-Fi 接口，所以 F50 只能当热点，车机和 iPhone 都连它；F50 不能同时连别的热点。F50 没有 USB 主机，有线 CarPlay 不可能。

地址：局域网 100.96.0.1/24（CGNAT 段；特斯拉浏览器拒绝 192.168/10/172.16，用域名也不行）。车机打开的地址是 `https://<自己的域名>:18443/`（DuckDNS 或 DNSPod 托管的域名），由盒子上的 dnsmasq 以 `address=/<名>/100.96.0.1` 本地应答（OpenWrt 的 DNS 重绑定保护会丢弃上游返回的 100.64/10 地址，所以必须本地应答）。

## 2. 进程与端口（1.3.0）

```
procd
 └─ /etc/init.d/autoplay (S99)  →  python3 /opt/autoplay/supervisor_openwrt.py     守护（supervision.py：分组件重启、退避、降级态）；
      │                                                                             设置页 :18080（含 /status.json）；诊断；升级检查；特斯拉常驻应答；DuckDNS / DNSPod 证书；状态模型
      ├─ BluetoothManager → python3 board_zte_f50.py                                 F50 蓝牙：dbus-daemon(私有总线) + btattach(/dev/ttyBT0) + bluetoothd(/opt/autoplay-bluez)
      │                                                                             上电失败 10/20/40 秒重试，之后每 60 秒；原因词进 status.json 的 bluetooth 域
      ├─ ReceiverManager → python3 run-receiver.py → java (Temurin 21, -Xmx384m, AppCDS, ExitOnOOM)   接收端（PlayPort 分叉）
      │     ├─ mDNS _airplay._tcp                                                   iPhone 发现
      │     ├─ :7000  AirPlay RTSP（配对、/info、SETUP）+ 视频 TCP 流 + 音频 UDP     ← iPhone
      │     ├─ :18443 HTTPS 静态页 + WSS /ws + JSON API（/api/display 也是存活探测）  ← 车机浏览器；连接打 DSCP AF41
      │     ├─ bt-bridge（python3, dbus-next）                                        每次邀请 iPhone 时起一个，走 iAP2 RFCOMM；失败时打印 reason=<词>
      │     └─ phone-presence.py                                                    无会话时每 2 秒 fork 一次做 ARP 探测，在线文件只在变化时写（硬件审查 H5 要改常驻）
      └─ logread -f                                                                  看 dnsmasq 查询，常驻应答车机的联网检测（tesla 域）
 mu300 底座：hostapd、dnsmasq(:53/:67)、netifd、uhttpd(LuCI :80)、mobile-data、thermal-guard、mu300-cpu、mu300-power…
 AutoPlay 工具：/etc/init.d/autoplay-tune (S98)、/etc/init.d/autoplay-measure (S99)   见 tools/f50/
```

| 端口 | 协议 | 谁用 | 备注 |
|---|---|---|---|
| 7000/tcp | AirPlay RTSP + 事件 | iPhone → F50 | 视频流和 HID 事件在 RTSP 协商出的连接上 |
| 动态 udp | RTP 音频、RTCP | iPhone → F50 | |
| 5353/udp | mDNS | iPhone ↔ F50 | 热点必须放行组播，不开客户端隔离 |
| 18443/tcp | HTTPS + WSS | 车机 → F50 | 投屏页、`/ws`、`/api/display`、`receiver-access.json`（仅本页令牌，仍写在 `web/dist/`，挪进 tmpfs 是待办）；端口可配（uci `viewer_port`） |
| 18080/tcp | HTTP | 手机 → F50 | 设置页（iPhone、蓝牙、证书、更新、出厂重置）和 `/status.json`；明文、无认证，有 Host 白名单和 `X-Frame-Options: DENY`（见 SECURITY） |
| 80/tcp | HTTP | 车机、手机 → F50 | LuCI（概览 + 网络 / iPhone / 自有地址 / 更新四个标签）；`100.96.0.2` 别名上的 80 转到设置页，并应答车机的联网检测 |
| 53/67 | DNS/DHCP | 车机、iPhone | dnsmasq；`address=` 把域名指到 100.96.0.1 |

目标形态（硬件审查 §四路线 B，WP2）：一个静态链接的守护进程 `autoplayd` 接管全部 Python 的职责（守护、蓝牙拉起、iAP2 桥、在线探测、状态通道、设置 API、升级、特斯拉/DuckDNS），JVM 保留为协议引擎；再以协议对等验证为门槛评估 Rust 原生引擎（`engine=jvm|native`）。端口收敛为 18443（投屏页 + API）、一个常驻状态页、LuCI 80。0.1.0 已经把 Python 侧的职责切成了 `supervision.py` 里的几个类和 `status_model.py` 的一份状态，这就是 `autoplayd` 要冻结的接口。

## 3. 数据流（一帧视频）

```
iPhone 编码 H.264 ─TCP─▶ JVM airplay-screen 线程：读 128B 头 + 包体 → ChaCha20-Poly1305 解密 → 长度前缀改 Annex B
   → Wire.videoFrame（11B 头 + NALU）→ 每个页面一个队列（LagGate：落后 >~300ms 就丢帧，等关键帧）
   → Ktor WebSocket 二进制帧 → Netty TLS → wlan0 ─▶ 浏览器 ws.ts → protocol.ts 解包 → video.ts：VideoDecoder.decode
   → VideoFrame → canvas 2d（alpha:false, desynchronized）→ 车机屏幕
触摸：pointer 事件 → 按画面归一化坐标 → WSS 文本 JSON → JVM → HID 报文 → ChaCha 加密 → iPhone 事件连接
音频：接收端不声明任何音频格式（1.3.0 起固定，ADR-16），iPhone 不建立音频流，音乐、导航播报、通话、Siri
   全部直接走特斯拉蓝牙，WSS 上没有音频，页面没有 Web Audio（1.1.0–1.2.0 的 carplay 备选模式已删除）
车辆定位（1.4.0，可选，默认关，docs/LOCATION.md）：navigator.geolocation 每秒一次 → WSS 文本 JSON → CarLocation
   （判新鲜、去跳点、可选 GCJ-02→WGS-84）→ Iap2LocationReporter → Wi-Fi iAP2 隧道 0xFFFB $GPGGA/$GPRMC → iPhone
```

F50 不解码、不转码，只解密、重封装、再加密。每帧在 JVM 里约 8 次内存拷贝、2 次加解密（硬件审查 H4）；所有网络中断落在 CPU0（H3）。这两条决定了 `tools/f50/harden.sh` 里 RPS、CPU0 空闲状态和 A76 限频的取舍。

## 4. 页面与设置页共用的状态模型

上游原状（0.1.0 之前）：投屏页只有 waiting / starting / live / reconnecting / error 五种显示状态，设置页靠横幅拼凑；蓝牙、认证、过热、升级中、被占用、重协商这些状态要么没有、要么显示成别的东西（界面审查 §一）。这是两套界面问题的共同根因，所以先定状态模型，再改界面。

### 4.1 投屏页状态（`viewer_ui_audit.md` §12）

| 状态 | 触发 | 显示 | 驾驶者能做什么 |
|---|---|---|---|
| `checking` | 页面启动 | 黑底 + 小字眉标 | — |
| `unsupported` | 浏览器检测失败 | 大字标题 + 白话说缺什么（"缺少 H.264 视频解码"）+ 按车型建议 + 折叠的技术详情 | 看详情 |
| `needs-access` | 没有令牌（页面打开时没能从盒子取到 `receiver-access.json`） | 「未取得盒子的访问许可」+ 检查盒子电源与热点、刷新本页（1.5.0 改写：原文让人去点盒子网页上没有的「在车机打开」） | 刷新 |
| `connecting-box` | 首次 `connecting` | 转圈 + "正在连接盒子…" + 3 秒后显示已等待秒数 | 刷新 |
| `box-unreachable` | `closed` 且无画面 >3 秒 | "盒子没有响应" + 清单（通电、热点）+ 已等待 + 次数 | 刷新、盒子网页 |
| `waiting-iphone` | `hello/session sessionActive:false` | 大状态图标 + "等待 iPhone" + 一句话原因（蓝牙未就绪 / 认证失败 / 正常等待） | 添加 iPhone、设置 |
| `starting` | `sessionActive:true`、首帧前 | "iPhone 已连接，正在接收画面…" | — |
| `renegotiating` | 显示设置变更 / 自动适配 | 上一帧调暗 + "正在按新窗口重新连接 CarPlay（约 5 秒）" | — |
| `live` | 首帧解码 | 画面；非全屏时一条细状态栏（状态点、夜间标记） | CarPlay |
| `recovering` | 链路断开（`reset(hold)` / `wake`） | 保留画面 + 40% 遮罩 + 居中常驻"连接中断 · 正在重连 · 触控已暂停"，无超时 | 等待，8 秒后可刷新 |
| `paused-by-box` | LagGate 关闸 | 状态栏小标签"画面暂停（车机变慢）" | — |
| `busy` | 另一个页面在用（需服务端新消息） | "另一块屏幕正在显示 CarPlay" + 接管 | 接管 |
| `box-restarting` | 等盒子应答的轮询 | "盒子正在重启/更新，页面将自动刷新" + 已等待 | — |
| `overheating` | 状态通道 thermal | "盒子过热，已降低画质 / 已暂停" | — |
| `error` | `{title, action, detail}` | 标题 + 动作 ≥22px，64px 按钮，详情折叠 | 重试 / 关闭 |
| `night`（修饰） | 「夜间模式」此刻的结果（日落到日出 / 跟随系统 / 始终白天 / 始终夜间；1.6.4 以前第一项是定时 18:30–06:30，见 ADR-23） | CarPlay 的深浅色随之切换（`docs/TESLA.md` §5）；1.5.0 起等待画面、设置面板和盒子设置页也分日间、夜间两套颜色（§4.3），画面四周和画面上的提示始终深色 | 设置里切换 |

0.1.0 已实现的：`recovering`（保留画面 + 遮罩 + 常驻提示）、`renegotiating`、`live-muted`（整宽底部解锁条，只在 AudioContext 挂起且确实收到页面要播的流时显示）、`connecting-box`/`box-unreachable`/`waiting-iphone`/`starting` 的提示语由 `src/status.ts` 按状态派生（含已等待秒数、盒子失联时隐藏"添加 iPhone"）、`unsupported` 的驾驶者可读双语检测页。还没有的：`busy`、`box-restarting`、`overheating`、`paused-by-box` 的显示，以及从盒子的 `status.json` 派生 `waiting-iphone` 的原因——这是下一步（ROADMAP 第 2–3 周）。`mic-blocked` 在特斯拉专属形态下不存在（不提供麦克风）。

### 4.2 盒子状态通道（STATUS-MODEL，已实现）

设置页、LuCI 概览和（下一步）投屏页读同一份状态，而不是各自拼。实现：`box/scripts/onecloud/status_model.py`（`Status`），由 `supervisor_openwrt.py` 填充，只在变化时写到 `/var/run/autoplay/status.json`（tmpfs），设置页在 `/status.json` 转发；`phone` 域的原因词来自 `/var/run/autoplay/receiver.log` 里 bt-bridge 的 `reason=<词>` 行。完整的域、状态、原因词和页面文案见 `box/docs/STATUS-MODEL.md`，这里只给形状：

```
{ "updated": <epoch>, "mode": "openwrt", "ssid": …, "home": "http://100.96.0.1:18080/", "entries": [...], "name": …,
  "bluetooth":   {"state": "starting|on|failed",                       "reason": "powering|adapter-not-powered|controller-timeout|hci-lost|…", "since": …},
  "wifi":        {"state": "up|waiting",                               "reason": …, "since": …, "ssid": …, "channel": 149, "address": "100.96.0.1"},
  "uplink":      {"state": "online|offline|unknown",                   "reason": …, "since": …},
  "identity":    {"state": "provided|missing",                         "reason": "files-missing|null", "since": …},
  "phone":       {"state": "live|idle|declined|pairing-lost",          "reason": "page-timeout|busy|aborted|timeout|refused|not-paired|auth-failed|…", "since": …, "active": bool},
  "certificate": {"state": "self_signed|issuing|ok|renewing|expiring_soon|expired|failed", "reason": …, "since": …, "not_after": …},
  "update":      {"state": "current|available|installing|failed|check-failed|check-off", "reason": "版本|阶段|信息", "since": …},
  "system":      {"state": "starting|ok|restarting|degraded",          "reason": "receiver-exit-<code>|receiver-liveness|hot", "since": …, "temp_c": …},
  "tesla":       {"state": "on|off|failed",                            "reason": …, "since": …} }
```

规则：每个域是 `{state, reason, since, ...extra}`；`since` 是状态**或原因**最后一次变化的墙钟时间，轮询的页面可以把 `since` 远落后于 `updated` 的条目置灰（界面审查 S8 的"陈旧状态"）；`reason` 是短的机器词或 `null`，页面把词映射成句子（`settings_page.BLUETOOTH_TEXT`、`own_domain.message`），LuCI 原样显示；状态色只做辅助，永远配文字；不出现端口、uci 键、文件路径、API 名称，这些收进"详细信息"。温度在 `system.temp_c` 里（SoC ≥95°C 时 reason 为 `hot`），没有单独的 `thermal` 域；投屏页的 `overheating` 以后从它派生。升级的健康检查 `update.healthy()` 也读这份状态：`system` 为 `ok` 且 `bluetooth` 为 `on` 才算升级成功，断电后的 `recover()` 用同一个判断决定补完还是回滚。

`tools/f50/harden.sh` 装的 `autoplay-tune` 按同一个目录约定使用 `/var/run/autoplay/session` 作为会话标志；谁来写这个文件（`phone.state == live` 时）是 WP2 剩下的一小项。

### 4.3 两张页面的日间/夜间与往返（1.5.0，ADR-20）

投屏页按「夜间模式」算出此刻是日间还是夜间（`receiver/web/src/night.ts` 的 `isNight`），用在三处：告诉 CarPlay（`{type:'night'}`）；给自己的界面换色（`<html data-theme>`；等待画面在脚本运行之前就画出来，所以 `index.html` 头部有几行按同一规则先定好，`check-car.mjs` 把它和 `isNight` 逐种情况对照）；写进去盒子设置页的链接。

- **去**：`http://<盒子>:18080/?night=1|0&from=panel|page[&turn=<秒>]`（`boxPageUrl`）。盒子设置页头部的脚本把这几项记进 `sessionStorage`（一小时内有效；1.6.5 起「日落到日出」带 `turn`，即下一次日落或日出，有它时结果到那一刻为止、之后反过来再管 8 小时，开着的页面到那一刻自己换色）并从地址里去掉，据此设 `data-theme` 和 `data-from`；服务器不读这两个参数。没有它们时（手机直接打开、书签）跟随浏览器的 `prefers-color-scheme`。
- **回**：有 `data-from` 时标题栏的按钮是「返回」。从设置面板来的回到 `<投屏页地址>#settings=connection`，投屏页见到这个片段就打开面板的「连接」并把片段去掉（`panelFromHash`），再点「完成」回到 CarPlay；从等待画面来的回到等待画面；直接打开的没有可退回的地方，按钮是「CarPlay 画面」。投屏页地址取这台浏览器来时用的那一个（按请求的 `Host` 在 `entries` 里选）。
- **颜色**：两边的日间、夜间配色是同一组值，各写在自己的样式表里（`receiver/web/src/style.css`、`box/scripts/onecloud/settings_ui.py`），盒子侧有一个测试逐项比较。

盒子设置页的分类用地址里的 `#…` 和 CSS `:target` 切换，不依赖脚本。界面上的取舍见 `docs/UI-1.5.0.md`。

## 5. 存储布局

| 路径 | 内容 | 介质 |
|---|---|---|
| `/opt/autoplay/` | 程序（`supervisor_openwrt.py` 等、`playport/lib`、`playport/web/dist`）、`autoplay` 包解开的程序包；postinst 把 `/opt/dashplay/{state,identity}` 搬过来 | SD 卡根分区（只读根是长期目标） |
| `/opt/autoplay-bluez/` | 私有 BlueZ 根（装机脚本的 `autoplay` 阶段安装；postinst 从旧路径迁移） | SD 卡 |
| `/opt/autoplay/identity/offline-mfi/` | **用户自备**的 `identity.pk8` + `certificate.p7b`，不进仓库、不进镜像；出厂重置时要二次确认才删 | SD 卡，root 可读 |
| `/opt/autoplay/state/` | 配对（`pairings.properties` + `.bak`）、蓝牙密钥、TLS 证书库、`config.json`、`phone-ios.properties`、AppCDS、升级日志和包缓存、时钟下限、`diag/`、日志镜像（5MB 尾部，每 60 秒）、`measure/`（测量服务） | SD 卡；每个写入都 fsync + rename |
| `/var/run/autoplay/` | `status.json`、`receiver.log`、日志环、`measure.csv`、`session` | tmpfs（`harden.sh` 单独挂 64MB） |
| `/etc/config/autoplay` | 11 个 uci 键：`enabled, viewer_port, idle_release, dns_provider, duckdns_domain, duckdns_token, own_domain, dnspod_id, dnspod_token, update_check, update_mirror`（1.1.0–1.2.0 的 `audio_route_navigation` 升级时删除） | SD 卡 |
| `/etc/autoplay/` | `harden.sh` 的配置、回退记录和戳记；`measure.conf` | SD 卡 |

常量（不是配置）：LAN 100.96.0.1/24（uci-defaults `90-autoplay-tesla` 安装时写一次）、设置页 18080、联网检测常驻应答、音乐/导航播报/通话/Siri 全部走车载蓝牙（1.3.0 起没有开关）、第一个 5 GHz 热点交给 iPhone、名字 = 自己的域名（DuckDNS 或 DNSPod）或 `autoplay.lan`。

## 6. 这份架构里还没有验证的假设（截至 1.5.0）

已验证（2026-11-02，1.0.0）：WebCodecs → canvas 的画面、触摸回传、蓝牙 iAP2 引导、Let's Encrypt 证书在特斯拉浏览器里无警告、热点只在 149–165 信道可见。仍未验证：

- 特斯拉**行驶中** canvas 不受 `<video>` 限制的波及（停车状态已看到画面；多个项目报告行车可用，无官方说明）。
- 特斯拉浏览器的真实 Chromium 版本、UA、DPR、两种窗口形状的精确尺寸（探测页还没在车上跑，`docs/TESLA.md` §7）。
- 画布不再持有焦点之后，浏览器被拉回时车机键盘是否还会出现（1.3.0，台架上无法复现）。
- 车辆定位（1.4.0）：行驶中浏览器多久给一个新位置、导航时会不会冻住（冻住时盒子停发，iPhone 用自己的）。坐标系有了一次实测（2026-11-10，国行 2022 款 Model 3、AMD 车机：GCJ-02），1.5.0 起默认「自动」（ADR-19）；别的车型、固件是否相同未知，不同时手动选。
- 1.5.0 的日间/夜间配色和两张页面之间的往返（§4.3）在特斯拉浏览器里的表现：只在台式机的 Chromium 里按车机的窗口尺寸核对过；用到的 `sessionStorage`、`history.replaceState`、CSS `:target` 都是常规特性。
- mu300-linux 系统更新后经 `mu300-user-packages keep` 装回 AutoPlay（1.5.0）：只对真实的发布用替身工具跑通，没有在真机上跑过（`docs/RELEASE.md`）。
- HTTP 页面下主线程 `MediaStreamTrackProcessor` 是否可用（决定 C′ 档是否值得做，进而决定证书方案能否省掉）。
- 方向盘按键是否交给网页（车载蓝牙模式下不需要）。
- CPU0 深度睡眠、RPS、限频对延迟和温度的实际影响——全部是别的板子或推算的数字。

探测页（`tools/probe/`）和测量服务（`tools/f50/measure.sh`）就是为了把这些变成数据。
