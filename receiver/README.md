# AutoPlay receiver

The part of AutoPlay that talks to the iPhone and to the car's browser. It is a Kotlin/JVM program, a hard fork of [PlayPort](https://github.com/youcci/playport) (commit `9a0882d`) with [DashPlay](https://github.com/yizhixiaoheigou/DashPlay)'s 63 patches replayed as git history, then trimmed to one target: a ZTE F50 running OpenWrt, a Tesla, an iPhone. The project-level README is [`../README.md`](../README.md); this file is about the receiver itself.

## What it does

Two modules:

- `protocol/` — the CarPlay stack inherited from DiPlay/xcertplay: iAP2 over Bluetooth (pairing, the Wi-Fi credential hand-over, session start), AirPlay/CarPlay over Wi-Fi (RTSP, pairing, the video and touch streams), and the MFi authentication exchange against a user-supplied accessory identity.
- `server/` — the receiver proper: the AirPlay server, the Bluetooth bootstrap through the box's `bt-bridge` helper, the display negotiation (view areas for the browser's window shapes), and a WSS server that serves the viewer page in `web/` and relays video, touch and session state to it.

Video is forwarded as the iPhone sends it, H.264 or H.265, never decoded here; the browser decodes with WebCodecs. Audio: with `--audio-route-navigation bluetooth` (what the box passes by default since 1.1.0) the receiver offers the iPhone no audio formats, so every sound stays on the car's Bluetooth; with `carplay` the navigation prompt and alert streams are relayed to the page, which plays them. Telephony, Siri and the microphone are never offered in either mode. `../docs/AUDIO.md` has the details.

What the trim removed, and why: `docs/TRIM-LOG.md`. The Kotlin changes made since 1.0.0 without a compiler at hand: `docs/UNVERIFIED-KOTLIN.md` — `./gradlew build` is the first thing to run on a machine with a Gradle network.

## Building

JDK 21. `settings.gradle.kts` allows Maven Central only.

```sh
cd receiver
./gradlew build                 # compiles both modules and runs their tests
./gradlew :server:installDist   # server/build/install/server/{bin,lib} → /opt/autoplay/playport/lib on the box
```

The viewer page is built separately (`web/README-build.md`): `npm ci && npm run build`, or `npm run build:offline` with a preinstalled esbuild; `npm test` runs its five check scripts.

## Running

On the box the receiver is not started by hand: `box/scripts/onecloud/run-receiver.py` writes the receiver's `config.json` (viewer port 18443 with TLS, display defaults) and starts the JVM with the flags below, under the procd service `autoplay`. The flags are listed here for reading logs and for running the server on a desk:

| Flag | Default | Meaning |
|---|---|---|
| `--device-name <name>` | `PlayPort` | AirPlay device name shown on the iPhone |
| `--model`, `--manufacturer` | `playport` | AirPlay model / manufacturer strings |
| `--airplay-port <port>` | 7000 | AirPlay RTSP port |
| `--http-port <port>` | 8080 | viewer page and WebSocket (the box sets 18443) |
| `--width`, `--height`, `--fps` | 1280, 720, 60 | display negotiated with the phone; the page adapts them at runtime |
| `--ui-scale <75\|85\|100\|115>` | 85 | CarPlay content size as the physical width told to the phone (350/300/250/200 mm; 85 = 300 mm, the Tesla default) |
| `--hevc` | off | offer H.265 (the page asks for it when the browser decodes it) |
| `--rhd` | off | right-hand-drive layout |
| `--audio-route-navigation <carplay\|bluetooth>` | `carplay` in code; the box passes `bluetooth` | see above |
| `--bind <address>` | auto | bind address |
| `--identity-dir <path>` | `./identity` | directory containing `offline-mfi/` (see `identity/README.md`) |
| `--state-dir <path>` | `~/.playport` | AirPlay identity and pairing state (the box uses `/opt/autoplay/state`) |
| `--wireless` | off | enable the Bluetooth bootstrap |
| `--wifi-ssid`, `--wifi-passphrase`, `--wifi-channel`, `--wifi-security <open\|wpa\|wpa2\|wpa3>` | —, —, 0, `wpa2` | the hotspot handed to the phone |
| `--bt-address <mac>` | — | iPhone Bluetooth address for the bootstrap |
| `--bt-bridge <path>` | — | the box's Bluetooth RFCOMM relay (`linux-bt-bridge/bt-bridge`) |
| `--mdns <jmdns\|off>` | `jmdns` | mDNS backend |
| `--http` | off | plain HTTP instead of TLS (WebCodecs then works only on localhost) |
| `--token <token>` | generated per start | browser access token; the box writes it to `receiver-access.json` for the page |

The first-time Bluetooth pairing uses PIN `3939` when the phone asks for one; in practice the box's settings page drives pairing and shows the passkey.

## Layout

```
protocol/   iAP2, AirPlay, MFi (com.shilapi.xcertplay.*)
server/     the receiver (com.playport.server.*), tests
web/        the viewer page (TypeScript), its check scripts, build scripts
identity/   where the user's accessory identity goes; git-ignored except its README
docs/       TRIM-LOG.md, UNVERIFIED-KOTLIN.md
```

## Status

1.0.0 ran in a 2022 Tesla Model 3 (AMD MCU) with an iPhone 15 Pro on iOS 27.2 on 2026-11-02. The receiver runs on Linux/JVM only; the macOS support of upstream PlayPort was removed. Kotlin changes since then are uncompiled (`docs/UNVERIFIED-KOTLIN.md`).

## Identity, license, credits

CarPlay requires an MFi-authenticated accessory. This repository contains no identity material and the software downloads none; the two files the receiver reads are described in `identity/README.md`, and how to obtain a legitimate pair is outside this project's scope. GPL-3.0; the attribution chain (PlayPort, DashPlay, DiPlay, xcertplay, WheelPlay) is in `NOTICE.md` and `../NOTICE.md`. CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; Tesla is a trademark of Tesla, Inc.
