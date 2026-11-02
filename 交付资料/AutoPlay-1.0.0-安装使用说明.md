# AutoPlay 1.0.0 安装 / 卸载 / 使用说明

> 适用：中兴 F50（MU300，已 Root + OpenWrt 25.12，内核 5.4）上的无线 CarPlay，画面投到特斯拉车机浏览器。
> 本版（1.0.0）为**首个在特斯拉车内实测通过的版本**：无线 CarPlay 画面、触摸、导航播报已验证可用。

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
AUTOPLAY_VERSION=1.0.0 sh box/scripts/build-bundle.sh autoplay-bundle.tar
# 用 Docker SDK 打 apk
sh openwrt/scripts/build-packages.sh out/ autoplay-bundle.tar
```

产物在 `out/`：`autoplay-1.0.0-r1.apk`、`autoplay-jre-*_<架构>.apk`、`luci-app-autoplay-*.apk`、`luci-i18n-autoplay-zh-cn-*.apk`。

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
> 2. 5 GHz 无线设为**中国区 CN / 信道 149**（厂商镜像国家码 TR 不含 149–165，这正是特斯拉搜不到热点的原因）。

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

盒子会自动用 DNS-01 挑战通过 DNSPod API 签发 Let's Encrypt 正式证书，并每 90 天自动续期（到期前 30 天）。车机访问 `https://<域名>:18443/` 无警告。无需在 DNSPod 建 A 记录（盒子本地 dnsmasq 会为特斯拉解析该域名）。

---

## 三、卸载

```sh
apk del luci-i18n-autoplay-zh-cn luci-app-autoplay autoplay autoplay-jre
```

注意：iPhone 配对、证书、认证身份文件会保留在 `/opt/autoplay/`；LAN 不会自动改回 `192.168.77.1`（需手动 `uci set network.lan.ipaddr=...`）。

---

## 四、使用

| 入口 | 地址 |
|---|---|
| 设置页 | `http://100.96.0.1:18080/` |
| LuCI 后台 | `http://100.96.0.1/` → 服务 → AutoPlay |
| 车机浏览器 | `https://<域名>:18443/`（或 `https://autoplay.lan:18443/`） |

### 上车步骤
1. **F50 接车上 USB**：5V≥3A、打火不断电的口，短粗线；加散热片/小风扇。
2. **iPhone**：连特斯拉蓝牙并设为媒体来源（音乐/通话/Siri 走特斯拉蓝牙）。
3. **车机 Wi-Fi**：打开「行驶中保持连接」，连 F50 热点 `ZTE_3B3B56`。
4. iPhone 靠近盒子，蓝牙 iAP2 自动引导连上 F50 热点。
5. 车机浏览器打开 `https://<域名>:18443/`，即看到 CarPlay 画面；触摸回传，轻点开启声音。

### 关键注意
- 蓝牙必须用私有 BlueZ，**不要 `apk add bluez-daemon`**（会带入不匹配的 6.12 内核模块）。
- 盒子需长期有 SIM（证书续期 + 特斯拉联网检测）。
- 升级走设置页「程序更新」或 LuCI「更新」，勿手动覆盖 `/opt/autoplay/{state,identity}`。
