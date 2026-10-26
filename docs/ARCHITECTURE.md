# 架构

本文描述 0.1.0 里程碑的实际形态（上游快照）和已经定下来的目标形态；两者不同的地方标出来。依据：《F50 车机浏览器 CarPlay 技术路径》§三、《硬件视角审查》§2.3、§四、《界面审查》§五、审计笔记 `viewer_ui_audit.md` §12。

## 1. 拓扑

```
 iPhone
  ├─① 蓝牙 iAP2：配对、MFi 认证、交出热点名/密码/信道 ─────────▶ F50 (hci0, 私有 BlueZ)
  ├─② 5 GHz Wi-Fi (ch149, WPA2)：AirPlay RTSP:7000、H.264 视频流、RTP 音频 ─▶ F50 (wlan0, 100.96.0.1)
  │     ◀──────────────── HID 触摸、iAP2 控制隧道 ──────────────────── F50
  └─④ 特斯拉蓝牙：音乐、通话、Siri、方向盘按键（原生） ─────────────▶ 车机

 F50（OpenWrt 25.12 / mu300-linux，5.4 内核；热点 100.96.0.1/24；5G SIM 给车机上网和证书续期）
  └─③ HTTPS/WSS :18443：H.264 原样转发（二进制帧）、导航播报音频、状态 ──▶ 车机浏览器（WebCodecs → canvas）
        ◀──────────── WSS 文本帧：触摸、按键、显示设置 ───────────────── 车机浏览器
```

拓扑是硬件定死的（技术路径 §一第 2 条）：SC2355 同一时间只能开一个 Wi-Fi 接口，所以 F50 只能当热点，车机和 iPhone 都连它；F50 不能同时连别的热点。F50 没有 USB 主机，有线 CarPlay 不可能。

地址：局域网 100.96.0.1/24（CGNAT 段；特斯拉浏览器拒绝 192.168/10/172.16，用域名也不行）。车机打开的地址是 `https://<duckdns 名>:18443/`，由盒子上的 dnsmasq 以 `address=/<名>/100.96.0.1` 本地应答（OpenWrt 的 DNS 重绑定保护会丢弃上游返回的 100.64/10 地址，所以必须本地应答）。

## 2. 进程与端口（0.1.0 现状 = DashPlay 的形态）

```
procd
 └─ /etc/init.d/dashplay (S99)  →  python3 supervisor_openwrt.py        守护；设置页 :18080；诊断；升级检查；特斯拉模式；DuckDNS
      ├─ python3 board_zte_f50.py                                        F50 蓝牙：dbus-daemon(私有总线) + btattach(/dev/ttyBT0) + bluetoothd(私有 BlueZ)
      ├─ python3 run-receiver.py  →  java (Temurin 21, -Xmx384m, AppCDS)   PlayPort 接收端
      │     ├─ mDNS _airplay._tcp                                        iPhone 发现
      │     ├─ :7000  AirPlay RTSP（配对、/info、SETUP）+ 视频 TCP 流 + 音频 UDP  ← iPhone
      │     ├─ :18443 HTTPS 静态页 + WSS /ws + JSON API（显示设置等）      ← 车机浏览器
      │     ├─ bt-bridge（python3, dbus-next）                             每次邀请 iPhone 时起一个，走 iAP2 RFCOMM
      │     └─ phone-presence.py                                         无会话时每 2 秒 fork 一次做 ARP 探测（硬件审查 H5 要去掉）
      └─ logread -f（特斯拉模式）                                          看 dnsmasq 查询，应答车机的联网检测
 mu300 底座：hostapd、dnsmasq(:53/:67)、netifd、uhttpd(LuCI :80)、mobile-data、thermal-guard、mu300-cpu、mu300-power…
 AutoPlay 新增：/etc/init.d/autoplay-tune (S98)、/etc/init.d/autoplay-measure (S99)   见 tools/f50/
```

| 端口 | 协议 | 谁用 | 备注 |
|---|---|---|---|
| 7000/tcp | AirPlay RTSP + 事件 | iPhone → F50 | 视频流和 HID 事件在 RTSP 协商出的连接上 |
| 动态 udp | RTP 音频、RTCP | iPhone → F50 | |
| 5353/udp | mDNS | iPhone ↔ F50 | 热点必须放行组播，不开客户端隔离 |
| 18443/tcp | HTTPS + WSS | 车机 → F50 | 投屏页、`/ws`、`/api/display`、`receiver-access.json`（仅本页令牌）；上游 10.23 起端口可配（`viewer_port`） |
| 18080/tcp | HTTP | 手机 → F50 | 设置页（添加 iPhone、证书、诊断）；明文、无认证（见 SECURITY） |
| 80/tcp | HTTP | 手机 → F50 | LuCI；特斯拉模式下 80 端口还做联网检测的应答和跳转 |
| 53/67 | DNS/DHCP | 车机、iPhone | dnsmasq；`address=` 把域名指到 100.96.0.1 |

