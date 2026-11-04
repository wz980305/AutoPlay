# AutoPlay 1.3.0 界面迭代：设置面板按 iOS「设置」的样子收口；删掉网页里的声音

日期：2026-11-05。承接 1.2.0（`docs/UI-1.2.0.md`）：那一轮把两张页面做到了车机窗口的比例，这一轮按车主上车一周后的清单做减法，并把设置面板的逻辑和外观向 iOS 系统「设置」对齐——每行一个彩色圆角图标、标签、右侧灰色当前值、尖角；分组标题在上、说明在下；没有和当前状态无关的话。同时修一个实车问题：浏览器被拉回 CarPlay 页面时有时弹出屏幕键盘。

## 一、清单与处理

**投屏页设置面板（`https://…:18443/`）**

| 车主的点 | 处理 |
|---|---|
| 浏览器被拉起时有时弹出屏幕键盘 | 画布不再可聚焦、不再在每次按下时 `focus()`；页面重新可见时 `blur()` 掉浏览器恢复的焦点；`interactive-widget=overlays-content`。ADR-17，§三 |
| 常用页删掉「声音」分组和「所有声音都走特斯拉蓝牙」卡片；另一套音频路径的代码整个删掉 | 删了（ADR-16，`docs/AUDIO.md`）。带来的问题写在 §四 |
| 每行都要像蓝牙卡片那样有图标 | 夜间模式（靛蓝·月亮）、语言（蓝·地球）、CarPlay 内容大小（蓝·AA）、帧率（橙·仪表）、无边框模式（蓝·展开）、画质与兼容（灰·扳手）、视频编码（紫·胶片）、性能模式（红·闪电）、允许 2560（青·四格）、兼容显示（灰·盾）、显示调试信息（深灰·终端）、打开盒子网页（绿·盒子）、连接与兼容性（蓝·脉冲）；左侧三个分类也各有图标，选中项用蓝色填充（iPad 设置侧栏的做法） |
| 删掉「当前请求：夜间」和页脚「本页语言与音量保存在此浏览器…」 | 删了。「定时」的时间段进了选项名本身（「定时 18:30–06:30」），不再有脚注 |
| 显示页：删掉「改变 iPhone 输出的 CarPlay 文字与图标大小…」、「1920 × 998 / 30 fps / H.265」状态行、「高分辨率、编码与调试」副标题、「分辨率随窗口自动调整…」脚注 | 都删了。按钮下那一行只在「正在应用 / 已保存 / 下次连接生效 / 失败」时出现，平时为空；分辨率、帧率、编码仍在调试浮层和「连接与兼容性」里 |
| 连接页：删掉「将离开当前画面…」副标题和整个「备用控制」 | 删了（主屏幕 / 返回 / 刷新画面三个按钮连同 `knob` 消息的发送代码；触控失灵时的退路是刷新页面） |
| 右侧各行下面的小字是不是都不必要（追问） | 是。设置面板里不再有任何行内说明：无边框模式、视频编码、性能模式、允许 2560、兼容显示、显示调试信息的小字全部删除；iOS 的行只有图标、标签、当前值。标签不再折行，当前值过长时截断加省略号（iOS 的做法）。等待画面的三行保留它们的提示（那是首次使用的引导，不是设置） |

**盒子设置页（`http://…:18080/`）**

| 车主的点 | 处理 |
|---|---|
| 删掉「上游在线；特斯拉自带音乐、地图可以上网。」 | 上游在线和开机头几秒的"检测中"都不再提示；只有上游不可用时才有一条横幅（证书不能续签、车机不会留在热点上，这才是要知道的） |
| 删掉「声音」分组的「导航播报」格 | 删了，随音频路径一起 |

## 二、设置面板现在的样子

- **常用**：外观（夜间模式、语言）。
- **显示**：画质（CarPlay 内容大小、帧率、「应用并重连」）；无边框模式；画质与兼容（视频编码、性能模式、允许 2560 分辨率、兼容显示、显示调试信息）。
- **连接**：打开盒子网页；连接与兼容性（解码能力、当前画面 `宽 × 高 / fps / 编码 / 解码延迟`、浏览器兼容性检测）。

