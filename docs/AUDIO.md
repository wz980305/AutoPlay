# 声音走向：默认全部走特斯拉蓝牙，网页可选播导航

自 1.1.0 起（ADR-14）：**默认 `audio_route_navigation = bluetooth`——盒子不向 iPhone 提供任何 CarPlay 音频，音乐、导航播报、提示音、通话、Siri 全部由 iPhone 经它和特斯拉之间的蓝牙播出，CarPlay 网页只管画面和触摸、没有声音。** 备选 `carplay`：网页播放导航播报和提示音（1.0.x 的做法），其余仍走蓝牙；经蓝牙听不到播报时用它。LuCI「服务 → AutoPlay → iPhone → 导航播报」切换，或：

```sh
uci set autoplay.main.audio_route_navigation=carplay   # 或 bluetooth
uci commit autoplay && /etc/init.d/autoplay restart
```

## 一、两种模式下各路声音怎么走

| 声音 | `bluetooth`（默认） | `carplay` |
|---|---|---|
| 音乐 / 播客 | iPhone → 特斯拉蓝牙 A2DP → 车扬声器；切歌、音量、媒体卡片是车的原生功能（AVRCP） | 同左。iPhone 偶尔仍把音乐发到网页（Siri 之后约 27 秒）：**网页丢弃它并提示一次**，不播放（见 §二） |
| 导航播报 / 提示音 | iPhone 自己混进 A2DP（和不用 CarPlay、只连车机蓝牙导航时一样） | iPhone → AirPlay（Wi-Fi，101 号流和 100 号流的 default/alert 类型）→ F50 → WebSocket → 车机浏览器 Web Audio → 车扬声器；上车后要**轻点页面一次**解锁声音，播报经 3 倍限幅放大，音量在页面滑杆 |
| 通话 / Siri / 麦克风 | iPhone ↔ 特斯拉蓝牙 HFP | 同左（两种模式下接收端都不声明 telephony/speechRecognition 和任何输入格式） |
| F50 自己的蓝牙 | 只传 iAP2 控制信令（配对引导、Wi-Fi 凭证交接、会话），不传声音 | 同左 |

协议上两种模式的区别只有一处：`/info` 里有没有 `audioFormats`/`audioLatencies` 和 features 的音频位（`AirPlayConfig.disableAudioOutput`）。`bluetooth` 模式下 iPhone 不建立任何音频流（上游 2026-10-31 在实机上看到的 "no audio SETUP"），于是按它不在 CarPlay 时的规则把所有声音路由到已连接的蓝牙设备——也就是特斯拉。

## 二、为什么网页永远不播音乐（两种模式都如此）

DashPlay 2026-11-01 在行驶中的特斯拉上发现：网页一旦通过媒体元素播放音乐，车机弹出"行车中视频只有声音"的横幅，横幅改变页面尺寸，CarPlay 随之每约 10 秒重协商一次。AutoPlay 1.1.0 起 `AudioEngine` 对 audioType 为 `media` 的流（102 号 AAC、100 号 "media" PCM）不建立任何状态、丢弃数据、记入统计（`musicDropped`），并提示驾驶者一次"请在 iPhone 控制中心把音频输出选为特斯拉"。0.1.0 冻结的 MSE 音乐路径（`music-output.ts`、`aac-mp4.ts`、`MUSIC_ELEMENT`）随之删除，ADR-5 的冻结项到此结束。

## 三、对使用的影响

- **上车要做的事**（`bluetooth` 模式）：车机蓝牙连 iPhone 并把它选为媒体来源；打开 AutoPlay 页面。没有"轻点开启声音"这一步。iPhone 没连车机蓝牙时，所有声音会从 iPhone 自己的扬声器出来——这是 iOS 的默认路由，不是故障。
- **`carplay` 模式多一步**：打开页面后轻点一次，否则导航没声音；页面没开或没解锁只影响播报，音乐通话照常。
- **duck（播报时压低音乐）**：`bluetooth` 模式下由 iPhone 自己处理，和普通蓝牙车机一样；`carplay` 模式下 iPhone 发来的 `duckAudio` 命令只计数，网页里已没有可压低的音乐。
- **延迟**：`bluetooth` 模式下播报经 A2DP，音乐没在放时 A2DP 要先把流打开，普通蓝牙车机常见的"第一个字被吃掉"可能出现；`carplay` 模式下播报经 Wi-Fi + Web Audio，和画面之间可能有几百毫秒不同步。

## 四、还没有实车答案的

1. `bluetooth` 模式下导航播报在行驶中是否稳定听到、第一个字有没有被吃；来电铃声和 Siri 是否照常。
2. 故意不连车机蓝牙时声音去了哪（预期：iPhone 扬声器）。
3. iOS 27.2 下 Siri 结束后那约 27 秒的 102 号音乐流是否还出现（`stats` 里的 `musicDropped` 会说）。

把结果记到 `docs/TESLA.md` §7。

## 五、代码位置

- 接收端：`ServerConfig.audioRouteNavigation` / `audioOverBluetooth`，`CarPlayServer.airPlayConfig`（`disableAudioOutput`），`AirPlayInfoPlist.build`；测试 `AudioCapabilitiesTest`。
- 盒子：`supervisor_openwrt.audio_route_of()` → `run-receiver.py --audio-route-navigation` → JVM 参数 + `receiver-access.json` 的 `audioRouteNavigation`；设置页「声音」格；LuCI `audio_route_navigation`。
- 网页：`boot.ts` → `playportPageAudio`；`main.ts` 隐藏解锁条/音量、不打开音频输出；`audio.ts` 丢弃 media 流；`flags.ts PAGE_PLAYS_MUSIC`。
