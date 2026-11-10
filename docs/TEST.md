# 测试

分四层：台式机上能跑的单元测试和检查脚本；盒子上的台架测试；车上的验收清单；长期的浸泡。0.1.1 本轮完成的测试范围、计数和未通过项目详见 `AUDIT-0.1.1.md`；以下保留原台架/实车验收方案。

## 1. 台式机

### Python（标准库 unittest）

```sh
# 本仓库的工具
python3 -m unittest discover -s tools/f50
python3 -m unittest discover -s openwrt/tests      # 安装脚本 90-autoplay-tesla 对着假 uci（1.0.1）
# 接收端：1.3.1 起 GitHub Actions 对每次推送跑 ./gradlew build（编译两个模块并跑全部测试），见下文「接收端」

# 盒子侧：设置页、状态模型、守护（supervision）、升级日志与回滚、证书退避、时钟下限、出厂重置、平台、诊断、装机脚本
cd box && python3 -m unittest discover -s tests/onecloud        # 270 个（1.5.1：+1，两份样式表里决定标题栏位置的数值逐项相同；1.5.0：+13，盒子温度与过热提醒、处理器占用、系统更新保留、坐标系迁移、盒子网页的分类/日夜间/无小字、与设置面板的颜色逐项相同；Python 3.11–3.13 下都通过），通过

# 蓝牙桥：test_reason、test_relay 等 7 个可直接跑；test_bluez、test_recovery 需要 dbus-daemon 和 dbus-next 0.2.3
cd box && python3 -m unittest discover -s tests/bluetooth       # 没有 dbus-next 时那两个模块报 import 错误，是环境问题
```

测试身份全是合成数据。裁剪前后的基线在 `box/docs/TEST-BASELINE.md`（375 → 225 是删掉的 Debian/N1/有线/STA 测试减去新模块的测试；1.2.0 为 263，删除上游刷机脚本及其 4 个测试文件后为 238，1.3.0 起仍为 238，1.4.0 为 239，1.4.1 为 243，1.4.2 为 249，1.4.3 为 256，1.5.0 为 269，1.5.1 为 270）。

### 投屏页（无浏览器）

```sh
cd receiver/web
mkdir -p node_modules && ln -sfn /opt/npm-tools/node_modules/typescript node_modules/typescript   # 没有 npm install 时
tsc --noEmit -p tsconfig.offline.json
npm test
node scripts/build-esbuild.mjs                                   # 或 npm run build
```

### 两张页面的截图（1.2.0 起，`docs/UI-1.2.0.md`、`docs/UI-1.3.0.md`、`docs/UI-1.5.0.md`）

```sh
cd receiver/web && npm run build:offline
python3 ../../box/tools/render_settings_states.py out/box-states              # 盒子设置页 13 个状态 → 静态 HTML（加 #net / #update / #more 看其他分类，加 ?night=1|0 看夜间/日间）
CHROME=/path/to/chromium node scripts/ui-shots.mjs out/ui-shots [viewer|box|twins]  # 特斯拉 773×601、1256×706、1256×560、1920×1200、手机；twins（1.5.1）量设置面板和盒子设置页的标题栏、分类、第一组是否在同一位置，差半个像素以上即失败
```

需要 `playwright-core` 和一个 Chromium；全部本地 mock，不碰盒子和手机。每个形状打印标签/说明字号、行高和有无横向溢出。

五个检查脚本（`check`、`check-car`、`check-browser`、`check-runtime`，0.1.1 起；`check-location`，1.4.0；`check-audio` 随页面音频于 1.3.0 删除）用 `typescript` 即时编译被测模块，在 Node 里模拟 DOM 表面：输入控制器（含 30ms 最短按压、补发抬起、抬起前补发最后位置（1.4.1）、绝不聚焦画布）、向盒子请求的期限（1.4.1，`ask-box.ts`）、车载模式和特斯拉默认值、状态提示（`status.ts`）、页内选项表、浏览器检测、车辆定位（特斯拉浏览器的占位精度与常数时间戳、GCJ-02 与特斯拉自己的换算对照、一次只读一个位置、页面隐藏时不读）。`check-flac.mjs` 随有线代码删除。这三步在 0.1.0 合并时都通过。

### 接收端

```sh
cd receiver && ./gradlew build          # 编译两个模块并跑测试；1.3.1 起每次推送都在 GitHub Actions 上跑
```

