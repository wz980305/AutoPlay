# AutoPlay

[中文](README.md)

AutoPlay is a GPL-3.0 hard fork of [PlayPort](https://github.com/youcci/playport) and [DashPlay](https://github.com/yizhixiaoheigou/DashPlay) / [openwrt-dashplay](https://github.com/yizhixiaoheigou/openwrt-dashplay) with exactly one target: a **ZTE F50** pocket router running OpenWrt ([mu300-linux](https://github.com/dikeckaan/mu300-linux), vendor 5.4 kernel, Unisoc T760), powered from a car USB port, receiving wireless CarPlay from an iPhone and showing it in a **Tesla's** built-in browser.

**Status: engineering skeleton, not yet validated in a car.** The receiver, box side and OpenWrt packages are the upstream snapshot of 2026-10-25 (DashPlay `e3beae4`, openwrt-dashplay `5f17702`, PlayPort `9a0882d` with its 63 patches replayed as git history), plus this repository's tools and documentation. Nothing in this milestone has run in a vehicle, and the Kotlin changes were not compiled in the authoring environment (see `receiver/docs/UNVERIFIED-KOTLIN.md`). Treat it as a design document with code attached, not as an installable product.

**Not an Apple-certified product.** Running it requires a user-supplied accessory identity. No identity material is included anywhere in this repository, its packages, docs or tests, and none is downloaded automatically. Shared identities circulating publicly may be revoked at any time (`NOTICE.md`, `docs/SECURITY.md`).

## How it works

The F50 runs a 5 GHz hotspot (100.96.0.1/24), bootstraps the iPhone over Bluetooth iAP2, and a JVM receiver forwards the iPhone's H.264 stream unchanged over WSS to the car browser, which decodes it with WebCodecs onto a canvas; touches travel back the same way. Music, calls and Siri go over the Tesla's own Bluetooth; the page only shows the picture and plays navigation prompts. Details in `docs/ARCHITECTURE.md`; reasoning in `docs/DECISIONS.md`.

## Layout

| Directory | Content | Origin |
|---|---|---|
| `receiver/` | Kotlin/JVM receiver (iAP2, AirPlay, MFi signer interface, WSS) and the TypeScript viewer in `receiver/web/` | PlayPort hard fork with DashPlay's patches as history |
| `box/` | Box-side Python: procd supervisor, F50 Bluetooth bring-up (private BlueZ), settings page, Tesla mode, DuckDNS certificate, update, installer, tests | DashPlay |
| `openwrt/` | OpenWrt 25.12 apk packages: program, jlink'd Temurin 21 JRE, LuCI app | openwrt-dashplay |
| `tools/` | New here: `probe/` (car-browser capability page), `f50/` (hardening script, measurement service, report tool), `car/` (touch-latency method) | AutoPlay |
| `docs/` | Architecture, build, test, roadmap, Tesla notes, security, decision records (Chinese) | AutoPlay |

## Where to start

- Probe the car browser first: `tools/probe/` (one HTML file, open it in the car).
- Week-1 hardening: `tools/f50/harden.sh --dry-run`.
- Measurement: `tools/f50/measure.sh` + `measure-report.py`; touch latency: `tools/car/touch-latency.md`.
- `docs/BUILD.md`, `docs/TEST.md`, `docs/TESLA.md`, `docs/ROADMAP.md`, `docs/SECURITY.md`, `docs/DECISIONS.md`.

Hardware prerequisites: an F50 on stock firmware B16; flashing and recovery only per mu300-linux's own documentation; a 5 V ≥3 A ignition-switched USB supply with a short cable; a heatsink and a small fan in a shaded spot; a high-endurance microSD; a SIM. Heat and power are the two largest risks of an F50 in a car (hardware review H1, H2).

## License

GPL-3.0 (`LICENSE`). Derived from PlayPort, DashPlay and openwrt-dashplay, themselves derived from DiPlay, xcertplay and WheelPlay; full attribution chain in `NOTICE.md`. CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; no affiliation with or endorsement by Apple or the upstream authors is implied.
