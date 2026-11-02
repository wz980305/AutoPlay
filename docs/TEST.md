# 测试

分四层：台式机上能跑的单元测试和检查脚本；盒子上的台架测试；车上的验收清单；长期的浸泡。0.1.1 本轮完成的测试范围、计数和未通过项目详见 `AUDIT-0.1.1.md`；以下保留原台架/实车验收方案。

## 1. 台式机

### Python（标准库 unittest）

```sh
# 本仓库的工具
python3 -m unittest discover -s tools/f50
python3 -m unittest discover -s openwrt/tests      # 安装脚本 90-autoplay-tesla 对着假 uci（1.0.1）

# 盒子侧：设置页、状态模型、守护（supervision）、升级日志与回滚、证书退避、时钟下限、出厂重置、平台、诊断、装机脚本
cd box && python3 -m unittest discover -s tests/onecloud        # 225 个，通过（0.1.0 合并时在本机跑过）

# 蓝牙桥：test_reason、test_relay 等 7 个可直接跑；test_bluez、test_recovery 需要 dbus-daemon 和 dbus-next 0.2.3
cd box && python3 -m unittest discover -s tests/bluetooth       # 没有 dbus-next 时那两个模块报 import 错误，是环境问题
```

测试身份全是合成数据。裁剪前后的基线在 `box/docs/TEST-BASELINE.md`（375 → 225 是删掉的 Debian/N1/有线/STA 测试减去新模块的测试）。

### 投屏页（无浏览器）

```sh
cd receiver/web
mkdir -p node_modules && ln -sfn /opt/npm-tools/node_modules/typescript node_modules/typescript   # 没有 npm install 时
tsc --noEmit -p tsconfig.offline.json
npm test
node scripts/build-esbuild.mjs                                   # 或 npm run build
```

四个检查脚本用 `typescript` 即时编译被测模块，在 Node 里模拟 DOM 表面：输入控制器（含 30ms 最短按压、补发抬起）、音频时间线、车载模式和特斯拉默认值、状态提示（`status.ts`）、duck 渐变、浏览器检测。`check-flac.mjs` 随有线代码删除。这三步在 0.1.0 合并时都通过。

### 接收端

```sh
cd receiver && ./gradlew build          # 编译两个模块并跑测试；0.1.1 已完成
```

见 `docs/BUILD.md` 的警告：Kotlin 侧改动未编译，第一次跑之前先读 `receiver/docs/UNVERIFIED-KOTLIN.md`，它按文件列出了编译风险和"失去最后一个调用者"的预期警告。

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
- [ ] 导航播报时会压低音乐；通话无回声（或者走车载蓝牙）

阶段 1 的基线复现标准（技术路径 §六）：上电到出画面 ≤45 秒；触摸到画面 ≤200ms；≥30fps；连续 30 分钟音频不断；暴晒下 SoC <85°C；连续 10 次点火都能自动重连。

界面的验收（界面审查 §七）：驾驶者要读的文字 ≥25px（按设备像素核对）、主要触控目标 ≥70px；链路断开 1 秒内画面变灰并出现常驻提示；每个状态的文案与实际状态一致（20 种状态逐一核对，WheelPlay 式的无头浏览器测试）；竖屏和 16:10 不变形；F50 设置页无"数据线"字样；配对码在手机首屏可见。

## 4. 车上还要回答的问题

接收端这次改动里要在盒子或车上才能看出对错的（`receiver/docs/UNVERIFIED-KOTLIN.md`"需要一台盒子或一辆车"）：

1. 封面排空：音乐走车载蓝牙时 iPhone 仍发起封面文件传输，排空线程必须让隧道活过 256 次传输；长途多次切歌后看日志里有没有 `iAP2 received-file queue limit exceeded`。
2. iOS 27 深浅色：iOS 27 手机上夜间模式能切换（日志 `appearance updates=true`），iOS 26 仍靠 `setNightMode`；2,2 / 1,1 的取值来自 dashplay-tesla 的实车观察，Apple 没有文档。
3. duck/unduck：`grep 'audio duckAudio'` 看 iPhone 发来的原始 `volume`，dB 到线性的映射在有日志之前是猜的。
4. 配对存储：第一次新配对后 `state/receiver/pairings.properties.bak` 出现；故意清空主文件后下次启动要回退到 `.bak`。
5. DSCP：盒子上 `tcpdump -v` 看 18443 的流量 TOS 是否 0x88。
6. 触摸释放：手指按着时挂倒挡冻结页面，日志应出现 `viewer client=N paused with a finger down: lifting it`，iPhone 上不能留下按住的按钮。

技术路径 §八的问题：

- iPhone 加入 F50 热点后，会不会走 F50 的 SIM 卡上网（流量费 + 挤占带宽）。
- 车载蓝牙模式下来电、Siri、导航语音分别从哪里出声，能否稳定切换；iOS 26 和 27 是否不同。
- F50 自带热点上的真实触摸延迟和帧率。
- 特斯拉：方向盘按键是否交给网页；证书警告页有没有"继续"；行车时网页麦克风是否可用；DuckDNS 和 Let's Encrypt 从这张 SIM 卡是否可达。
- iPhone 走开再回来，是否真的不会自己连回 F50 的热点（dashplay-tesla 作者在 N1 上的观察）。

## 5. 持续

每次改动都要有前后对比：`measure-report.py` 的 CPU0 软中断%、SoC 最高温、降频分钟数，加上相机法的 P50/P95。没有基线的优化不合并。
