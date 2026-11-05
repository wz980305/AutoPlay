# AutoPlay 1.4.2 安装 / 卸载 / 使用说明

> 适用：中兴 F50（MU300，已 Root + OpenWrt 25.12，内核 5.4）上的无线 CarPlay，画面投到特斯拉车机浏览器。
> 1.0.0 是**首个在特斯拉车内实测通过的版本**（无线 CarPlay 画面、触摸、导航播报已验证）；1.0.1 是它的收尾；**1.1.0 把声音默认全部交给特斯拉蓝牙**（见第三节），并引入 DashPlay 10.26–11.01 的可靠性修复；**1.2.0 只改界面**：两张页面按特斯拉的窗口形状核对，下拉与确认框改在页内画（见第六节）；**1.3.0** 按上车一周后的清单收口：设置面板按 iOS「设置」的样子（每行图标、无小字），网页里的声音和「备用控制」删掉，盒子页不再报"上游在线"，并修浏览器拉回时偶尔弹键盘的问题（见第七节）；**1.3.1** 接上在线升级：项目有了自己的发布密钥，每个版本是 GitHub 上一个签过名的 Release，装好 1.3.1 以后在设置页点一下就能升级（见第八节）。**1.3.2** 设置面板左侧分类去掉图标、删掉「允许 2560 分辨率」，盒子页「检查更新」下不再有「上次检查」一行。**1.4.0** 可以把车辆定位交给 iPhone 的 CarPlay 导航（默认关闭，见第九节）；「显示 → 画质」的「应用并重连」只在改了内容大小或帧率时才出现。**1.4.1** 无线 CarPlay 意外断开后盒子会主动请回那部 iPhone 一次、画面流卡住 10 秒内重连；盒子设置页按窗口形状重排，顶部只留需要处理的提示（见第十节）。**1.4.2** 在线升级先经 GitHub API 下载，github.com 的下载链接返回 502 时也能升级。接收端的 Kotlin 自 1.1.0 起未在本地编译过，1.3.1 起由 GitHub Actions 编译；自己编译时留意 `receiver/docs/UNVERIFIED-KOTLIN.md`。

---

## 一、安装

