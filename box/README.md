# AutoPlay（盒子端）

[English](README.en.md)

把一台 **ZTE F50 随身 WiFi**（OpenWrt）变成特斯拉用的无线 CarPlay 接收端：车和 iPhone 都连盒子的 5 GHz 热点，车机浏览器打开盒子的网页就有画面和触控；音乐、通话、Siri 走车自带的蓝牙。盒子替车答联网检查，所以车机不会因为"没网"拒绝连热点；插上能上网的 SIM 卡，车机自带的应用也能照常上网。

AutoPlay 是 [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) 的硬分叉（GPL-3.0），只保留一个目标：**F50 + 特斯拉**。其他盒子、有线 CarPlay、借手机热点等模式都已去掉（[docs/TRIM-LOG.md](docs/TRIM-LOG.md)）。接收程序在仓库的 `receiver/`（PlayPort 打好补丁的源码），本目录是盒子上的监管程序、蓝牙桥接、设置页和装机脚本。

> **这不是 Apple 认证产品。** 运行需要你自己提供配件认证身份（见下文）。刷机有风险，操作不当可能变砖。

## 需要什么

- ZTE F50 插卡版（原厂 B16 固件），散热器，8 GB 以上可清空的 SD 卡，能传数据的 USB 线；
- 想让车机上网就再加一张能上网的 SIM 卡（不插也能用 CarPlay）；
- 装机用的电脑：Apple 芯片 Mac 或 64 位 Windows 10/11；
- 你自己的 CarPlay 认证文件（见下文）。

## 怎么装

把下面这句话发给你的 AI 助手（Claude Code、Codex 等能在电脑上运行命令的都行），它会按 [装机 skill](skills/autoplay-install/SKILL.md) 一步步做，只在要你插拔线、按按钮或在手机上点选时叫你：

> 请在终端用 curl 下载本仓库 `box/skills/autoplay-install/SKILL.md` 的原文并完整读完，再按它一步步帮我把 AutoPlay 装到 F50 上。

装机命令是 `scripts/f50-install.py`，一个阶段一条命令：`check`（工具、下载、空间）→ `flash`（完整备份并 Root，一次下载模式会话）→ `openwrt`（OpenWrt 装到 SD 卡，原厂系统保留在 B 槽）→ `autoplay`（本程序和蓝牙，热点改为 `100.96.0.1`）→ `identity`（放入认证文件）→ `tesla`（上车前检查，可选 Wi-Fi 国家码/信道）。每一步以 `F50_OK` 或 `F50_STOP <原因>` 结束，停了就停，不会自己重试写设备。

## 上车

1. 车机连盒子的 5 GHz 热点（名字和密码在 OpenWrt 后台的无线设置里，插件不改），iPhone 也连上并配对蓝牙（设置页会邀请；蓝牙名叫 `AutoPlay`）。
2. 车机浏览器打开 `https://autoplay.lan:18443/`（填了 DuckDNS 名字就是 `https://<名字>.duckdns.org:18443/`，有正式证书，浏览器不再警告）。
3. 设置页在 `http://100.96.0.1:18080/`（车机或手机打开 `http://100.96.0.2/` 也会转到这里）：看 iPhone、蓝牙、证书和更新的状态，邀请或删除 iPhone，升级，恢复出厂设置。OpenWrt 后台「服务 → AutoPlay」有同样的四个标签页。

设置只有七项（`/etc/config/autoplay`）：开关、网页端口、空闲释放秒数、DuckDNS 名字和 token、是否检查更新、更新镜像。网络仍由 OpenWrt 管，插件只把 LAN 定为 `100.96.0.1/24` 并答联网检查。

状态都有一个原因词（蓝牙没起来是为什么、证书还剩几天、程序为什么在重启），见 [docs/STATUS-MODEL.md](docs/STATUS-MODEL.md)。

## 认证身份

iPhone 只连接出示有效配件证书、并能用对应私钥签名的接收端。AutoPlay 与 PlayPort 一样**不附带、不分发、不自动下载任何身份**；仓库、安装包、文档和测试里没有真实身份文件。盒子上缺少这两个文件时接收程序拒绝启动：

```
/opt/autoplay/identity/offline-mfi/identity.pk8       # PKCS#8 EC P-256 私钥
/opt/autoplay/identity/offline-mfi/certificate.p7b    # 对应的配件证书
```

来源见 [PlayPort README 的 Accessory identity 一节](https://github.com/youcci/playport#accessory-identity-required)。公开可得的身份是共享的实验身份，Apple 随时可能使其失效；只用于个人实验，不要出售、再分发或提交到仓库。装机的 `identity` 阶段把文件放到位并核对私钥与证书配对，文件只有 root 可读；设置页的"恢复出厂设置"只有再输入一次确认文字才会删它。

## 构建与测试

程序包 `autoplay-bundle-<版本>.tar` 是 OpenWrt 包解开到 `/opt/autoplay` 的内容：先构建 `receiver/`（`./gradlew :server:installDist`，网页 `npm run build`），再

```sh
sh box/scripts/build-bundle.sh autoplay-bundle.tar
```

它只打包 git 已提交的文件，另下载两份固定哈希的依赖：dbus-next 0.2.3（蓝牙桥接）和 acme.sh 3.1.6（DuckDNS 证书）。OpenWrt 包的定义在仓库的 `openwrt/`。

测试只用标准库 `unittest`，不用网络：

```sh
cd box
python3 -m unittest discover -s tests/onecloud
python3 -m unittest discover -s tests/bluetooth    # test_bluez / test_recovery 需要 dbus-next
```

## 目录

- `scripts/onecloud/` 盒子上的程序：`supervisor_openwrt.py`（监管、状态、重试）、`run-receiver.py`（启动 JVM）、`settings_page.py`（设置页）、`tesla_openwrt.py`（联网检查）、`own_domain.py`（DuckDNS + Let's Encrypt）、`update.py`（在线升级与回退）、`board_zte_f50.py`（F50 蓝牙启动）
- `linux/bt-bridge/` BlueZ D-Bus 的 iAP2 RFCOMM 桥接（[说明](linux/bt-bridge/README.md)）
- `scripts/f50-install.py` 装机；`skills/autoplay-install/` 给 AI 助手的装机说明
- `docs/` 修剪记录、状态模型、测试基线

## 许可

GPL-3.0，见 `LICENSE`；来源与致谢见 [NOTICE.md](NOTICE.md)。CarPlay、iPhone、AirPlay 是 Apple Inc. 的商标；本项目与 Apple 无关。
