# 声音走向：哪些走蓝牙，哪些不走

一句话：**不是所有声音都走蓝牙。** 音乐、通话、Siri 走 iPhone 和特斯拉之间的蓝牙，F50 不经手；导航播报和提示音走 Wi-Fi 到 F50，再由车机浏览器播出来；F50 自己的蓝牙只传控制信令，不传任何声音。

## 一、四条路径

| 声音 | 路径 | 由什么决定 | 代码位置 |
|---|---|---|---|
| **音乐 / 播客 / 媒体** | iPhone → 特斯拉蓝牙 **A2DP** → 车扬声器。F50 和网页不参与；切歌、音量、媒体卡片都是车的原生功能（AVRCP） | iPhone 的输出选择：iPhone 同时连着特斯拉蓝牙，并在车机上把这部 iPhone 选为媒体来源、在 iPhone 的播放输出里选车的蓝牙（iOS 会记住）。接收端**仍然声明**支持 media 输出（100 号流 PCM、102 号流 AAC-LC），所以 iPhone 想发到网页时也发得过来——Siri 结束后约 27 秒就是这种情况 | `receiver/protocol/.../AirPlayInfoPlist.kt` `audioFormats()`；网页 `audio.ts`（`idleClose`：播完就关掉音频输出，否则特斯拉把开着音频输出的浏览器当成媒体源，在它和 iPhone 蓝牙之间来回切，DashPlay 2026-10-14 实车观察） |
| **通话 / Siri / 麦克风** | iPhone ↔ 特斯拉蓝牙 **HFP** ↔ 车的麦克风和扬声器 | **确定性的**：接收端的 `audioFormats()` 不声明 `telephony` 和 `speechRecognition` 两种音频类型、不声明任何输入格式，iPhone 只能把这三样留在车的蓝牙上。0.1.0 已删掉网页麦克风上行（`mic.ts`、`MicUplink.kt`，TRIM-LOG D3） | `AirPlayInfoPlist.kt` `audioFormats()` 的注释和列表 |
| **导航播报 / 提示音 / 警报** | iPhone → AirPlay（Wi-Fi，101 号"替代音频"流和 100 号流的 default/alert 类型，PCM 或 Opus）→ F50 接收端 → WebSocket → 车机浏览器 Web Audio → 车扬声器 | CarPlay 协议：iPhone 把播报发给 CarPlay 主机，没有"改走蓝牙"的开关。所以网页必须能出声：浏览器自动播放策略要求**先轻点一次页面**解锁；播报经 `promptBoost = 3` 的限幅放大（蓝牙音乐音量是车控的，播报音量是网页里的滑杆） | `audio.ts`（`promptBoost`、`streamGainValue`）、`i18n.ts` `sound` 键、`flags.ts` `PROMPT_BOOST` |
| **iAP2 控制** | iPhone ↔ F50 蓝牙 **RFCOMM**（配对引导、Wi-Fi 凭证交接、会话保持、位置/车辆状态消息） | F50 的私有 BlueZ 只开 iAP2 的 RFCOMM 通道；没有 A2DP/HFP 配置文件，**不传声音** | `box/linux/bt-bridge/`、`receiver/.../transport/Iap2*` |

## 二、对使用的影响

- **上车必须两件事**：车机蓝牙连 iPhone 并选为媒体来源（音乐/通话），以及打开 AutoPlay 页面后轻点一次（播报）。少了前者音乐会从网页出来（有声音，但缓冲延迟明显、特斯拉媒体卡片会来回跳）；少了后者导航没声音。
- **duck（压低音乐）**：导航播报时 iPhone 发 `duckAudio`，接收端转给网页压低*网页里*的媒体增益。音乐走蓝牙时这条基本不起作用，播报期间音乐是否变小由 iPhone 自己决定。
- **延迟**：播报经 Wi-Fi + WebSocket + Web Audio，比画面略慢是正常的；音乐经蓝牙，和画面之间可能有几百毫秒不同步（例如音乐 App 的进度条），这是分路的代价，不是 bug。
- **页面关掉或没解锁 = 没有播报**，但音乐和通话不受影响。
- **MSE 音乐路径**（`MUSIC_ELEMENT`，默认开）只在 iPhone 真把音乐发到网页时用到；它冻结不删（ADR-5），是否可以去掉要看实车里 102 号流到底出现多久、多频繁——`stats` 消息里有各流的字节数可以回答。

## 三、还没有实车答案的

- iOS 27.2 下 Siri 结束后那约 27 秒的 102 号流还在不在、多长。
- 来电铃声走哪边（协议上属于 telephony，应在蓝牙；未记录）。
- 播报和画面的相对延迟数值（`tools/car/touch-latency.md` 的相机法同样可用于声音）。

把这些结果记到 `docs/TESLA.md` §4。