### 1. 前置
- F50 已按 [mu300-linux](https://github.com/dikeckaan/mu300-linux) 的文档刷成它的 OpenWrt 镜像（我们实测的那台原厂固件是 B13；刷机步骤本说明不写），后台 `http://192.168.77.1`（root 登录）。
- 盒子需能联网（插 SIM），装依赖要拉 OpenWrt 源。

### 2. 拿到安装包

**直接下载（推荐）**：GitHub 仓库 `wz980305/AutoPlay` 的 Releases → 最新版本（现在是 `v1.4.2`），下载 `autoplay-1.4.2-r1.apk`、`luci-app-autoplay-*.apk`、`luci-i18n-autoplay-zh-cn-*.apk` 和与盒子架构对应的 `autoplay-jre-*_<架构>.apk`（F50 一般是 `aarch64_generic`；`ssh root@<盒子> cat /etc/apk/arch` 可查）。`SHA256SUMS` 里有每个文件的哈希。

浏览器下载返回 502 时，改走 GitHub API 的 asset 接口（在电脑的终端里，一个空文件夹中运行；只取 F50 用得到的包，最后一步核对哈希）：

```sh
TAG=v1.4.2
curl -s https://api.github.com/repos/wz980305/AutoPlay/releases/tags/$TAG \
  | python3 -c 'import json,sys; [print(a["url"], a["name"]) for a in json.load(sys.stdin)["assets"]]' \
  | grep -E ' (autoplay-[0-9].*|luci-.*|autoplay-jre-.*_aarch64_generic\.apk|SHA256SUMS)$' \
  | while read url name; do curl -fL -H 'Accept: application/octet-stream' -o "$name" "$url"; done
grep -E 'autoplay-[0-9]|luci-|aarch64_generic' SHA256SUMS | shasum -a 256 -c -
```

**自己编译**：需要 JDK 21 工具链 + Docker（SDK 镜像 `openwrt/sdk:x86-64-25.12.5`），或者一条命令 `sh box/scripts/release.sh 1.4.2`（同 GitHub Actions 里跑的那条，产物在 `out/release-1.4.2/`）。分步：

```sh
# 都在仓库根目录执行
# 编译接收端（Kotlin/Gradle 9.5.0）
(cd receiver && ./gradlew build && ./gradlew :server:installDist)   # build 先跑测试：1.1.0 起的 Kotlin 改动还没编译过
# 编译投屏页
(cd receiver/web && npm ci && npm run build)
# 打程序包
AUTOPLAY_VERSION=1.4.2 sh box/scripts/build-bundle.sh autoplay-bundle.tar
# 用 Docker SDK 打 apk
sh openwrt/scripts/build-packages.sh out/ autoplay-bundle.tar
```

产物在 `out/`：`autoplay-1.4.2-r1.apk`、`autoplay-jre-*_<架构>.apk`、`luci-app-autoplay-*.apk`、`luci-i18n-autoplay-zh-cn-*.apk`。

### 3. 装到 F50（手动路线）
```sh
ssh root@192.168.77.1 cat /etc/apk/arch    # 一般 aarch64_generic
# 推 4 个包到盒子，然后在盒子上：
apk update
apk add --allow-untrusted autoplay-jre-*_<架构>.apk autoplay-[0-9]*.apk \
    luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk
python3 /opt/autoplay/board_zte_f50.py --setup   # F50 私有 BlueZ（切勿 apk add bluez-daemon）
/etc/init.d/autoplay restart
```

> 安装时（`90-autoplay-tesla`）会自动完成两件事，并有一个副作用：
> 1. LAN 从 `192.168.77.1` 切成 **`100.96.0.1/24`**（特斯拉浏览器不认私网地址）。
> 2. 5 GHz 无线设为**中国区 CN / 信道 149**（厂商镜像国家码 TR 不含 149–165，这正是特斯拉搜不到热点的原因）。已经在 149–165 里的信道（例如你在 LuCI 里改成的 157）会保留。
> 3. 两处修改都会让经 Wi-Fi 连着的 SSH 断开一次：LAN 换地址，无线重载。

### 4. 认证身份（投屏前必须）
把 `identity.pk8` + `certificate.p7b` 放到 `/opt/autoplay/identity/offline-mfi/`，`/etc/init.d/autoplay restart`，状态页 `identity` 由 missing 变为 provided。

---

## 二、自有域名证书（可选，消除车机警告）

支持两种 DNS 提供商（LuCI「服务 → AutoPlay → 自己的网址」或命令行 uci）：

**DuckDNS（免费子域名）**
```sh
uci set autoplay.main.dns_provider=duckdns
uci set autoplay.main.duckdns_domain=<子域名>
uci set autoplay.main.duckdns_token=<token>
uci commit autoplay
```

**腾讯云 DNSPod（自有域名，本版新增）**
```sh
uci set autoplay.main.dns_provider=dnspod
uci set autoplay.main.own_domain=<域名，如 car.example.com>
uci set autoplay.main.dnspod_id=<DNSPod API ID>
uci set autoplay.main.dnspod_token=<DNSPod API Token>
uci commit autoplay
/etc/init.d/autoplay restart
```

盒子会自动用 DNS-01 挑战通过 DNSPod API 签发 Let's Encrypt 正式证书，并在到期前 30 天自动续期（证书有效期 90 天）。车机访问 `https://<域名>:18443/` 无警告。盒子本地 dnsmasq 会为特斯拉解析该域名；**建议同时在 DNSPod 控制台加一条 A 记录 `<域名> → 100.96.0.1`**，车机若经公网解析器查询也能解析（DuckDNS 路线天然如此）。

> 注意：DNSPod 的 API Token 是**账号级**凭证，能改这个账号下所有域名的解析。只填在自己掌控的盒子上；它保存在盒子的 `/etc/config/autoplay`（仅 root 可读）和 acme.sh 的账户文件里，出厂重置会清除。更稳的做法（腾讯云子账号最小权限密钥）在后续版本。

---

## 三、声音

**所有声音走特斯拉蓝牙**：盒子不向 iPhone 提供 CarPlay 音频，音乐、导航播报、通话、Siri 全部由 iPhone 经特斯拉蓝牙播出，CarPlay 页面无声，页面里没有任何声音设置。前提：iPhone 连着特斯拉蓝牙并被选为媒体来源；没连时声音会从 iPhone 自己出来。

1.1.0–1.2.0 里"改为页面播放导航"的备选（LuCI「导航播报」下拉、`uci audio_route_navigation`）在 1.3.0 删掉了：车上已确认走蓝牙可用，备选只剩成本。升级时安装脚本会自动删掉旧配置里的这个键，不用手动处理。页面也不能播音乐（行驶中的特斯拉会对播音乐的网页弹横幅并让 CarPlay 反复重连）。细节见 `docs/AUDIO.md`。

---

## 四、卸载

```sh
apk del luci-i18n-autoplay-zh-cn luci-app-autoplay autoplay autoplay-jre
```

注意：iPhone 配对、证书、认证身份文件会保留在 `/opt/autoplay/`；LAN 不会自动改回 `192.168.77.1`（需手动 `uci set network.lan.ipaddr=...`）。

---

## 五、使用

| 入口 | 地址 |
|---|---|
| 设置页 | `http://100.96.0.1:18080/` |
| LuCI 后台 | `http://100.96.0.1/` → 服务 → AutoPlay |
| 车机浏览器 | `https://<域名>:18443/`（或 `https://autoplay.lan:18443/`） |

### 上车步骤
1. **F50 接车上 USB**：5V≥3A、打火不断电的口，短粗线；加散热片/小风扇。
2. **iPhone**：连特斯拉蓝牙并设为媒体来源（音乐/通话/Siri 走特斯拉蓝牙）。
3. **车机 Wi-Fi**：打开「行驶中保持连接」，连 F50 的热点（SSID 见 LuCI「网络 → 无线」）。
4. **第一次使用**：车机（或手机）浏览器打开 `http://100.96.0.1:18080/`，点「添加 iPhone」；在 iPhone 的「设置 → 蓝牙」里点盒子的名字，两边核对六位配对码。之后 iPhone 靠近盒子，蓝牙 iAP2 自动引导它连上 F50 热点。
5. 车机浏览器打开 `https://<域名>:18443/`，即看到 CarPlay 画面；触摸回传。默认模式下页面无声，所有声音从特斯拉蓝牙出来，不需要轻点。

### 关键注意
- 蓝牙必须用私有 BlueZ，**不要 `apk add bluez-daemon`**（会带入不匹配的 6.12 内核模块）。
- 开一段导航，留意播报的第一个字有没有被吃掉；来电、Siri 照常。
- 盒子需长期有 SIM（证书续期 + 特斯拉联网检测）。
- **1.2.0 上车看一眼界面**：设置 → 夜间模式弹出的是页内选项表（大字、可点）而不是浏览器的小下拉；盒子页点一部手机 → 「删除此 iPhone…」出现确认屏而不是浏览器弹窗。若选项表没有出现，把车机浏览器版本记到 `docs/TESLA.md` 并反馈。
- **1.3.0 上车看一眼**：从别的应用切回浏览器十次左右，屏幕键盘不再出现；设置面板三页每行都有图标、没有小字。
- **在线升级（1.3.1 起）**：已经装着 1.3.0 或更早版本的盒子，先按第一节手动装一次 1.3.1 或更新的版本（可以直接用 GitHub Release v1.3.1 上的 apk，不必自己编译）；之后设置页或 LuCI「程序更新」会在新版本发布后一天内提示，点「立即升级」即可，CarPlay 断开约 1 分钟，起不来会自动退回（`docs/RELEASE.md`）。勿手动覆盖 `/opt/autoplay/{state,identity}`。

## 六、1.2.0 的界面变化（`docs/UI-1.2.0.md`）

- 投屏页设置里的五个下拉（夜间模式、语言、CarPlay 内容大小、帧率、视频编码）改为页内选项表：点行 → 居中列表，每项一行，当前项打勾，「取消」关闭。
- 二级菜单（画质与兼容、连接与兼容性、备用控制；盒子页的手机行）打开时自动滚进视野。
- 盒子设置页（`http://100.96.0.1:18080/`）字号和按钮尺寸与投屏页一致；添加 iPhone 时整页只显示配对码和「一致 / 不一致」；「删除此 iPhone…」「立即升级」先进入确认屏再执行，没有浏览器弹窗。
- 操作和地址都没有变化；不需要重新配对或重新申请证书。

## 七、1.3.0 的变化（`docs/UI-1.3.0.md`）

- 设置面板：每行一个彩色图标 + 标签 + 当前值，和 iOS「设置」一样；行内不再有说明文字；「常用」只剩夜间模式和语言，「显示」是画质、无边框模式、画质与兼容，「连接」是打开盒子网页和连接与兼容性。「声音」分组和「备用控制」删除。
- 浏览器被拉回时偶尔弹出的屏幕键盘：画面不再持有浏览器焦点，页面重新可见时清掉焦点；键盘即使出现也不改变页面尺寸。
- 盒子设置页：不再显示"上游在线"的横幅，只有上游不可用时才提示。
- 操作和地址都没有变化；不需要重新配对或重新申请证书。升级时旧配置里的 `audio_route_navigation` 键会被自动删掉。

## 八、在线升级（1.3.1 起，`docs/RELEASE.md`）

- **第一次**：装着 1.3.0 或更早版本的盒子，按第一节手动装一次 1.3.1 或更新的版本（直接用 Release 上的 apk 即可）。旧版本的包里是上游 DashPlay 的公钥，认不出我们签的发布；1.3.1 带着项目自己的公钥。
- **之后**：盒子开机 2 分钟后检查一次，之后每 24 小时一次；有新版本时，设置页 `http://100.96.0.1:18080/`「程序更新」和 LuCI「程序更新」会显示版本号和这一版改了什么。点「立即升级」→ 确认：CarPlay 断开约 1 分钟，盒子先备份配对、证书和设置，先下载当前版本作退路，新版本起不来就自动装回。CarPlay 正在用时不会升级。
- 下载先走 GitHub API（1.4.2 起；github.com 的下载链接返回 502 时也能下），再走 github.com，都不行时自动换镜像（默认 `ghfast.top`，LuCI「程序更新」可改；`none` 表示只用 GitHub）。所有文件都核对签名和哈希，来源和镜像改不了内容。
- 不想让盒子检查：LuCI「程序更新」关掉「检查更新」。

## 九、车辆定位（1.4.0 起，`docs/LOCATION.md`）

默认 CarPlay 导航用 iPhone 自己的定位。打开这个开关后，特斯拉的位置（车顶天线）每秒经盒子交给 iPhone；iPhone 自己定位差时（放在中控下方、包里、高楼之间）会改用它，自己定位好时基本不变。

1. 停着车，投屏页右上角「设置」→「常用」→「导航」→ 打开「使用车辆定位」。浏览器问"是否允许使用位置"时点允许（拒绝则开关自动关回去）。CarPlay 会重新连接一次，约 5 秒。
2. **只需做一次**：在中国大陆境内，「使用车辆定位」下面会出现「坐标系」。打开 iPhone 的「指南针」App，看底部的经纬度；再点「坐标系」，两项下面各有一行灰色经纬度，选和指南针**一致**的那一项（另一项会差十几秒）。
3. 想看它是否在工作：「显示 → 画质与兼容 → 显示调试信息」，画面右下角的调试信息多一行「车辆定位 1.0/s · 车速」。行驶中应在 1/s 左右；是 0 表示浏览器没给新位置，这时 iPhone 用自己的定位，和没开一样。

注意：

- 浏览器关掉或切到后台时盒子收不到位置，2.5 秒后停发，iPhone 自动用回自己的定位。
- 有报告说部分特斯拉固件在授权位置后浏览器会崩溃（多为 Intel 的 MCU2）。遇到就关掉这个开关，或在浏览器地址栏撤销本站的位置权限。
- 位置只在盒子内存里经过，不写日志、不保存。
- 觉得导航位置反而变差了，关掉即可，回到 1.3 的状态。

## 十、1.4.1 的变化

- **断线后**：一个正在用的无线 CarPlay 自己断开（干扰、车开出信号好的位置）时，盒子在 45 秒内经蓝牙主动邀请那部 iPhone 一次，不再等它自己回到盒子的 Wi-Fi。只一次、只给那部 iPhone；盒子自己做的断开（长时间不用释放、改显示或定位、关机）不会触发。
- **画面停住**：画面流传到半截卡住超过 10 秒，盒子断开并重连，而不是一直停在最后一帧。
- **触控**：很短的拖动、拖回起点不再被当成轻点。
- **盒子设置页**（`http://100.96.0.1:18080/`）：顶部只在需要你处理时出现提示（蓝牙没启动、缺认证文件、证书不能续签、出错）。点「检查更新」后在「程序更新」里就地转圈，页面自己刷新出结果；邀请、拒绝等结果写在对应分组下面。每行有彩色图标，说明文字改成一句话；手机、车机窄窗、车机全屏、电脑大屏上都核对过排版。没有网络时的提示从"上游不可用"改为"盒子没有网络（没有 4G 信号）"。有新版本时只显示说明的第一段，点「完整更新说明」看全部。
- 操作和地址都没有变化；不需要重新配对或重新申请证书。装着 1.3.1 或更新版本的盒子在设置页点「立即升级」即可。
