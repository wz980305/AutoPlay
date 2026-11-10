# AutoPlay（盒子端）

[English](README.en.md)

这是跑在 **中兴 F50 随身 WiFi**（OpenWrt）上的那一半 AutoPlay：守护接收程序、拉起 F50 的蓝牙、维护证书、给车主一张设置页，并替车机应答联网检查，这样车机不会因为"这个 Wi-Fi 没网"而拒绝停留在盒子的热点上。接收程序本身（Kotlin/JVM，和 iPhone 讲 CarPlay、把画面转给车机浏览器）在仓库的 `receiver/`。项目的整体说明在 [仓库根目录的 README](../README.md)。

本目录来自 [DashPlay](https://github.com/yizhixiaoheigou/DashPlay)（GPL-3.0 硬分叉），只保留一个目标：F50 + 特斯拉。Debian、斐讯 N1、玩客云、有线 CarPlay、借手机热点、外接路由等模式都已去掉，过程记在 [docs/TRIM-LOG.md](docs/TRIM-LOG.md)。

> **这不是 Apple 认证产品。** 运行需要你自己提供配件认证身份（见下文）。

## 需要什么

一台中兴 F50（型号 MU300），**已经按 [mu300-linux](https://github.com/dikeckaan/mu300-linux) 的文档刷成它的 OpenWrt 镜像**。我们实测的那台原厂固件是 B13。刷机、root、回安卓只看 mu300-linux 自己的说明，本仓库不写这些步骤，也不判断哪个固件版本能刷；上游 DashPlay 面向 B16 原厂固件的刷机脚本已于 2026-11-03 删除。

车上还要：一张能上网的 SIM 卡（证书签发和续期、车机的联网检测都靠它）；5 V、3 A 以上、打火不断电的 USB 供电，短而粗的线；散热片。以及你自己的 CarPlay 认证文件（见下文）。

## 怎么装

四个 apk 包（`autoplay`、`autoplay-jre`、`luci-app-autoplay` 和它的中文翻译）由仓库的 `openwrt/` 定义，用 OpenWrt 的 Docker SDK 打出来，推到盒子上 `apk add`，再跑一次 `python3 /opt/autoplay/board_zte_f50.py --setup` 让 F50 的蓝牙用上私有的 BlueZ（不要 `apk add bluez-daemon`），放好认证文件，重启服务。完整命令在 [安装使用说明](../交付资料/AutoPlay-1.3.2-安装使用说明.md) 和 [`openwrt/README.md`](../openwrt/README.md)。

安装脚本（uci-defaults `90-autoplay-tesla`）会把 LAN 从 `192.168.77.1` 改成 **`100.96.0.1/24`**——特斯拉的浏览器打不开私网地址，100.64/10 这段可以——并把 5 GHz 无线设为中国区 CN / 信道 149：实车只在 149–165 上搜得到热点，而 mu300-linux 镜像的国家码 TR 没有这些信道。你在 LuCI 里改到 153–165 的信道会保留；SSID 和密码不动。

## 上车

1. 车机 Wi-Fi 连盒子的 5 GHz 热点，打开"行驶中保持连接"；蓝牙连 iPhone 并选为媒体来源。
2. 第一次使用，在设置页 `http://100.96.0.1:18080/` 点「添加 iPhone」，在 iPhone 的「设置 → 蓝牙」里点盒子的名字，两边核对六位配对码。之后 iPhone 靠近就会被蓝牙 iAP2 引导连上热点。
3. 车机浏览器打开 `https://<你的域名>:18443/`（DuckDNS 名字或 DNSPod 托管的自有域名；没设域名时是 `https://autoplay.lan:18443/`，车机会报证书警告）。

设置页能看到热点、盒子、iPhone 三者的状态，添加或删除 iPhone，看证书有效期，下载诊断记录，恢复出厂设置；车机或手机打开 `http://100.96.0.2/` 也会转到它。OpenWrt 后台「服务 → AutoPlay」有四个标签页：网络、iPhone、自己的网址（DuckDNS / DNSPod）、程序更新。

`/etc/config/autoplay` 一共十一项：开关、网页端口、空闲释放秒数、DNS 服务商、DuckDNS 名字和 token、自有域名和 DNSPod 的 ID 与 token、是否检查更新、更新镜像。声音没有选项：所有声音都走特斯拉蓝牙（1.1.0–1.2.0 的 `audio_route_navigation` 键升级时会被删掉，`docs/AUDIO.md`）。网络仍由 OpenWrt 管。

每个状态都带一个原因词（蓝牙为什么没起来、证书还剩几天、程序为什么在重启），见 [docs/STATUS-MODEL.md](docs/STATUS-MODEL.md)。程序更新：从 1.3.1 起每个版本都是签过名的 GitHub Release，`update.py` 每天检查一次、车主点一下就升级，升级前备份并下载退路，起不来自动退回（[docs/RELEASE.md](../docs/RELEASE.md)）；更早版本的盒子手动装一次 1.3.1 或更新的版本后接上这条链。配对、证书、身份文件都保留在 `/opt/autoplay/` 下。

## 认证身份

iPhone 只连接出示有效配件证书、并能用对应私钥签名的接收端。AutoPlay **不附带、不分发、不自动下载任何身份**；仓库、安装包、文档和测试里没有身份文件。盒子上缺少这两个文件时，状态页的 `identity` 停在 `missing`，接收程序不会启动：

```
/opt/autoplay/identity/offline-mfi/identity.pk8       # PKCS#8 EC P-256 私钥
/opt/autoplay/identity/offline-mfi/certificate.p7b    # 对应的配件证书
```

怎样取得合法的身份不在本项目讨论范围内；公开流传的共享身份 Apple 随时可能使其失效，不要出售、再分发或提交到仓库。文件只有 root 可读；设置页的"恢复出厂设置"只有再输入一次确认文字才会删它。

## 构建与测试

程序包 `autoplay-bundle-<版本>.tar` 是 OpenWrt 包解开到 `/opt/autoplay` 的内容：先构建 `receiver/`（`./gradlew :server:installDist`，网页 `npm run build`），再在仓库根目录

```sh
AUTOPLAY_VERSION=1.4.3 sh box/scripts/build-bundle.sh autoplay-bundle.tar
```

它只打包 git 已提交的文件，另下载两份固定哈希的依赖：dbus-next 0.2.3（蓝牙桥接）和 acme.sh 3.1.6 连同 DuckDNS 与 DNSPod 两个 DNS 钩子（证书）。

测试只用标准库 `unittest`，不用网络：

```sh
cd box
python3 -m unittest discover -s tests/onecloud      # 238 个
python3 -m unittest discover -s tests/bluetooth     # test_bluez / test_recovery 需要 dbus-next
```

## 目录

- `scripts/onecloud/` 盒子上的程序：`supervisor_openwrt.py`（监管、状态、重试）、`supervision.py`（分组件重启策略）、`status_model.py`（九个状态域）、`run-receiver.py`（启动 JVM）、`settings_page.py` / `settings_ui.py`（设置页）、`pairing_window.py`（配对）、`tesla_openwrt.py`（联网检查）、`own_domain.py`（DuckDNS / DNSPod + Let's Encrypt）、`update.py`（升级与回退）、`factory_reset.py`、`board_zte_f50.py`（F50 蓝牙启动）、`mu300_boot.py`、`viewer_port.py`
- `linux/bt-bridge/` BlueZ D-Bus 的 iAP2 RFCOMM 桥接（[说明](linux/bt-bridge/README.md)）
- `scripts/build-bundle.sh` 打程序包；`scripts/scan-sensitive.py` 发布前的敏感信息扫描
- `docs/` 修剪记录、状态模型、测试基线
- `tools/render_settings_states.py` 把设置页的八个状态渲染成静态 HTML（配合 `receiver/web/scripts/ui-shots.mjs` 截图）

## 许可

GPL-3.0，见 `LICENSE`；来源与致谢见 [NOTICE.md](NOTICE.md)。CarPlay、iPhone、AirPlay、MFi 是 Apple Inc. 的商标，Tesla 是 Tesla, Inc. 的商标；本项目与 Apple、Tesla 无关。
