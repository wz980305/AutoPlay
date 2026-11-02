# AutoPlay

> **1.0.0 (2026-11-02):** The first release validated in a Tesla. Adds Tencent Cloud (DNSPod) support for the own-domain certificate (alongside DuckDNS), and pins the 5 GHz Wi-Fi to China / channel 149 (the vendor image ships country TR, whose rules have no 149–165, which is why a Tesla could not see the hotspot). Receiver, web and OpenWrt package versions are now 1.0.0. Earlier 0.1.x notes below are historical.

[中文](README.md)

AutoPlay is a GPL-3.0 hard fork of [PlayPort](https://github.com/youcci/playport) and [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) / [openwrt-dashplay](https://github.com/yizhixiaoheigou/openwrt-dashplay) with exactly one target: a **ZTE F50** pocket router running OpenWrt ([mu300-linux](https://github.com/dikeckaan/mu300-linux), vendor 5.4 kernel, Unisoc T760), powered from a car USB port, receiving wireless CarPlay from an iPhone and showing it in a **Tesla's** built-in browser.

**Status: engineering skeleton, not yet validated in a car.** On top of the upstream snapshot of 2026-10-25 (DashPlay `e3beae4`, openwrt-dashplay `5f17702`, PlayPort `9a0882d` with its 63 patches replayed as git history), milestone 0.1.0 landed three things: the receiver trimmed to "F50 + Tesla only" with a batch of audit fixes (`receiver/docs/TRIM-LOG.md`); the box side stripped of every other platform and mode, turned into Tesla constants, with per-component supervision, a status model, an update journal with rollback, certificate state and a factory reset, and the packages renamed `autoplay` (`box/docs/TRIM-LOG.md`, `box/docs/STATUS-MODEL.md`); and this repository's tools and docs. **Not verified:** the Kotlin changes were never compiled (no Gradle or network where they were written; `receiver/docs/UNVERIFIED-KOTLIN.md` lists every file and what to check); nothing was installed on an F50; nothing ran in a car. What was verified: the web side (`tsc` clean, esbuild builds, the four `check*.mjs` pass), 225 box-side unit tests, and the tools' syntax checks, unit test and headless render of the probe page. Treat it as a design document with code attached, not as an installable product.

**Not an Apple-certified product.** Running it requires a user-supplied accessory identity. No identity material is included anywhere in this repository, its packages, docs or tests, and none is downloaded automatically. Shared identities circulating publicly may be revoked at any time (`NOTICE.md`, `docs/SECURITY.md`).

## How it works

The F50 runs a 5 GHz hotspot (100.96.0.1/24), bootstraps the iPhone over Bluetooth iAP2, and a JVM receiver forwards the iPhone's H.264 stream unchanged over WSS to the car browser, which decodes it with WebCodecs onto a canvas; touches travel back the same way. Music, calls and Siri go over the Tesla's own Bluetooth; the page only shows the picture and plays navigation prompts. Details in `docs/ARCHITECTURE.md`; reasoning in `docs/DECISIONS.md`.

## Layout

| Directory | Content | Origin |
|---|---|---|
| `receiver/` | Kotlin/JVM receiver (iAP2, AirPlay, MFi signer interface, WSS) and the TypeScript viewer in `receiver/web/`. Trimmed for the Tesla: wired, macOS, microphone uplink, now-playing/artwork/Media Session and the Xpeng fullscreen family are gone; defaults are performance mode off, 1920 cap, 300 mm UI; state-driven hints, recovering veil, full-width sound-unlock bar, rem type scale, iOS 27 appearance, duck/unduck, minimum press. Constants live in `web/src/flags.ts` | PlayPort hard fork with DashPlay's patches as history, plus 22 trim/fix commits |
| `box/` | Box-side Python: procd supervisor (`supervision.py`: per-component restarts, Bluetooth retries at 10/20/40/60 s, receiver liveness probe), F50 Bluetooth bring-up (private BlueZ), the status model `/var/run/autoplay/status.json` (9 domains, each `{state, reason, since}`), settings page (S1/S2 fixed: no "cable" text on the F50, a Bluetooth failure shows a red bar with its reason), Tesla constants (LAN 100.96.0.1/24, connectivity checks always answered, 7 uci keys), DuckDNS back-off and certificate state, update journal and rollback, clock floor, factory reset, installer, tests | DashPlay minus Debian/N1/OneCloud/STA/external/IPv6/local-CA/wired |
| `openwrt/` | OpenWrt 25.12 apk packages: `autoplay` (`/opt/autoplay`, `/etc/init.d/autoplay`, `/etc/config/autoplay`; postinst migrates from `/opt/dashplay`, `CONFLICTS dashplay`), `autoplay-jre` (jlink'd Temurin 21), `luci-app-autoplay` (overview + 4 tabs) | openwrt-dashplay, renamed and trimmed |
| `tools/` | New here: `probe/` (car-browser capability page), `f50/` (hardening script, measurement service, report tool), `car/` (touch-latency method) | AutoPlay |
| `docs/` | Architecture, build, test, roadmap, Tesla notes, security, decision records (Chinese) | AutoPlay |

## Where to start

- Probe the car browser first: `tools/probe/` (one HTML file, open it in the car).
- Week-1 hardening: `tools/f50/harden.sh --dry-run`.
- Measurement: `tools/f50/measure.sh` + `measure-report.py`; touch latency: `tools/car/touch-latency.md`.
- `docs/BUILD.md`, `docs/TEST.md`, `docs/TESLA.md`, `docs/ROADMAP.md`, `docs/SECURITY.md`, `docs/DECISIONS.md`.
- What was trimmed and what is uncompiled: `receiver/docs/TRIM-LOG.md`, `receiver/docs/UNVERIFIED-KOTLIN.md`, `box/docs/TRIM-LOG.md`; the box status words: `box/docs/STATUS-MODEL.md`.

Hardware prerequisites: an F50 on stock firmware B16; flashing and recovery only per mu300-linux's own documentation; a 5 V ≥3 A ignition-switched USB supply with a short cable; a heatsink and a small fan in a shaded spot; a high-endurance microSD; a SIM. Heat and power are the two largest risks of an F50 in a car (hardware review H1, H2).

## License

GPL-3.0 (`LICENSE`). Derived from PlayPort, DashPlay and openwrt-dashplay, themselves derived from DiPlay, xcertplay and WheelPlay; full attribution chain in `NOTICE.md`. CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; no affiliation with or endorsement by Apple or the upstream authors is implied.
