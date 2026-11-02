# AutoPlay 的 OpenWrt 软件包

[English](README.en.md)

[AutoPlay](../box/README.md) 在 ZTE F50（OpenWrt 25.12，`apk` 装包）上的三个包：

- `autoplay`：程序与开机服务（`/opt/autoplay`、`/etc/init.d/autoplay`、`/etc/config/autoplay`），各架构通用。程序本身是 AutoPlay 发布附带的 `autoplay-bundle-<版本>.tar`（`autoplay/Makefile` 的 `PKG_SOURCE_URL` 与 `PKG_HASH`），本目录不另存源码。
- `autoplay-jre`：Eclipse Temurin 21 JRE 的 musl 版（OpenWrt 没有 Java），aarch64 与 x86_64。
- `luci-app-autoplay`（含中文 `luci-i18n-autoplay-zh-cn`）：后台「服务 → AutoPlay」，一块概览加四个标签页（网络、iPhone、访问名称、更新）。

> **这不是 Apple 认证产品。** 运行需要你自己提供配件认证身份，见 [box/README.md](../box/README.md#认证身份)。

正常情况下不用手动装这些包：[装机脚本](../box/scripts/f50-install.py) 的 `autoplay` 阶段会装好并把 LAN 改成 `100.96.0.1/24`。下面是手动路线和包的行为说明。

## 安装（手动）

```sh
cd /tmp
apk update
apk add --allow-untrusted autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-[0-9]*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk
python3 /opt/autoplay/board_zte_f50.py --setup     # F50 自己的 BlueZ（见下）
```

包没有签名，所以要 `--allow-untrusted`。约 230 MB 存储（Java 占大头）。

安装时（postinst）会：

- 把 LAN 定为 `100.96.0.1/24`（RFC 6598 共享地址段，特斯拉浏览器能打开）、DHCP 给出网关和 DNS；LAN 已经是别的地址时会改，车和手机要重连一次；
- 删掉 DashPlay 时代的 uci 选项和 dhcp 记录，只留七项：`enabled`、`viewer_port`、`idle_release`、`duckdns_domain`、`duckdns_token`、`update_check`、`update_mirror`；
- 从 DashPlay 升级过来时，搬 `/opt/dashplay/{state,identity}` 和独立 BlueZ 到 `/opt/autoplay`，把 `/etc/config/dashplay` 里的选项抄过来（`autoplay` 与 `dashplay` 包互斥，网页升级会先卸载旧包）；
- 预生成 Java 的 AppCDS 归档，开机快几秒。

### F50 的蓝牙

F50 用厂商 5.4 内核，不能装系统的 `bluez-daemon`（它会带入 6.12 的内核模块，装了蓝牙和无线都会坏）。`board_zte_f50.py --setup` 从 F50 自己的官方软件源把 BlueZ 装进独立目录 `/opt/autoplay-bluez`；监管程序总是用它启动蓝牙，起不来会按 10/20/40 秒、之后每 60 秒重试，并在设置页和 LuCI 显示原因。

## 使用

- 设置页：`http://100.96.0.1:18080/`（`http://100.96.0.2/` 也转到这里）。
- 车机浏览器：`https://autoplay.lan:18443/`；填了 DuckDNS 名字就是 `https://<名字>.duckdns.org:18443/`，有 Let's Encrypt 正式证书，不再有警告。
- LuCI「服务 → AutoPlay」：概览（蓝牙、iPhone、证书、更新各一行，带原因）；「网络」看热点和网段；「iPhone」邀请/删除；「访问名称」填 DuckDNS 名字和 token；「更新」检查、升级、改镜像。
- 特斯拉 WiFi 要打开「行驶中保持连接」，否则一出 P 挡就断 WiFi。搜不到热点时把无线地区设为中国、信道 149（装机的 `tesla` 阶段有 `--country`/`--channel`）。

状态与原因词：[box/docs/STATUS-MODEL.md](../box/docs/STATUS-MODEL.md)。

## 升级

后台「服务 → AutoPlay → 更新」或设置页的「程序更新」：每天检查一次，有新版本只提示；点「立即升级」后从 GitHub（连不上时换镜像）下载签名核对过的正式版，CarPlay 使用中不升级，升级前备份配对、证书和设置，计划里出现内核、内核模块或系统蓝牙就停，新版本起不来（接收程序没在约 4 分钟内应答、或蓝牙没上电）就装回原来的版本。升级过程写在 `state/update-journal.json`，中途断电下次开机接着收尾或回退。

手动：`apk update && apk add --upgrade --simulate --allow-untrusted /tmp/autoplay-upgrade/*.apk` 看计划，确认只有用户态包后去掉 `--simulate`。不要卸载重装、不要 sysupgrade、不要覆盖 `/opt/autoplay/{state,identity}`。

## 卸载

```sh
apk del luci-i18n-autoplay-zh-cn luci-app-autoplay autoplay autoplay-jre
```

已添加的 iPhone、证书和认证文件留在 `/opt/autoplay/`，确定不用了再手动删除（或先在设置页「恢复出厂设置」）。LAN 不会改回去。

## 自己打包

需要 Docker（容器不需要特权、主机网络或设备）。

```sh
sh scripts/build-packages.sh out/                         # SDK 从 AutoPlay 发布页下载程序包并校验
sh scripts/build-packages.sh out/ autoplay-bundle.tar     # 或用你自己构建的程序包（box/scripts/build-bundle.sh）
sh scripts/lab-test.sh out/                               # 在干净的 OpenWrt 25.12.5 容器里安装、启动、检查、卸载
sh scripts/bump-autoplay.sh <版本> autoplay-bundle-<版本>.tar   # 发布新版本后更新 autoplay/Makefile 的版本与校验值
```

依赖只写成运行依赖（`EXTRA_DEPENDS`），打包时不编译 Python 或内核模块。

## 许可与商标

GPL-3.0，见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。CarPlay、iPhone、AirPlay 和 MFi 是 Apple Inc. 的商标；本项目与 Apple 无从属或背书关系。