1.1.0 到 1.3.0 在没有 Gradle 网络的环境里写的 Kotlin 改动，1.3.1 的第一次 Actions 运行就编译并通过了测试（`receiver/docs/UNVERIFIED-KOTLIN.md` 留作记录）。1.4.0 新增 `CarLocationTest`（16 个）和 `Iap2LocationReporterTest`（7 个）；1.5.0 的 `CarLocationTest` 加 3 个（坐标系「自动」只在大陆时区换算、手选的不看时区、时区名单）；1.4.1 新增 `ScreenStreamReadDeadlineTest`（4 个，回环套接字上的半截消息）和 `WirelessSessionRecoveryTest`（6 个）；本地没有 Gradle 网络时，推到分支后在 Actions 里 Run workflow 即可得到同样的编译和测试。

### 探测页渲染

`tools/probe/index.html` 用 Playwright 的无头 Chromium 渲染过一次（1920×1200，点过所有需要轻点的按钮、触控区、动画和可达性测试，无控制台错误，截图 `docs/images/probe.png`）。重跑的做法：起一个本地 http 服务提供该文件，用 `playwright-core` 打开，监听 `pageerror` 和 `console`，依次点 `#btnAudio #btnWakeLock #btnFullscreen`、在 `#touchpad` 上 `touchscreen.tap`、填 `#fetchUrls` 后点 `#btnFetch`、点 `#btnAnim10`，最后读 `#outText`。脚本不在仓库里（它依赖本机的 Chromium 路径），步骤如上。

### 脚本语法

```sh
sh -n tools/f50/harden.sh && sh -n tools/f50/measure.sh && sh -n tools/f50/measure.init
sh -n openwrt/autoplay/files/autoplay.init && sh -n box/scripts/build-bundle.sh
```

`harden.sh` 支持 `AUTOPLAY_SYSROOT=<目录>`，可以在一个假根目录里跑 apply / 再次 apply / `--revert`，检查幂等和回退（对真实的 mu300 `extra-modules` 文件做过）。`measure.sh --once --out /tmp/m.csv --persist /tmp/p` 采一行，看表头和数据列数是否一致。

## 2. 盒子台架（装好系统、不上车）

| 测试 | 做法 | 看什么 | 依据 |
|---|---|---|---|
| 点火循环 | 可编程继电器或 USB 电源开关反复通断电，**≥100 次冷启动**，每次完成蓝牙配对和一次 CarPlay 会话（用手机当"车机"开页面）；其中混入 **20 次在 1 分钟内断电**的短途 | 零次退回安卓；上电到出画面 P95 ≤35 秒；`mu300-next-boot status` 的 boot-tries 正常清零 | WP0、WP1、PA#1 |
| 随机断电 | 投屏中随机断电 **200 次**（包括 JVM 启动时、升级过程中） | 零配对丢失、零文件系统错误（`e2fsck -fn`）；先测单次通勤的写盘量（`/proc/diskstats`）做基线 | WP3、H7 |
| 高温浸泡 | 环境 ≥35°C（吹风机或夏天午后），两跳各 15 Mbit/s，持续 2 小时，`measure.sh` 全程记录 | 不复位；装风扇后 SoC 稳定在降频点以下；`thermal-guard` 日志是 "watching only" 还是 "capping"（5.4 是否绑定了 soc-thmzone） | WP4、H1、PA#2 |
| Wi-Fi 压测 | 双向 iperf ≥1 小时，同时跑带载 ping（mu300 项目自己的检查清单） | 不断流；`push link fail`、`loopcheck` 计数 | PA#4 |
| 功耗 | USB 在线电流表：空闲热点、投屏中、5G 工作、高温、开机峰值；模拟打火压降（5V→3.5V 持续 50–300ms） | 填《硬件视角审查》的功耗表；哪种适配器能扛过压降 | H2 |
| 故障注入 | 会话中 `kill` bluetoothd / JVM；卡住 ubus；断 WAN；JVM 启动时断电；升级中断电 | 与当前会话无关的组件故障不中断 CarPlay；相关组件 10 秒内恢复；车机上能看到原因 | WP2 |
| 音频空洞 | 把页面统计的 400ms 空洞时间戳和内核 `loopcheck(N)` 行对齐 | 是否每 5 秒一次（H8 的假设） | H8 |
| harden.sh | `--dry-run` → apply → `--status` → 重启 → `--status` → `--revert` | 每项都按预期；`extra-modules` 去掉模块后重启内存多出约 45MB | tools/f50 |

