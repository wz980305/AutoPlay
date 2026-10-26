# AutoPlay (box side)

[中文](README.md)

Turns a **ZTE F50** pocket Wi-Fi router (OpenWrt) into a wireless CarPlay receiver for a Tesla: the car and the iPhone both join the box's 5 GHz access point, the car's browser opens the box's page and gets the picture and touch; music, calls and Siri go over the car's own Bluetooth. The box answers the car's connectivity checks, so the car does not refuse the hotspot for "no internet"; with a SIM card that has data, the car's own apps are online as usual.

AutoPlay is a hard fork of [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) (GPL-3.0) with one target left: **F50 + Tesla**. Other boxes, wired CarPlay and the phone-hotspot modes are gone ([docs/TRIM-LOG.md](docs/TRIM-LOG.md)). The receiver lives in the repository's `receiver/` (PlayPort with the patches applied); this directory is what runs on the box: supervisor, Bluetooth bridge, settings page, and the installer.

> **Not an Apple-certified product.** It needs an accessory identity you provide yourself (below). Flashing carries a risk of bricking the device.

## What you need

- A ZTE F50 (SIM version, stock B16 firmware), a heat sink, an SD card of 8 GB or more that can be wiped, a USB cable that carries data;
- a SIM card with data if the car should be online (CarPlay works without one);
- a computer for the install: Apple-silicon Mac or 64-bit Windows 10/11;
- your own CarPlay accessory identity (below).

## Installing

Send this to your AI assistant (Claude Code, Codex, anything that can run commands on your computer). It follows the [install skill](skills/autoplay-install/SKILL.md) step by step and only calls you to plug something in, press a button or tap on the phone:

> Download the raw text of `box/skills/autoplay-install/SKILL.md` from this repository with curl in the terminal, read all of it, then follow it to install AutoPlay on my F50.

The installer is `scripts/f50-install.py`, one command per stage: `check` (tools, downloads, space) → `flash` (full backup and Root in one download-mode session) → `openwrt` (OpenWrt onto the SD card, stock system kept in slot B) → `autoplay` (this program and Bluetooth; the LAN becomes `100.96.0.1`) → `identity` (your identity files onto the box) → `tesla` (pre-drive checks, optional Wi-Fi country/channel). Every stage ends with `F50_OK` or `F50_STOP <reason>`; a stop stops, nothing is retried against the device.

## In the car

1. The car joins the box's 5 GHz access point (name and password are OpenWrt's wireless settings; the plugin leaves them alone); the iPhone joins too and pairs over Bluetooth (the settings page invites it; the Bluetooth name is `AutoPlay`).
2. The car's browser opens `https://autoplay.lan:18443/` (with a DuckDNS name: `https://<name>.duckdns.org:18443/`, which carries a real certificate so the browser stops warning).
3. The settings page is `http://100.96.0.1:18080/` (`http://100.96.0.2/` redirects there): iPhone, Bluetooth, certificate and update status, invite or remove an iPhone, upgrade, factory reset. LuCI has the same four tabs under Services → AutoPlay.

Seven settings (`/etc/config/autoplay`): enabled, viewer port, idle release seconds, DuckDNS name and token, update check, update mirror. The network stays OpenWrt's; the plugin only sets the LAN to `100.96.0.1/24` and answers the connectivity checks.

Every status carries a reason word (why Bluetooth is not up, how many days the certificate has left, why the program is restarting): [docs/STATUS-MODEL.md](docs/STATUS-MODEL.md).

## Accessory identity

An iPhone only connects to a receiver that presents a valid accessory certificate and signs with the matching private key. Like PlayPort, AutoPlay **neither includes, distributes nor downloads any identity**; the repository, packages, documentation and tests contain no real identity files. The receiver refuses to start without these two files on the box:

```
/opt/autoplay/identity/offline-mfi/identity.pk8       # PKCS#8 EC P-256 private key
/opt/autoplay/identity/offline-mfi/certificate.p7b    # the matching accessory certificate
```

Sources are discussed in [PlayPort's README, "Accessory identity"](https://github.com/youcci/playport#accessory-identity-required). Publicly available identities are shared experimental identities that Apple can revoke at any time; personal experimentation only, do not sell, redistribute or commit them. The installer's `identity` stage puts the files in place, checks that key and certificate match and leaves them readable by root only; the settings page's factory reset removes them only after a second typed confirmation.

## Build and test

The program bundle `autoplay-bundle-<version>.tar` is what the OpenWrt package unpacks to `/opt/autoplay`. Build `receiver/` first (`./gradlew :server:installDist`, `npm run build` for the page), then

```sh
sh box/scripts/build-bundle.sh autoplay-bundle.tar
```

It packs committed files only and downloads two hash-pinned inputs: dbus-next 0.2.3 (the Bluetooth bridge) and acme.sh 3.1.6 (the DuckDNS certificate). The OpenWrt package definitions are in the repository's `openwrt/`.

Tests use the standard library's `unittest` only and no network:

```sh
cd box
python3 -m unittest discover -s tests/onecloud
python3 -m unittest discover -s tests/bluetooth    # test_bluez / test_recovery need dbus-next
```

## Layout

- `scripts/onecloud/`: what runs on the box — `supervisor_openwrt.py` (supervision, status, retries), `run-receiver.py` (starts the JVM), `settings_page.py`, `tesla_openwrt.py` (connectivity checks), `own_domain.py` (DuckDNS + Let's Encrypt), `update.py` (online update and rollback), `board_zte_f50.py` (F50 Bluetooth bring-up)
- `linux/bt-bridge/`: the iAP2 RFCOMM bridge over BlueZ's D-Bus API ([README](linux/bt-bridge/README.md))
- `scripts/f50-install.py`: the installer; `skills/autoplay-install/`: the install guide for an AI assistant
- `docs/`: trim log, status model, test baseline

## License

GPL-3.0, see `LICENSE`; sources and attribution in [NOTICE.md](NOTICE.md). CarPlay, iPhone and AirPlay are trademarks of Apple Inc.; this project is not affiliated with Apple.
