# AutoPlay 1.2.0 安装 / 卸载 / 使用说明

> 适用：中兴 F50（MU300，已 Root + OpenWrt 25.12，内核 5.4）上的无线 CarPlay，画面投到特斯拉车机浏览器。
> 1.0.0 是**首个在特斯拉车内实测通过的版本**（无线 CarPlay 画面、触摸、导航播报已验证）；1.0.1 是它的收尾；**1.1.0 把声音默认全部交给特斯拉蓝牙**（见第三节），并引入 DashPlay 10.26–11.01 的可靠性修复；**1.2.0 只改界面**：两张页面按特斯拉的窗口形状核对，下拉与确认框改在页内画（见第六节），功能与 1.1.0 相同。接收端四个 Kotlin 文件自 1.1.0 起未经编译，第一次构建时留意 `receiver/docs/UNVERIFIED-KOTLIN.md`。

---

## 一、安装

### 1. 前置
- F50 已刷 OpenWrt（mu300-linux），后台 `http://192.168.77.1`（root 登录）。
- 盒子需能联网（插 SIM），装依赖要拉 OpenWrt 源。

### 2. 编译安装包（本机）
需要 JDK 21 工具链 + Docker（SDK 镜像 `openwrt/sdk:x86-64-25.12.5`）：

```sh
# 编译接收端（Kotlin/Gradle 9.5.0）
cd receiver && ./gradlew :server:installDist
# 编译投屏页
cd web && npm ci && npm run build
# 打程序包
AUTOPLAY_VERSION=1.2.0 sh box/scripts/build-bundle.sh autoplay-bundle.tar
# 用 Docker SDK 打 apk
sh openwrt/scripts/build-packages.sh out/ autoplay-bundle.tar
```

产物在 `out/`：`autoplay-1.2.0-r1.apk`、`autoplay-jre-*_<架构>.apk`、`luci-app-autoplay-*.apk`、`luci-i18n-autoplay-zh-cn-*.apk`。

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

> 安装时（`90-autoplay-tesla`）会自动完成两件事：
> 1. LAN 从 `192.168.77.1` 切成 **`100.96.0.1/24`**（特斯拉浏览器不认私网地址）。
> 2. 5 GHz 无线设为**中国区 CN / 信道 149**（厂商镜像国家码 TR 不含 149–165，这正是特斯拉搜不到热点的原因）。已经在 149–165 里的信道（例如你在 LuCI 里改成的 157）会保留。
> 3. 两处修改都会让经 Wi-Fi 连着的 SSH 断开一次：LAN 换地址，无线重载。

### 4. 认证身份（投屏前必须）
把 `identity.pk8` + `certificate.p7b` 放到 `/opt/autoplay/identity/offline-mfi/`，`/etc/init.d/autoplay restart`，状态页 `identity` 由 missing 变为 provided。

---

## 二、自有域名证书（可选，消除车机警告）

支持两种 DNS 提供商（LuCI「服务 → AutoPlay → Own address」或命令行 uci）：

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

## 三、声音（1.1.0）

默认 **所有声音走特斯拉蓝牙**：盒子不向 iPhone 提供 CarPlay 音频，音乐、导航播报、通话、Siri 全部由 iPhone 经特斯拉蓝牙播出，CarPlay 页面无声。前提：iPhone 连着特斯拉蓝牙并被选为媒体来源；没连时声音会从 iPhone 自己出来。

经蓝牙听不到导航播报时，改为页面播放（1.0.x 的做法，上车后要轻点页面一次开声音）：LuCI「服务 → AutoPlay → iPhone → 导航播报」选「在 CarPlay 页面」，或

```sh
uci set autoplay.main.audio_route_navigation=carplay   # 改回：bluetooth
uci commit autoplay && /etc/init.d/autoplay restart
```

两种模式下页面都不再播放音乐（行驶中的特斯拉会对播音乐的网页弹横幅并让 CarPlay 反复重连）。细节见 `docs/AUDIO.md`。

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
4. iPhone 靠近盒子，蓝牙 iAP2 自动引导连上 F50 热点。
5. 车机浏览器打开 `https://<域名>:18443/`，即看到 CarPlay 画面；触摸回传。默认模式下页面无声，所有声音从特斯拉蓝牙出来，不需要轻点。

### 关键注意
- 蓝牙必须用私有 BlueZ，**不要 `apk add bluez-daemon`**（会带入不匹配的 6.12 内核模块）。
- **1.1.0 上车第一件事**：开一段导航，确认播报从车机扬声器出来、第一个字没被吃掉；来电、Siri 照常。听不到就切回页面播报（第三节）。
- 盒子需长期有 SIM（证书续期 + 特斯拉联网检测）。
- **1.2.0 上车看一眼界面**：设置 → 夜间模式弹出的是页内选项表（大字、可点）而不是浏览器的小下拉；盒子页点一部手机 → 「删除此 iPhone…」出现确认屏而不是浏览器弹窗。若选项表没有出现，把车机浏览器版本记到 `docs/TESLA.md` 并反馈。
- **在线升级目前不可用**：`update.py` 校验发布签名，而项目还没有自己的发布密钥和软件源（仓库里的公钥仍是上游 DashPlay 的），设置页「程序更新」会报找不到或拒绝。升级请按第一节手动 `apk add` 新包（配对、证书、认证身份都在 `/opt/autoplay/` 下保留）；勿手动覆盖 `/opt/autoplay/{state,identity}`。

## 六、1.2.0 的界面变化（`docs/UI-1.2.0.md`）

- 投屏页设置里的五个下拉（夜间模式、语言、CarPlay 内容大小、帧率、视频编码）改为页内选项表：点行 → 居中列表，每项一行，当前项打勾，「取消」关闭。
- 二级菜单（画质与兼容、连接与兼容性、备用控制；盒子页的手机行）打开时自动滚进视野。
- 盒子设置页（`http://100.96.0.1:18080/`）字号和按钮尺寸与投屏页一致；添加 iPhone 时整页只显示配对码和「一致 / 不一致」；「删除此 iPhone…」「立即升级」先进入确认屏再执行，没有浏览器弹窗。
- 操作和地址都没有变化；不需要重新配对或重新申请证书。