去掉的字串：`sound`、`volume`、`volumeHint`、`soundTitle`、`soundOnCar`、`soundOnCarHint`、`privacy`、`playing`、`paused`、`musicDropped`、`voiceSiri`、`voiceCall`、`voicePrompt`、`nightNow`、`nightOn`、`nightOff`、`browserDark`、`browserLight`、`nightScheduleHint`、`savedHere`、`uiHint`、`advancedHint`、`autoHint`、`boxLinkHintLive`、`fallback`、`fallbackHint`、`home`、`back`、`refresh`、`codecHint`、`performanceModeHint`、`allow2560Hint`、`compatDisplayHint`、`debugHudHint`、`management`、`display`。改了的：`unsupported`（不再提音频）、`noStream`（"尚无画面"）、`frameSettings`（「画质」）、`nightSchedule`（「定时 18:30–06:30」/ "18:30–06:30"）、`ui` 的英文（"Content size"："CarPlay content size" 在 773 px 窗口里把当前值挤成了省略号）、`nextSession` 成句。`fullscreenRowHint` 等三句只剩等待画面在用。

## 三、键盘：改了什么、为什么

页面里没有文本输入框；能拿到焦点的只有按钮、开关和画布。画布的 `tabindex="0"` 和每次按下时的 `this.surface.focus()` 从上游继承，为的是键盘方向键——但方向键的监听一直在 `window` 上，不需要焦点。车机的屏幕键盘跟着浏览器的焦点元素走，浏览器把页面从后台恢复时会把焦点还给上次的元素；这是页面里唯一能解释"有时弹键盘"的机制，台架上无法复现车机的键盘。所以：

1. `index.html` 的画布去掉 `tabindex`；`input.ts` 去掉 `focus()`（`check.mjs`、`check-runtime.mjs` 现在断言控制器绝不调用 `surface.focus`）。
2. `main.ts` `dropStrayFocus()`：`pageshow`、窗口 `focus`、`visibilitychange` 变为可见时，若没有本页的 `<dialog>` 打开，就 `blur()` 当前焦点元素。
3. `<meta name="viewport">` 加 `interactive-widget=overlays-content`，并在支持的浏览器上设 `navigator.virtualKeyboard.overlaysContent = true`：万一键盘还是出现，不改变页面尺寸（尺寸一变 `ResizeObserver` 就会按新窗口重协商 CarPlay）。

## 四、删掉音频路径带来的问题

1. **没有退路。** 某辆车经蓝牙听不到导航播报时，没有开关可切；只能从 `v1.2.0` 取回 `audio.ts`、`audio-timing.ts`、解锁条和 uci 键。做这个决定的依据是车主已在车上确认走蓝牙可用。
2. **接收端要重新编译。** `ServerConfig.kt`、`CarPlayServer.kt`、`AudioCapabilitiesTest.kt` 的改动没有 Gradle 网络，列入 `receiver/docs/UNVERIFIED-KOTLIN.md`；在那之前盒子跑的是更早编译的接收端，所以 `run-receiver.py` 仍传 `--car-voice --audio-route-navigation bluetooth`（1.3.0 的接收端接受并忽略）。
3. **升级的盒子配置里会留下一个旧键** `audio_route_navigation`，安装脚本和守护进程启动时删掉它；LuCI 的「iPhone」页少一个下拉。
4. 调试浮层少了声音一行；`stats` 里少了 `musicKbps`、`promptGain`、`pageAudio`、`carMusic`、duck 计数；`?promptgain=` 不再有作用。
5. 浏览器检测不再要求 Web Audio、不再报告 AudioDecoder：一台没有这两样的车机浏览器现在能通过检测（它本来也不需要）。

## 五、怎么复现

```sh
cd receiver/web && npm run build:offline && npm test
python3 ../../box/tools/render_settings_states.py out/box-states
CHROME=/path/to/chromium node scripts/ui-shots.mjs out/ui-1.3.0        # 投屏页 4 形状 × 12 张（带边框窗口另有 5 张英文），盒子页 5 形状 × 8 状态
cd ../../box && python3 -m unittest discover -s tests/onecloud           # 238
```

截图在 `UI审查截图/1.3.0/`（随交付资料），台式机上量到的数字：773 × 601 下主标签 24 px、当前值 24 px、行高 72 px，无横向溢出。改动经另一个没看过修改过程的 agent 审查过一遍（它找出的英文标签截断、空状态行下的多余分隔线、两条死 CSS 规则已修）。

## 六、要在车上确认的

1. 从后台拉回浏览器十次左右，键盘是否还会出现；若仍出现，看 `stats` 的 `ev 2`（页面可见）后面有没有 `ev 5`（窗口尺寸变化）——有则键盘改变了页面尺寸，没有则是车机自己的键盘不随焦点走，要另找原因。
2. 设置面板三页在 773 × 601 和无边框下，图标、当前值、尖角是否对齐；「画质与兼容」展开后是否滚入可视区。
3. 盒子页顶部不再有绿色横幅；拔掉 SIM 后应出现"上游不可用"的黄色横幅。
