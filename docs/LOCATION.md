# 车辆定位给 iPhone（1.4.0）

日期：2026-11-05。投屏页「常用 → 导航 → 使用车辆定位」打开后，特斯拉浏览器读到的车辆位置每秒送到盒子，盒子按 iAP2 LocationInformation（`$GPGGA` + `$GPRMC`）交给 iPhone，CarPlay 导航用它。**默认关闭。**本文先写调研得出的结论（为了不靠实车试错就能定下做法），再写做法、开关、日志和来源。

## 一、结论

### 1. iPhone 会认真用车机给的位置——好坏都会

- Apple 对 CarPlay 车机的要求（WWDC16 722、WWDC17 717）：车机要提供速度；无线 CarPlay 要求车机有 GNSS，"车辆的卫星定位与 iPhone 自己的传感器一起使用"。
- 实测（LIVI #354，iOS 18.7.2）：iPhone 自己没有好定位时日志写"got accessory, stopping everything less preferred"，改用车机的位置；自己定位好时保留自己的。iOS 15 起 `CLLocationSourceInformation.isProducedByAccessory` 标出"来自 CarPlay"的定位。
- 反面：宝马 iX 的 TSB MC-10242869（"第三方导航位置漂移"，原因是 TCB4 远程信息模块软件，刷新解决）、大众"CarPlay 用了车的错误位置"、iOS 18.0"在海中央"、Alpine 接 OBD 后位置晚 10–30 秒照样显示、国内 V2EX 多帖"CarPlay 用车机 GPS 就漂，断开 CarPlay 就好"。**车机给错的、晚的、冻住的位置，iPhone 会照用。**
- iOS 有一点防伪：LIVI 把位置伪造到远处，几秒后被识破；但这不能当成保护。

所以这个功能只能在"给出去的每一个点都新鲜、连续、坐标系对"时才开，任何一项不确定就**什么都不发**——没有车机数据时 iPhone 用回自己的 GNSS，这是它本来的状态。

### 2. 特斯拉浏览器给的是什么

| 事实 | 来源 |
|---|---|
| 是车自己的位置，带速度、航向、海拔 | Leaflet #7157（2020，Model 3，精度 0.78 m）；tesla-pi 实测（2026-08，Model 3 焕新版，Chromium 148：速度 0、航向 203.77°、海拔 51.35 m，首次 12 ms）；Tesla Android 2025.46.1 "用特斯拉提供的速度和航向" |
| `accuracy` 可能是占位值 **9999.99**（不是 10 km 误差） | tesla-pi |
| `timestamp` 可能是**不随时间走的常数**，也不是 1970 年起的毫秒 | tesla-pi（一个约 1.8 × 10¹⁰ 的数，每个点都一样） |
| 每秒 `getCurrentPosition` 一次可用，是 Tesla Android 从 2023.32.1 跑到现在的做法；`watchPosition` 2020 年没有授权提示、报错，2026 年只在位置变化时回调 | Tesla Android `gps-controller.js`；Leaflet #7157；tesla-pi |
| 必须 HTTPS，证书过期就拿不到位置；授权按网址记住 | Tesla Android #308、release notes |
| 授权位置后浏览器可能崩溃：2023.32 起出现，2023.36 说修好，**2024.14 又回来（多为 MCU2）**，Tesla Android 从此默认关闭 | Tesla Android release notes 2023.32.1 / 2023.36.1 / 2024.24.1 |
| 浏览器最小化后很快关闭，重开时重新加载 | incarweb.app（2026-09） |
| 有报告说位置在导航模式开始后冻住或跳到旧位置（ABRP，2023–2024），原因未明 | ABRP 反馈板 |
| 特斯拉自己的接口对国内车同时给 WGS-84 和 GCJ-02（"native"），相差约 600 m | teslamotors/fleet-telemetry #392（深圳）、alandtse/tesla #233（广州） |

### 3. 没有人默认打开它

查到的特斯拉投屏方案（Carlinkit T2C、TslaMirror、TeslAA 等）都只用手机定位；能转发浏览器定位的只有 Tesla Android 和 WheelPlay，**都默认关闭**（Tesla Android 因崩溃从 2024.24.1 起关闭）。DiPlay 的特斯拉浏览器模式干脆不做定位，比亚迪车机模式「向 iPhone 报告位置」默认关。

### 4. 查不到的两件事，以及代码怎样让它们答错时也无害

| 查不到 | 答错的后果 | 代码的处理 |
|---|---|---|
| 国行特斯拉浏览器的坐标是 WGS-84 还是 GCJ-02 | iPhone 收到偏几百米的位置，照用 | 「坐标系」两项各自写出"按这个算，车在哪"，格式和 iPhone 指南针一样，**停车时对一眼指南针、点一样的那项**（§三）；默认 WGS-84（标准 Chromium 和特斯拉接口的默认字段都是 WGS-84） |
| 行驶中浏览器多久出一个新点、导航时会不会冻住 | 冻住的位置被当成"车还在这" | 只有**位置变了**才算新点；同一位置再来一遍（缓存或冻住）不算；2.5 s 没有新点就停发，iPhone 用回自己的 |

崩溃风险：只在车主打开开关的那一刻请求授权；本车是 AMD（MCU3），没有查到 AMD 车的崩溃报告。浏览器真的崩了，关掉开关（或在地址栏撤销本站的位置权限）即可。

## 二、做法

