# Tesla-only trim of the receiver (branch `receiver-trim`, 2026-10-26)

Base: `c138aae` (PlayPort `9a0882d` + DashPlay's 63 patches, one commit each, plus the box/openwrt import). Target: one
product, one mode: a ZTE F50 (OpenWrt) showing wireless CarPlay in a Tesla's built-in browser, with music, calls and
Siri on the car's own Bluetooth. Design inputs: `tesla_only_web_delta.md`, `tesla_only_box_delta.md` (D3, D5, D8, D9,
F1, F3), `code_inventory_trimming.md` (receiver rows), `viewer_ui_audit.md` (V1–V22, §12, §13),
`media_performance_audit.md` (#2, #6, #8, #16), `reliability_audit.md` (#7), `borrowability.md` §2e.1.

Only `receiver/` was touched. The Kotlin side is **not compiled** here (no Gradle offline); see
[UNVERIFIED-KOTLIN.md](UNVERIFIED-KOTLIN.md) for every Kotlin file and why. The web side is verified: `tsc` clean,
esbuild builds, all `check*.mjs` pass (`web/README-build.md`).

## Size

`git diff --shortstat c138aae...HEAD -- receiver`: **68 files changed, 1000 insertions(+), 5936 deletions(-)**.

| Part | Before | After | Note |
|---|---|---|---|
| Kotlin, main (`protocol/src/main` + `server/src/main`) | 16,908 | 12,941 | −3,967 (wired 2,960; macOS 74 + dns-sd; dead 498; mic 230; now-playing 65; the rest edits) |
| Kotlin, tests | 2,925 | 2,503 | −422 (wired-free already; dead-code, mic and now-playing tests) |
| Web source (`src/`, `index.html`, `public/`) | 3,040 | 2,732 | −308 net: ≈ −640 deleted (mic 225, media session 109, flac 75, fullscreen family ≈ 90, custom size, QR), ≈ +330 added (recovering, state hints, duck, flags, status module, min press) |
| `index.html` on the wire | 41,354 B | 9,405 B | the two QR data URIs |
| Web checks (`check*.mjs`) | 592 | 592 | −33 (check-flac), −≈ 40 (Media Session), + Tesla defaults, status hints, duck, min press, browser-check |
| Swift (`macos/`) | 341 | 0 | |

## Deleted (and why it was safe)

| Item | Files | Evidence |
|---|---|---|
| Wired (USB) CarPlay | `WiredBootstrap.kt`; `Iap2UsbMuxHost`, `UsbMuxPipe`, `TlsDuplexChannel`, `LockdownCarKitClient/PairRecord/PairingClient/PlistChannel/TlsEngineFactory`, `Iap2WiredControlClient`, `Iap2ControlDeadline`; kxml2; `--usb-bridge`; `web/src/flac-mp4.ts`, `check-flac.mjs`; the FLAC music kind | The F50 has no USB host for an iPhone; the wired path was a WheelPlay port driven by a Python bridge polling sysfs forever (inventory #3). |
| macOS build | `macos/bt-bridge/`, `WifiInfo.kt`, `DnsSdAdvertiser` + the `os.name` probe, the `macos/` path candidates of `BluetoothBridge.resolvePath` | The box always passes `--wifi-ssid/--wifi-channel/--bt-bridge`; `--mdns` is `jmdns` (default) or `off`. |
| Dead code | `RemoteMfiAuthenticationClient` (+test, `--mfi-server/--mfi-token`), `CarPlayClusterDisplay` (+test), `CarPlayPlaybackStatus` | No caller (inventory #5). `KeystoreRewrap.java` lived in DashPlay's scripts, not here. |
| Microphone uplink (D3) | `mic.ts`, `MicUplink.kt`, `MicrophonePacketizer.kt` (+test), WebBridge/WebHub mic members, `MicrophoneConfig`/`microphoneConfig`, the `mic` message, `MIC_FRAME_*`, `ws.ts sendBinary` | With calls and Siri on the car's Bluetooth `/info` offers no input format and no telephony/speechRecognition stream, so the phone can never open the uplink. `carVoice` became that constant (`AirPlayInfoPlist.audioFormats`). |
| Now-playing / artwork / Media Session (D5) | `media-session.ts`, `NowPlaying.kt` (+test), `nowPlayingFeed`, the `now-playing`/`artwork` messages | The Tesla's own media card shows the song; the page's Media Session was already constructed passive (every method a no-op). **Kept** the iAP2 artwork drain (below). |
| Xpeng DOM-fullscreen family (D9) | `requestFullscreen` state machine, `fullscreenchange`, reverse-camera restore hint and capture-phase tap, the glass button over the picture and its corner setting (`f50-fullscreen-button`) | The Tesla browser ignores `requestFullscreen`; reverse gear freezes the tab instead of hiding it. The Tesla hop stays in the welcome row and the sheet. |
| Author QR block | two 112 px data-URI images, `.follow` CSS, three i18n strings | Fork; brightest elements at night (V11). Attribution moved to [NOTICE.md](../NOTICE.md). |
| Custom resolution | the switch (`f50-auto-fit`), width/height fields, `range` error | A Tesla yields two known shapes; the automatic path is the tested one. fps and codec moved under Advanced. |
| Car flags | `receiver-access.json` `carMusic`/`tesla`, `boot.ts` parsing, `main.ts` branches, `ServerConfig.carVoice` | Constants in `web/src/flags.ts` (`CAR_MUSIC`, `TESLA`, `PROMPT_BOOST = 3`) and the protocol. `--car-voice` is accepted and ignored for one release (the box's launcher still passes it). |
| Fallback controls previous/play/next | three buttons and the `media` branch of the fallback handler | The car's own keys over Bluetooth AVRCP. |

## Kept against the plan (hidden dependencies)

| Item | Why it stays |
|---|---|
| `transport/IphoneUsbException.kt` | Listed as wired; thrown by `Iap2WirelessControlClient` and `Iap2IdentificationClient` (timeouts). |
| `transport/Iap2LocationClient.kt` (+test) | Listed as dead; `Iap2LocationProvider` and `Iap2LocationMessages` are part of `Iap2WirelessControlClient.run` (the phone's Start/StopLocationInformation). Removing them means surgery in the wireless control client, not worth an unverified compile. |
| `Iap2ArtworkReceiver` (+test) | The iPhone keeps starting artwork file transfers on the tunneled iAP2 link; 256 undrained transfers terminate the link (`Iap2LinkChannel.kt`). `CarPlayServer.artworkDrain` runs the receiver with `complete = { false }` and no `expect()`, so every packet leaves the queue and each transfer is declined. |
| `AirPlayHid.telephonyHidDevice`, `sendTelephony`, the `"telephony"` input route | Three harmless lines; the HID declaration is part of the tested `/info`. |
| `compat-display.ts`, the decode-backlog skip, `frameRateCheck` | Needed by Chrome 113 / MCU2 Teslas; never hard-wired either way (web delta items 11, 12). |

## Frozen (kept, not developed)

| Item | Switch | Note |
|---|---|---|
| MSE music path (`music-output.ts`, `aac-mp4.ts`, the element branch of `audio.ts`, `musicTimeline`) | `MUSIC_ELEMENT` in `web/src/flags.ts` (default `true`) | The iPhone sends ~27 s of music here after Siri; whether the Web Audio path carries it acceptably is a listening test still to do. With `false`, AAC decodes into Web Audio at a 1.0 s target (`audio-timing.ts`). |
| View areas (`display-fit.ts` `areaPlan` family, `DisplayState.areas`, `AirPlayViewArea`, `ViewAreaTest`, the `check-car.mjs` blocks) | — | Dead on the page since `window-renegotiate` (2026-10-23); the author said it may return (F3). A two-shape landscape revival is the measured follow-up. |

## Fixes (each its own commit)

| # | Commit | What |
|---|---|---|
| 3a | `285aa00` | `pairings.properties` written temp + fsync + rename, previous copy kept as `.bak`, no re-save while loading, `.bak` fallback (reliability #7). |
| 3b | `8656c5b` | Netty `childOption(IP_TOS, 0x88)` (DSCP AF41) on the viewer HTTPS/WSS (media #6). |
| 3c | `09576c7` | Performance mode off by default; auto resolution capped at 1920 unless fast decoder AND `f50-allow-2560` (Advanced switch); UI size default 300 mm (`ServerConfig.DEFAULT_UI_SCALE = 85`); night `schedule`, prompt boost 3, idle close constants. |
| 3d | `272ba4a` | Recovering state: 40 % veil + persistent 26 px notice over the held frame, cross-fade on the first new frame (V1). |
| 3e | `937c10c` | Hint as a function of state (`src/status.ts`, asserted), `renegotiating` state, elapsed seconds, box link hidden while the box is unreachable (V3). |
| 3f | `1948f30` | Sound-unlock full-width bottom bar, 28 px, shown only while suspended AND a page-played stream arrived (V7). |
| 3g | `942b971` | Canvas `alpha:false`; `desync` (whether `desynchronized` took) in the 10 s stats (media #8). |
| 3h | `4f447ff` | `html{font-size:clamp(18px,1.9vmin,26px)}`, chrome in rem per §13 tokens, welcome card `min(720px,60vw)`, targets ≥ 3.5rem, toast bottom-centre 1.3rem, no backdrop-filter over the picture (V4). |
| 3i | `4d538d5` | iOS 27 appearance: `enablesUIAppearance/enablesMapAppearance`, `uiAppearanceUpdate`+`mapAppearanceUpdate` (2,2 dark / 1,1 light) for iOS ≥ 27, `setNightMode` always; per-phone iOS major in `phone-ios.properties`; the four DiPlay `*AppearanceMode = 0` keys removed (design from the dashplay-tesla fork). |
| 3j | `8cde6de` | `duckAudio`/`unduckAudio` → `{type:"duck", level, ms}`; the page ramps the Web Audio media gain (and the element volume behind `MUSIC_ELEMENT`); counts logged (media #2). |
| 3k | `932af55` | 30 ms minimum press; all-up on `pagehide`/hidden from the page and on viewer close/pause from the box (media #16). The HID single-thread executor was not done (not trivial blind). |

## i18n and brand

`f6b182c`: every driver-visible string through `t()` (voice labels, brand), `accessHint`/box/settings strings rewritten
for AutoPlay, `browser-check.js` rewritten as the driver-facing bilingual version (headline, plain-words missing
capability, Tesla advice, details disclosure; still ES5), language storage guarded. `884d9f6`: "DashPlay" → "AutoPlay"
in the web UI and i18n only.

## Follow-ups not in this branch

- Compile and run the Kotlin (UNVERIFIED-KOTLIN.md lists what to watch on a box).
- The Tesla-specific additions of `tesla_only_web_delta.md` item 21 beyond the viewport-based borderless test that
  landed: the "Remain Connected in Drive" reminder, a one-time UA/panel log, the Tesla detect, a prompt-gain slider.
- The box side (`box/`, `openwrt/`) still writes `carMusic`/`tesla` into `receiver-access.json` and passes
  `--car-voice`; both are ignored now and can go with the box trim.
- `receiver/README.md` is still upstream PlayPort's (macOS) README with a fork notice on top; a Tesla-only README is
  the box trim's job once the install path is final.

## Since this log was written (as of 1.3.0, 2026-11-05)

- The frozen MSE music path behind `MUSIC_ELEMENT` is gone: 1.1.0 deleted `music-output.ts` and `aac-mp4.ts`, and
  `flags.ts` now has `PAGE_PLAYS_MUSIC = false` — the page never plays music (ADR-14, `../../docs/AUDIO.md`).
- "Music, calls and Siri on the car's Bluetooth" became "every sound, navigation prompts included" with the 1.1.0
  default `audio_route_navigation=bluetooth`; 1.3.0 removed the `carplay` alternative and with it the whole page-audio
  path (`audio.ts`, `audio-timing.ts`, `check-audio.mjs`, the unlock bar, the volume slider, `CAR_MUSIC`,
  `PAGE_PLAYS_MUSIC`, `PROMPT_BOOST`, `boot.ts playportPageAudio`), the HUD's sound line and the browser check's two
  audio rows (ADR-16). The receiver always sets `disableAudioOutput = true`; its wire-level audio relay is dormant.
- `--car-voice` and `--audio-route-navigation` are accepted and ignored; `run-receiver.py` passes both for receiver
  builds before 1.3.0 and no longer writes `carMusic`/`tesla`/`audioRouteNavigation` into `receiver-access.json`.
- The canvas no longer carries `tabindex` and `InputController` never focuses it (1.3.0, ADR-17: the car's keyboard).
- View areas remain implemented in the receiver and `display-fit.ts` but the page still never calls `areaPlan`.
- `receiver/README.md` was rewritten for the fork on 2026-11-03; the Kotlin changes since 1.0.0 are listed in
  `UNVERIFIED-KOTLIN.md`.
