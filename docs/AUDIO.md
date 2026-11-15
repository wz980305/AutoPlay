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

## 六、用过车机自带的媒体后，CarPlay 里播放没有声音（2026-11-16 审查）

车主报告：在 CarPlay 里放 Apple Music、暂停；在车机自带的 Apple Music 里放、暂停；回到 CarPlay 再放，有时没有声音。问这是否说明声音这一块还有问题，并要求全面审查。

**结论：盒子和页面的代码里没有找到问题；声音断在特斯拉的媒体来源上。** 这是「声音全部走特斯拉蓝牙」这个设计本来就有的前提（第三节：iPhone 要被选为车机的媒体来源），车机自带的媒体一播放，这个前提就被换掉了。

| 步骤 | iPhone | 特斯拉 | 盒子和页面 |
|---|---|---|---|
| 1. 在 CarPlay 里播放 | 声音经蓝牙发给特斯拉 | 媒体来源是「手机」（蓝牙），出声 | 只传画面和触摸，不经手声音 |
| 2. 在车机自带的 Apple Music 里播放 | 已暂停 | 媒体来源换成自带的 Apple Music | 页面在后台，CarPlay 会话保持（十几分钟不回来才断开） |
| 3. 回到 CarPlay 再播放 | 照常经蓝牙发声音 | 来源仍是自带的 Apple Music（暂停着）：有时自己切回「手机」，有时不切，不切就没有声音 | 和第 1 步一样 |

依据：

- 特斯拉的用户手册把手机（蓝牙）列为在媒体播放器里选的一个来源，没有说手机一播放车就自动切过去。
- 特斯拉车主论坛上有同样的现象：选过别的来源（比如车机的 Spotify）之后，车不再自动切回蓝牙来源，手机的音乐和导航播报都没有声音，在菜单里手动选回蓝牙来源后恢复。「有时候」正是因为车有时会自己切、有时不会。
- 做同一件事的产品（在特斯拉浏览器里显示 CarPlay、声音走车机蓝牙的 Carlinkit T2C）的说明里也写着：不要让车机自带的应用和 CarPlay 同时播放，并在车机上选蓝牙作为声音来源。

**恢复办法：** 在车机的媒体播放器里把来源选回「手机」（蓝牙）。想听 Apple Music 时只在 CarPlay 里放，就不会遇到（两边是同一个账号、同一个资料库）。

**确认办法：** 没有声音时看车机的媒体栏：显示的是车机自带的 Apple Music（暂停着）而不是 iPhone 正在放的歌，就是这个原因；选回「手机」后声音回来即可确认。若来源已经是「手机」、iPhone 的音频输出也显示车机，仍然没有声音，那是另一回事：在「AutoPlay 设置」下载诊断记录再查。

**盒子为什么帮不上：** iPhone 的声音不经过盒子；盒子和页面既看不到、也改不了特斯拉的媒体来源，也不知道车机此刻有没有在出声。

审查过的地方（都没有发现会让 iPhone 不出声或把声音引到别处的行为）：

- 接收端告诉 iPhone 的能力（`AirPlayInfoPlist.build`）：没有 `audioFormats`/`audioLatencies`，功能位里没有音频位；`bluetoothIDs` 只有盒子自己的蓝牙地址，所以 CarPlay 期间 iPhone 只会停掉它和盒子之间的声音通道，和特斯拉之间的不动（`BluetoothIdentityTest`）。
- 屏幕和主音频的归属（`modes`）：盒子在会话开始时声明一次，约束全是「随时可以拿走」；之后从不向 iPhone 发改变归属的命令（代码里没有这条命令），所以重连前后 iPhone 都可以随时播放。新增 `AirPlayInfoPlistTest.theIphoneMayTakeMainAudioAtAnyTime` 固定这一点。
- 页面到后台再回来：页面的连接最多保留 10 分钟，其后没有页面满 5 分钟才结束 CarPlay 会话；这段时间盒子不向 iPhone 发任何和声音有关的东西。
- 盒子的蓝牙：只注册 iAP2 一个服务（`bridge.py`，`test_bluez`），不提供 A2DP、HFP，iPhone 不会把它当成能出声的设备。
- 页面：不播放任何声音，旧接收端可能转发的音频帧和压低音量的消息只解析、不处理。

接收端日志里和声音有关的只有两行：`CarPlay resource ownership`（iPhone 报告屏幕、主音频归属变化时）、`audio duckAudio/unduckAudio`（iPhone 要求压低或恢复音乐音量时）。到 1.6.6 为止诊断记录没有保留它们：车主随后给的 2026-11-15 行车记录里没有一行和声音有关，只能看出那段时间 CarPlay 一直连着（27 分半没有断过），页面五次离开屏幕（5 到 112 秒，应是去了车机别的应用），每次回来都在原来的连接上、约半秒后继续，盒子在这些时刻什么也没做。这和上面的结论一致，但不能单独证明它。1.6.7 起诊断记录保留这两行（`diagnostics.KEEP`），再遇到没有声音时，记录能说出 iPhone 当时有没有在播放。真车上的声音只能在车里验证，这次审查是读代码、跑测试和读这份记录，没有实车录音。
