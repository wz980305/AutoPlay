# 声音走向：全部走特斯拉蓝牙，网页无声

自 1.3.0 起（ADR-16）只有一种模式：**盒子不向 iPhone 提供任何 CarPlay 音频，音乐、导航播报、提示音、通话、Siri 全部由 iPhone 经它和特斯拉之间的蓝牙播出；CarPlay 网页只管画面和触摸，没有声音，也没有任何声音设置。** 1.1.0–1.2.0 的 `audio_route_navigation` 选项（备选 `carplay`：网页播导航播报）连同网页端的 Web Audio 代码一起删除；需要时在 git 历史的 `v1.2.0` 标签里。

## 一、各路声音怎么走

| 声音 | 走向 |
|---|---|
| 音乐 / 播客 | iPhone → 特斯拉蓝牙 A2DP → 车扬声器；切歌、音量、媒体卡片是车的原生功能（AVRCP） |
| 导航播报 / 提示音 | iPhone 自己混进 A2DP，和不用 CarPlay、只连车机蓝牙导航时一样 |
| 通话 / Siri / 麦克风 | iPhone ↔ 特斯拉蓝牙 HFP；接收端从不声明 telephony/speechRecognition 和任何输入格式 |
| F50 自己的蓝牙 | 只传 iAP2 控制信令（配对引导、Wi-Fi 凭证交接、会话），不传声音 |

协议上就一件事：接收端的 `/info` 里没有 `audioFormats`/`audioLatencies`，features 没有音频位（`AirPlayConfig.disableAudioOutput = true`，`CarPlayServer.airPlayConfig`）。iPhone 于是不建立任何音频流（上游 2026-10-31 在实机上看到的 "no audio SETUP"），按它不在 CarPlay 时的规则把所有声音路由到已连接的蓝牙设备——也就是特斯拉。

## 二、为什么删掉网页播导航的备选

- **实车已经确认走蓝牙可用**（车主确认，2026-11-05 记录）：音乐、导航播报、通话都从特斯拉蓝牙播出，没有再切回 `carplay` 的需要。
- 备选模式拖着一整套只在备选下才用的代码：`audio.ts`（340 行 Web Audio：解锁、PCM/AAC 解码、限幅放大、duck、丢弃音乐）、`audio-timing.ts`、解锁条、音量滑杆、「声音」分组、`?promptgain=`、调试浮层的声音行、接收端的 `--audio-route-navigation` 和 uci 键、LuCI 下拉、盒子页的「声音」格，以及三处测试。它们的失效模式（页面没解锁就没播报、Web Audio 和画面不同步、特斯拉对发声页面弹横幅）正是 1.1.0 想摆脱的。
- 浏览器检测随之不再要求 Web Audio / AudioDecoder：车机浏览器只需要 WebCodecs 视频解码。

## 三、对使用的影响

- **上车要做的事**：车机蓝牙连 iPhone 并把它选为媒体来源；打开 AutoPlay 页面。没有"轻点开启声音"这一步，页面里也没有音量。
- iPhone 没连车机蓝牙时，所有声音会从 iPhone 自己的扬声器出来——这是 iOS 的默认路由，不是故障。
- **duck（播报时压低音乐）** 由 iPhone 自己处理，和普通蓝牙车机一样；盒子转发来的 `duck` 消息页面直接忽略。
- **延迟**：播报经 A2DP，音乐没在放时 A2DP 要先把流打开，普通蓝牙车机常见的"第一个字被吃掉"可能出现。
- **没有退路**：若某辆车经蓝牙听不到导航播报，1.3.0 起没有开关可切，只能回到 `v1.2.0` 的代码（`git checkout v1.2.0 -- receiver/web/src/audio.ts …`）。做这个决定的依据是实车确认，见上。

## 四、兼容旧接收端

网页、盒子脚本和接收端一起发布，但接收端的 Kotlin 自 1.1.0 起没有在有网的机器上编译过（`receiver/docs/UNVERIFIED-KOTLIN.md`）。为了让盒子脚本装在一台跑着更早接收端（默认在网页播导航）的盒子上也保持全部走蓝牙，`run-receiver.py` 仍给 JVM 传 `--car-voice --audio-route-navigation bluetooth`；1.3.0 的接收端接受并忽略这两个参数。`receiver-access.json` 只剩 `token` 和 `settingsPort`。升级时安装脚本和守护进程会删掉旧配置里的 `audio_route_navigation` 键。

## 五、代码位置

- 接收端：`CarPlayServer.airPlayConfig`（`disableAudioOutput = true`），`AirPlayInfoPlist.build`；测试 `AudioCapabilitiesTest`（不声明音频；旧参数被忽略）。
- 盒子：`run-receiver.py`（JVM 参数、`receiver-access.json`）；`supervisor_openwrt.OBSOLETE_OPTIONS` 与 `90-autoplay-tesla` 删除旧键。
- 网页：`main.ts` 对 wire 类型 3/4/6（旧接收端可能仍转发的音频帧）只解析不处理；`debug-hud.ts` 两行；`public/browser-check.js` 不检查音频 API。