目标形态（硬件审查 §四路线 B，WP2）：一个静态链接的守护进程 `autoplayd` 接管全部 Python 的职责（守护、蓝牙拉起、iAP2 桥、在线探测、状态通道、设置 API、升级、特斯拉/DuckDNS），JVM 保留为协议引擎；再以协议对等验证为门槛评估 Rust 原生引擎（`engine=jvm|native`）。端口收敛为 18443（投屏页 + API）、一个常驻状态页、LuCI 80。

## 3. 数据流（一帧视频）

```
iPhone 编码 H.264 ─TCP─▶ JVM airplay-screen 线程：读 128B 头 + 包体 → ChaCha20-Poly1305 解密 → 长度前缀改 Annex B
   → Wire.videoFrame（11B 头 + NALU）→ 每个页面一个队列（LagGate：落后 >~300ms 就丢帧，等关键帧）
   → Ktor WebSocket 二进制帧 → Netty TLS → wlan0 ─▶ 浏览器 ws.ts → protocol.ts 解包 → video.ts：VideoDecoder.decode
   → VideoFrame → canvas 2d（alpha:false, desynchronized）→ 车机屏幕
触摸：pointer 事件 → 按画面归一化坐标 → WSS 文本 JSON → JVM → HID 报文 → ChaCha 加密 → iPhone 事件连接
音频（特斯拉模式）：只有 100/101 号流（导航播报、提醒）经 WSS 到页面，AudioDecoder/Web Audio 播放并放大 3 倍；
   音乐、通话、Siri 不经过 F50（iPhone 直接走特斯拉蓝牙）
```

F50 不解码、不转码，只解密、重封装、再加密。每帧在 JVM 里约 8 次内存拷贝、2 次加解密（硬件审查 H4）；所有网络中断落在 CPU0（H3）。这两条决定了 `tools/f50/harden.sh` 里 RPS、CPU0 空闲状态和 A76 限频的取舍。

## 4. 页面与设置页共用的状态模型

现状：投屏页只有 waiting / starting / live / reconnecting / error 五种显示状态，设置页靠横幅拼凑；蓝牙、认证、过热、升级中、被占用、重协商这些状态要么没有、要么显示成别的东西（界面审查 §一）。这是两套界面问题的共同根因，所以先定状态模型，再改界面。

### 4.1 投屏页状态（`viewer_ui_audit.md` §12）

| 状态 | 触发 | 显示 | 驾驶者能做什么 |
|---|---|---|---|
| `checking` | 页面启动 | 黑底 + 小字眉标 | — |
| `unsupported` | 浏览器检测失败 | 大字标题 + 白话说缺什么（"缺少 H.264 视频解码"）+ 按车型建议 + 折叠的技术详情 | 看详情 |
| `needs-access` | 没有令牌 | "在车机打开 https://<盒子>/ 一次" + 盒子地址 | — |
| `connecting-box` | 首次 `connecting` | 转圈 + "正在连接盒子…" + 3 秒后显示已等待秒数 | 刷新 |
| `box-unreachable` | `closed` 且无画面 >3 秒 | "盒子没有响应" + 清单（通电、热点）+ 已等待 + 次数 | 刷新、盒子网页 |
| `waiting-iphone` | `hello/session sessionActive:false` | 大状态图标 + "等待 iPhone" + 一句话原因（蓝牙未就绪 / 认证失败 / 正常等待） | 添加 iPhone、设置 |
| `starting` | `sessionActive:true`、首帧前 | "iPhone 已连接，正在接收画面…" | — |
| `renegotiating` | 显示设置变更 / 自动适配 | 上一帧调暗 + "正在按新窗口重新连接 CarPlay（约 5 秒）" | — |
| `live` | 首帧解码 | 画面；非全屏时一条细状态栏（状态点、夜间标记、声音关标记） | CarPlay |
| `live-muted` | 已有画面且声音未解锁 | 底部整宽提示条"轻点任意位置开启声音（导航播报、Siri）" | 轻点 |
| `recovering` | 链路断开（`reset(hold)` / `wake`） | 保留画面 + 40% 遮罩 + 居中常驻"连接中断 · 正在重连 · 触控已暂停"，无超时 | 等待，8 秒后可刷新 |
| `paused-by-box` | LagGate 关闸 | 状态栏小标签"画面暂停（车机变慢）" | — |
| `busy` | 另一个页面在用（需服务端新消息） | "另一块屏幕正在显示 CarPlay" + 接管 | 接管 |
| `box-restarting` | 等盒子应答的轮询 | "盒子正在重启/更新，页面将自动刷新" + 已等待 | — |
| `overheating` | 状态通道 thermal | "盒子过热，已降低画质 / 已暂停" | — |
| `error` | `{title, action, detail}` | 标题 + 动作 ≥22px，64px 按钮，详情折叠 | 重试 / 关闭 |
| `night`（修饰） | 夜间模式 | 界面变暗、隐藏二维码、可选画面遮罩 | 设置里切换 |