```
特斯拉浏览器 navigator.geolocation（每秒一次，只在页面可见时）
  → 投屏页 location.ts：{type:"location", location:{lat, lon, acc, alt, speed, heading, time}} 走已有的 WSS
  → 盒子 CarLocation.kt：判新鲜、去跳点、可选 GCJ-02 → WGS-84
  → Iap2LocationReporter（每 250 ms 问一次，有新点才发）
  → iAP2 0xFFFB LocationInformation：$GPGGA + $GPRMC → iPhone
```

- **只在 Wi-Fi 上的 iAP2 隧道里声明**（identification 的 LocationInformation 组件，GGA + RMC），蓝牙引导链路不声明：iOS 可能把位置绑在声明它的链路上，RFCOMM 关闭后拒收 Wi-Fi 上的（DiPlay PR #157）。开关从关到开时 CarPlay 重连一次（约 5 秒），iPhone 才知道多了一个位置来源；关掉立即停发，声明随下次连接去掉，不打断当前画面。
- **新点**：位置和上一个不同。同一位置再来不算（缓存、冻住都是这样）；所以停在红灯时 2.5 s 后不再发，iPhone 用自己的定位直到车动。
- **时间**：浏览器的 `timestamp` 不可信，NMEA 的时间是盒子收到这个点的时刻（精确到百分之一秒）。没有证据说明 iOS 用 NMEA 时间补偿延迟，所以链路要短：盒子每 250 ms 取一次，按设计页面读到 → iPhone 不超过约 0.3 s。
- **精度**：9999 以上当"没报"（HDOP 写 1.0）；真实精度差于 100 m 的点丢掉（那是网络估算，不是卫星定位）；其余 HDOP = 精度 / 5。
- **跳点**：比上一个点远出"70 m/s × 间隔 + 100 m"的点先扣住，下一个点也在那附近才接受（浏览器自己的修正）；回到原轨迹的点照常接受。超过 30 s 没有点（页面藏过、地库）则从头开始，不论距离。
- **不发的东西**：`$PASCD`（车速）——浏览器的速度来自 GPS，隧道里正好没有，冒充轮速对航位推算没有好处；海拔、航向未知时字段留空（"0.0" 等于说在海平面、"0.00" 等于说朝北）。
- 这一版顺带修了接收端从上游继承的一个问题：旧的无线循环在**每收到一个 iPhone 消息**后都把最后一个位置再发一遍（以前位置功能没开，所以没有表现）。

## 三、开关与坐标系

- 「常用 → 导航 → 使用车辆定位」：打开时浏览器弹一次"是否允许使用位置"，拒绝则开关回到关。开关状态存在盒子（`config.json` 的 `carLocation`），授权存在浏览器。
- 「坐标系」只在车在中国大陆境内（或已选 GCJ-02）时出现。点开后两项下面各有一行灰字，是"按这一项换算后交给 iPhone 的位置"，写法和 iPhone「指南针」App 底部一样（度分秒）。**停着车，打开 iPhone 指南针，选和它一致的那一项**——相差十几秒（约 300–600 m）的那项就是错的。之后不用再管。
- 调试浮层（「显示 → 画质与兼容 → 显示调试信息」）打开时多一行「车辆定位 1.0/s · 43 km/h」：每秒送出几个点、当前车速。行驶中这一行应在 1/s 左右；长时间是 0 说明浏览器没给新位置（此时 iPhone 用自己的定位）。

## 四、更好、不变、更坏

- **更好**：iPhone 放在中控下方、杯架、包里，或城市峡谷里——车顶天线的定位比手机好，iPhone 会用它。
- **不变**：开阔路面、手机定位本来就好——iPhone 基本保留自己的。
- **可能更坏**：坐标系选错（§三一次解决）；浏览器给出跳变或滞后的位置而没被过滤（只能从日志判断，见 §五）。拿不准就关掉，回到 1.3 的状态。
- **隧道**：浏览器在隧道里给不给推算位置查不到；给，就照常转发；不给或冻住，盒子停发，iPhone 用自己的运动传感器——和不开一样。

## 五、日志里看什么

盒子日志（LuCI 或 `logread -e autoplay`）：

- `wireless iAP2 tunnel accepted carLocation=true`：这次连接声明了位置。
- `car location: the iPhone asked for sentence types [...]`、`started location updates`：iPhone 要了位置。
- 每分钟一行 `car location: last 60 s new=58 repeated=2 jumped=0 dropped=0 off=0 sent=58 withSpeed=58 requested=true datum=wgs84 accuracy=not reported`：`new` 接近 60、`sent` 接近 `new` 是正常行驶；`jumped` 或 `dropped` 经常不为 0 说明浏览器的位置有问题，关掉开关。
- 投屏页每 10 秒的 `viewer stats` 里有 `locSent`、`locFailed`、`locAcc`、`locDenied`。

日志里没有坐标；盒子不保存位置。

## 六、来源

- Apple：WWDC16 722 *Developing CarPlay Systems*、WWDC17 717；`CLLocationSourceInformation.isProducedByAccessory`
- LIVI #354（iOS 怎样采用配件定位）；DiPlay `docs/BYD_NAVIGATION.md`、PR #109 / #157；rigPlay #7
- tesla-pi `docs/telemetry-options.md`（2026-08 实测）；Tesla Android `web/beta/js/gps/gps-controller.js` 与 release notes；Leaflet #7157
- teslamotors/fleet-telemetry #392、alandtse/tesla #233（国内车的两种坐标）
- BMW TSB MC-10242869（NHTSA）；V2EX 1036418、708591；ABRP 反馈板"Tesla GPS location does not refresh in built-in browser"
- WheelPlay `browser-location.js`（另一个默认关闭的实现）
