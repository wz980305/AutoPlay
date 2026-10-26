# 测试

分四层：台式机上能跑的单元测试和检查脚本；盒子上的台架测试；车上的验收清单；长期的浸泡。本里程碑只跑过第一层。

## 1. 台式机

### Python（标准库 unittest）

```sh
# 本仓库的工具
python3 -m unittest tools/f50/test_measure_report.py

# 盒子侧（来自 DashPlay）：设置、多手机、平台、诊断、固件打包；证书相关测试需要 OpenSSL 3
cd box && python3 -m unittest discover -s tests/onecloud

# 蓝牙桥：需要 dbus-daemon 和 dbus-next；测试身份全是合成数据
cd box && python3 -m unittest discover -s tests/bluetooth
```

### 投屏页检查脚本（无浏览器）

```sh
cd receiver/web && npm ci && npm test
# 等于：node check.mjs && node check-audio.mjs && node check-car.mjs && node check-browser.mjs && node check-flac.mjs
```

它们用 `typescript` 即时编译被测模块，在 Node 里模拟 DOM 表面：输入控制器、音频时间线、车载模式、浏览器检测、FLAC 封装。

### 接收端

```sh
cd receiver && ./gradlew test
```

见 `docs/BUILD.md` 的警告：Kotlin 侧改动未编译，第一次跑之前先读 `receiver/docs/UNVERIFIED-KOTLIN.md`。

### 探测页渲染

`tools/probe/index.html` 用 Playwright 的无头 Chromium 渲染过一次（1920×1200，点过所有需要轻点的按钮、触控区、动画和可达性测试，无控制台错误，截图 `docs/images/probe.png`）。重跑的做法：起一个本地 http 服务提供该文件，用 `playwright-core` 打开，监听 `pageerror` 和 `console`，依次点 `#btnAudio #btnWakeLock #btnFullscreen`、在 `#touchpad` 上 `touchscreen.tap`、填 `#fetchUrls` 后点 `#btnFetch`、点 `#btnAnim10`，最后读 `#outText`。脚本不在仓库里（它依赖本机的 Chromium 路径），步骤如上。

### 脚本语法

```sh
sh -n tools/f50/harden.sh && sh -n tools/f50/measure.sh && sh -n tools/f50/measure.init
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
- [ ] 导航播报时会压低音乐；通话无回声（或者走车载蓝牙）

阶段 1 的基线复现标准（技术路径 §六）：上电到出画面 ≤45 秒；触摸到画面 ≤200ms；≥30fps；连续 30 分钟音频不断；暴晒下 SoC <85°C；连续 10 次点火都能自动重连。

界面的验收（界面审查 §七）：驾驶者要读的文字 ≥25px（按设备像素核对）、主要触控目标 ≥70px；链路断开 1 秒内画面变灰并出现常驻提示；每个状态的文案与实际状态一致（20 种状态逐一核对，WheelPlay 式的无头浏览器测试）；竖屏和 16:10 不变形；F50 设置页无"数据线"字样；配对码在手机首屏可见。

## 4. 车上还要回答的问题（技术路径 §八）

- iPhone 加入 F50 热点后，会不会走 F50 的 SIM 卡上网（流量费 + 挤占带宽）。
- 车载蓝牙模式下来电、Siri、导航语音分别从哪里出声，能否稳定切换；iOS 26 和 27 是否不同。
- F50 自带热点上的真实触摸延迟和帧率。
- 特斯拉：方向盘按键是否交给网页；证书警告页有没有"继续"；行车时网页麦克风是否可用；DuckDNS 和 Let's Encrypt 从这张 SIM 卡是否可达。
- iPhone 走开再回来，是否真的不会自己连回 F50 的热点（dashplay-tesla 作者在 N1 上的观察）。

## 5. 持续

每次改动都要有前后对比：`measure-report.py` 的 CPU0 软中断%、SoC 最高温、降频分钟数，加上相机法的 P50/P95。没有基线的优化不合并。