实现上只需要把 `render()` 里的 `state` 变成带 `reason`/`since` 的枚举、`hint` 由状态派生，加两条服务端消息（`busy`、`restarting`）。`mic-blocked` 在特斯拉专属形态下不存在（不提供麦克风）。

### 4.2 盒子状态通道（STATUS-MODEL）

设置页、LuCI 概览和投屏页读同一份状态，而不是各自拼。约定一个 JSON（计划放在 `/var/run/autoplay/status.json`，由守护进程原子写、由 18443 的 API 和设置页转发），每个条目三元组：

```
{ "<component>": { "state": "<code>", "reason": "<code 或空>", "since": <epoch 秒> }, ... }
component: bluetooth | wifi | uplink | identity | phone | certificate | update | system | tesla | thermal
state 例子：bluetooth = off|starting|on|failed；identity = missing|ok|rejected；certificate = ok|expiring_soon|expired|renewing|failed；
          thermal = ok|warm|hot|released；update = idle|available|installing|failed；phone = none|inviting|connected|busy
```

规则：每个状态对应一句现状 + 一句动作的文案（zh/en 都有），`since` 用来判断陈旧（例如"网络已切换，请重连"不能永远挂着，界面审查 S8）；状态色只做辅助，永远配文字；不出现端口、uci 键、文件路径、API 名称，这些收进"详细信息"。投屏页的 `waiting-iphone` 原因、`overheating`、`box-restarting` 直接由这里的 `bluetooth`、`identity`、`thermal`、`update` 派生。

这个通道在 0.1.0 里还不存在；它是 WP2（守护进程输出健康状态）、WP3（证书状态）、WP4（温度）和界面第 2 批的共同前置。`tools/f50/harden.sh` 装的 `autoplay-tune` 已经按同一个目录约定使用 `/var/run/autoplay/session` 作为会话标志。

## 5. 存储布局（目标）

| 路径 | 内容 | 介质 |
|---|---|---|
| `/opt/autoplay/`（现为 `/opt/dashplay/`） | 程序、JRE、私有 BlueZ | SD 卡根分区，只读为目标 |
| `/opt/autoplay/identity/offline-mfi/` | **用户自备**的身份文件，不进仓库、不进镜像 | SD 卡 |
| `/opt/autoplay/state/` | 配对、蓝牙密钥、TLS 证书库、`config.json`、AppCDS、`measure/` | SD 卡；每个写入都 fsync + rename |
| `/var/run/autoplay/` | 日志环、`measure.csv`、`session`、`status.json` | 64MB tmpfs（harden.sh） |
| `/etc/config/*`、`/etc/autoplay/` | uci 配置、加固脚本的配置和回退记录 | SD 卡 |

目标是把 uci 键从 22 个减到 7 个（`enabled, viewer_port, idle_release, duckdns_domain, duckdns_token, update_check, update_mirror`），其余写成常量（特斯拉专属补充 §五）。

## 6. 这份架构里还没有验证的假设

- 特斯拉行车时 canvas 不受 `<video>` 限制的波及（多个项目报告，无官方说明）。
- 特斯拉浏览器的真实 Chromium 版本、UA、DPR、两种窗口形状的尺寸。
- HTTP 页面下主线程 `MediaStreamTrackProcessor` 是否可用（决定 C′ 档是否值得做，进而决定证书方案能否省掉）。
- 方向盘按键是否交给网页（车载蓝牙模式下不需要）。
- CPU0 深度睡眠、RPS、限频对延迟和温度的实际影响——全部是别的板子或推算的数字。

探测页（`tools/probe/`）和测量服务（`tools/f50/measure.sh`）就是为了把这些变成数据。
