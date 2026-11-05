# AutoPlay (box side)

[中文](README.md)

This is the half of AutoPlay that runs on the **ZTE F50 pocket router** (OpenWrt): it supervises the receiver, brings up the F50's Bluetooth, maintains the certificate, gives the owner a settings page, and answers the car's connectivity checks so the car does not leave the box's hotspot for "having no internet". The receiver itself (Kotlin/JVM: speaks CarPlay to the iPhone and relays the picture to the car's browser) lives in the repository's `receiver/`. The project as a whole is described in the [root README](../README.en.md).

This directory comes from [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) (GPL-3.0 hard fork) and keeps one target: F50 + Tesla. Debian, Phicomm N1, Onecloud, wired CarPlay, phone-hotspot and external-router modes are gone; the process is recorded in [docs/TRIM-LOG.md](docs/TRIM-LOG.md).

> **Not an Apple-certified product.** Running it requires your own accessory identity (below).

## What you need

A ZTE F50 (model MU300) **already flashed to [mu300-linux](https://github.com/dikeckaan/mu300-linux)'s OpenWrt image following that project's own documentation**. The unit we verified in the car shipped with stock firmware B13. Flashing, rooting and going back to Android are mu300-linux's business; this repository gives no such steps and makes no claim about which firmware versions can be flashed; upstream DashPlay's flashing scripts for stock B16 were removed on 2026-11-03.

In the car: a SIM with data (certificate issuance and renewal, and the car's connectivity checks, depend on it); 5 V at 3 A or more from a port that stays powered through ignition, a short thick cable; a heatsink. And your own CarPlay accessory identity (below).

## Installing

Four apk packages (`autoplay`, `autoplay-jre`, `luci-app-autoplay` and its Chinese translation) are defined in the repository's `openwrt/` and built with the OpenWrt Docker SDK; copy them to the box, `apk add` them, run `python3 /opt/autoplay/board_zte_f50.py --setup` once so the F50's Bluetooth uses the private BlueZ (do not `apk add bluez-daemon`), place the identity files, restart the service. Full commands: the [install guide](../交付资料/AutoPlay-1.3.2-安装使用说明.md) (Chinese) and [`openwrt/README.en.md`](../openwrt/README.en.md).

The install script (uci-defaults `90-autoplay-tesla`) moves the LAN from `192.168.77.1` to **`100.96.0.1/24`** — a Tesla's browser refuses private addresses but accepts the 100.64/10 range — and sets the 5 GHz radio to country CN / channel 149: the car only finds the hotspot on 149–165, which the mu300-linux image's country code (TR) does not have. A channel you set in LuCI within 149–165 is kept; SSID and password are untouched.

## In the car

1. Join the box's 5 GHz hotspot from the car and turn on "Remain connected in Drive"; pair the iPhone over Bluetooth and make it the media source.
2. The first time, open the settings page at `http://100.96.0.1:18080/`, tap "Add iPhone", tap the box's name in the iPhone's Settings → Bluetooth, and compare the six-digit code on both sides. Afterwards the iPhone is bootstrapped onto the hotspot over Bluetooth iAP2 whenever it comes near.
3. Open `https://<your domain>:18443/` in the car's browser (a DuckDNS name or your own DNSPod-hosted domain; without one it is `https://autoplay.lan:18443/` with a certificate warning).

The settings page shows the hotspot–box–iPhone chain, adds and removes iPhones, shows certificate expiry, offers a diagnostics download and a factory reset; `http://100.96.0.2/` from the car or a phone redirects to it. LuCI's Services → AutoPlay has four tabs: Network, iPhone, Own address (DuckDNS / DNSPod), Program update.

`/etc/config/autoplay` has eleven options: on/off, viewer port, idle-release seconds, DNS provider, DuckDNS name and token, own domain plus DNSPod ID and token, update check, update mirror. Sound has no option: every sound plays on the Tesla's Bluetooth (the `audio_route_navigation` key of 1.1.0–1.2.0 is removed on upgrade, `docs/AUDIO.md`). The network stays OpenWrt's.

Every state carries a reason word (why Bluetooth is down, how many days the certificate has left, why the program restarted): [docs/STATUS-MODEL.md](docs/STATUS-MODEL.md). Program update: since 1.3.1 every version is a signed GitHub Release; `update.py` checks once a day and upgrades on one tap, backing up and downloading the way back first and rolling back if the new version does not come up ([docs/RELEASE.md](../docs/RELEASE.md)); a box on an earlier version joins this chain after one manual install of 1.3.1 or later. Pairings, certificate and identity stay under `/opt/autoplay/`.

## Accessory identity

An iPhone only connects to a receiver that presents a valid accessory certificate and can sign with the matching private key. AutoPlay **ships, distributes and downloads no identity**; there is none in the repository, the packages, the docs or the tests. Without these two files the status page shows `identity: missing` and the receiver does not start:

```
/opt/autoplay/identity/offline-mfi/identity.pk8       # PKCS#8 EC P-256 private key
/opt/autoplay/identity/offline-mfi/certificate.p7b    # the matching accessory certificate
```

How to obtain a legitimate identity is outside this project's scope; a shared identity circulating publicly may be revoked by Apple at any time — do not sell, redistribute or commit one. The files are root-only; the settings page's factory reset deletes them only after a second typed confirmation.

## Build and test

The bundle `autoplay-bundle-<version>.tar` is what the OpenWrt package unpacks to `/opt/autoplay`. Build `receiver/` first (`./gradlew :server:installDist`, and `npm run build` for the page), then from the repository root:

```sh
AUTOPLAY_VERSION=1.4.0 sh box/scripts/build-bundle.sh autoplay-bundle.tar
```

It packs committed files only and downloads two pinned dependencies: dbus-next 0.2.3 (Bluetooth bridge) and acme.sh 3.1.6 with the DuckDNS and DNSPod DNS hooks (certificates).

Tests use the standard library `unittest` only, no network:

```sh
cd box
python3 -m unittest discover -s tests/onecloud      # 238
python3 -m unittest discover -s tests/bluetooth     # test_bluez / test_recovery need dbus-next
```

## Layout

- `scripts/onecloud/` the programs on the box: `supervisor_openwrt.py` (supervision, status, retries), `supervision.py` (per-component restart policy), `status_model.py` (nine status domains), `run-receiver.py` (starts the JVM), `settings_page.py` / `settings_ui.py` (settings page), `pairing_window.py` (pairing), `tesla_openwrt.py` (connectivity checks), `own_domain.py` (DuckDNS / DNSPod + Let's Encrypt), `update.py` (update and rollback), `factory_reset.py`, `board_zte_f50.py` (F50 Bluetooth bring-up), `mu300_boot.py`, `viewer_port.py`
- `linux/bt-bridge/` the iAP2 RFCOMM bridge over BlueZ D-Bus ([README](linux/bt-bridge/README.md))
- `scripts/build-bundle.sh` builds the bundle; `scripts/scan-sensitive.py` scans for personal and secret material before publishing
- `docs/` trim log, status model, test baseline
- `tools/render_settings_states.py` renders the settings page's eight states to static HTML (for `receiver/web/scripts/ui-shots.mjs`)

## License

GPL-3.0, see `LICENSE`; sources and credits in [NOTICE.md](NOTICE.md). CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; Tesla is a trademark of Tesla, Inc. This project is not affiliated with either.