## 3. 车上验收（《加固路线图》§五"可以天天用"）

先用 `tools/probe/` 得到能力表，再用 `tools/car/touch-latency.md` 测延迟，`measure.sh` 全程开着。

- [ ] 连续 2 周通勤（≥40 次点火），全程不需要人工干预
- [ ] 零次退回安卓
- [ ] 上电到出画面 P95 ≤40 秒
- [ ] 触摸到画面 P95 ≤200ms（240 fps 相机法）
- [ ] 夏天暴晒停车后上车，5 分钟内恢复正常，或者明确提示过热
- [ ] 随机断电 200 次，零配对丢失、零文件系统错误（台架完成即可）
- [ ] 进隧道 SIM 掉线时 CarPlay 不受影响（上游 10.25 已修，作为回归项）
- [ ] 声音全走蓝牙：导航播报从车机扬声器出来、第一个字没被吃、播报时 iPhone 自己压低音乐；通话无回声（走车载蓝牙）
- [ ] 从后台拉回浏览器十次，屏幕键盘不再出现（1.3.0，`docs/UI-1.3.0.md` §六）

阶段 1 的基线复现标准（技术路径 §六）：上电到出画面 ≤45 秒；触摸到画面 ≤200ms；≥30fps；连续 30 分钟音频不断；暴晒下 SoC <85°C；连续 10 次点火都能自动重连。

界面的验收（界面审查 §七）：驾驶者要读的文字 ≥25px（按设备像素核对）、主要触控目标 ≥70px；链路断开 1 秒内画面变灰并出现常驻提示；每个状态的文案与实际状态一致（20 种状态逐一核对，WheelPlay 式的无头浏览器测试）；竖屏和 16:10 不变形；F50 设置页无"数据线"字样；配对码在手机首屏可见。

## 4. 车上还要回答的问题

接收端这次改动里要在盒子或车上才能看出对错的（`receiver/docs/UNVERIFIED-KOTLIN.md`"需要一台盒子或一辆车"）：

1. 封面排空：音乐走车载蓝牙时 iPhone 仍发起封面文件传输，排空线程必须让隧道活过 256 次传输；长途多次切歌后看日志里有没有 `iAP2 received-file queue limit exceeded`。
2. iOS 27 深浅色：iOS 27 手机上夜间模式能切换（日志 `appearance updates=true`），iOS 26 仍靠 `setNightMode`；2,2 / 1,1 的取值来自 dashplay-tesla 的实车观察，Apple 没有文档。
3. duck/unduck：页面不再有可压低的声音（1.3.0），`grep 'audio duckAudio'` 只用来确认 iPhone 仍把压低音乐的事交给了蓝牙那边。
4. 配对存储：第一次新配对后 `state/receiver/pairings.properties.bak` 出现；故意清空主文件后下次启动要回退到 `.bak`。
5. DSCP：盒子上 `tcpdump -v` 看 18443 的流量 TOS 是否 0x88。
6. 触摸释放：手指按着时挂倒挡冻结页面，日志应出现 `viewer client=N paused with a finger down: lifting it`，iPhone 上不能留下按住的按钮。

技术路径 §八的问题：

- iPhone 加入 F50 热点后，会不会走 F50 的 SIM 卡上网（流量费 + 挤占带宽）。
- 车载蓝牙模式下来电、Siri、导航语音分别从哪里出声，能否稳定切换；iOS 26 和 27 是否不同。
- F50 自带热点上的真实触摸延迟和帧率。
- 特斯拉：方向盘按键是否交给网页；证书警告页有没有"继续"；行车时网页麦克风是否可用；Let's Encrypt 从国内 SIM 可达已在 1.0.0 验证（DNSPod 路线）；DuckDNS 的接口从这张 SIM 卡是否可达仍未验证。
- iPhone 走开再回来，是否真的不会自己连回 F50 的热点（dashplay-tesla 作者在 N1 上的观察）。

## 5. 持续

每次改动都要有前后对比：`measure-report.py` 的 CPU0 软中断%、SoC 最高温、降频分钟数，加上相机法的 P50/P95。没有基线的优化不合并。
