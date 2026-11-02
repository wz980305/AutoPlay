---
name: autoplay-install
description: 装 AutoPlay 到一台已经运行 mu300-linux OpenWrt 的中兴 F50 上。刷机、root、回安卓不在此处。
---

# AutoPlay 装机说明（1.2.0）

这里原来是上游 DashPlay 的装机向导（面向原厂 B16 固件的 F50、斐讯 N1、玩客云和 Debian），内容与本项目的做法已不一致，于 2026-11-03 移除。AutoPlay 的安装只有一条路线，完整步骤在仓库的
[`交付资料/AutoPlay-1.2.0-安装使用说明.md`](../../../交付资料/AutoPlay-1.2.0-安装使用说明.md)，要点：

1. **刷机只看 [mu300-linux](https://github.com/dikeckaan/mu300-linux) 自己的文档**（我们实测的 F50 原厂固件是 B13）。本仓库不写刷机、root 步骤，也不判断哪个固件版本能刷（`docs/DECISIONS.md` ADR-11）。
2. 在电脑上构建接收端与投屏页，用 OpenWrt 的 Docker SDK 打出四个 apk（`openwrt/README.md`）。
3. 把包推到盒子上 `apk add --allow-untrusted`，跑一次 `python3 /opt/autoplay/board_zte_f50.py --setup`（F50 私有 BlueZ，切勿 `apk add bluez-daemon`），重启服务。安装脚本会把 LAN 改成 `100.96.0.1/24`、把 5 GHz 设为 CN / 149。
4. 把你自己的配件认证文件放到 `/opt/autoplay/identity/offline-mfi/`。本项目不提供、不下载、不说明如何取得身份。
5. 车上：Wi-Fi 连热点并打开「行驶中保持连接」，蓝牙连 iPhone 并选为媒体来源，在 `http://100.96.0.1:18080/` 添加 iPhone，浏览器打开 `https://<你的域名>:18443/`。

同目录的 `downloads.json`、`requirements-f50.txt` 和 `box/scripts/f50-*.py`、`prepare-*.py` 属于被移除的上游流程，未被使用。
