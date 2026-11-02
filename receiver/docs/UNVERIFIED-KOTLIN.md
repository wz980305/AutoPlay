# Kotlin changed without compiling (branch `receiver-trim`, 2026-10-26)

> Superseded for compilation by 0.1.1 (2026-10-31): both modules now build and local tests pass on JDK 21. Hardware-dependent checks below remain open. See `../../docs/AUDIT-0.1.1.md`. This document preserves the original 0.1.0 audit history.

The machine this series was written on had no network: Gradle could not resolve the Kotlin plugin or any
dependency, so **no Kotlin in this branch has been compiled or tested**. The web side was verified (`tsc`, esbuild,
`check*.mjs`); the Kotlin side was kept mechanical, reviewed twice per commit, and every deletion was followed by a
reference grep (imports, call sites, Gradle wiring, test classes). A developer with Gradle should run, before anything
else:

```sh
cd receiver && ./gradlew build        # compiles both modules and runs the test suite
```

and expect at most warnings about members that lost their last caller (listed per file below). Then build the viewer
(`web/README-build.md`) and run the receiver on a box.

## Files, what changed, what to look at first

### protocol module

| File | Change | Compile risk / what to check |
|---|---|---|
| `protocol/build.gradle.kts` | `net.sf.kxml:kxml2` dependency removed | Only `LockdownPlistChannel.kt` (deleted) imported `org.xmlpull` / kxml2. |
| `airplay/AirPlayConfig.kt` | `microphone`, `callsAndSiri` fields removed; `appearanceUpdates: Boolean = false` added | Any out-of-tree caller passing the two removed names breaks; in-tree callers (CarPlayServer, tests) were updated. |
| `airplay/AirPlayInfoPlist.kt` | `audioFormats(entertainmentRate)` offers output formats only (no `audioInputFormats`, no telephony/speechRecognition); the four `uiAppearanceMode/Setting`, `mapAppearanceMode/Setting` keys left out of each display; `enablesUIAppearance`/`enablesMapAppearance` set when `config.appearanceUpdates`; new `appearanceCommands(night)` | `format()` lost its `inputFormats` parameter; check nothing else called it. `listOf` replaced `listOfNotNull`. |
| `airplay/AirPlaySession.kt` | `AirPlayDeviceInfo.osVersion` (default `""`) added and filled from SETUP's `osVersion`; `sendPendingNightModeLocked` sends `setNightMode` and, when `config.appearanceUpdates`, the two appearance commands (`var sent` folding) | `sendCommandLocked` is called for each extra command under the same `eventWriteLock`, as before for one. |
| `airplay/CarPlayMediaEngine.kt` | microphone uplink removed: `MediaSink.onMicrophoneStarted/Stopped`, `microphoneEnabled` constructor parameter, `pendingMicrophone`, `microphoneConfig()`, `DATASTREAM_INPUT_KEY`, `OPUS_24K/48K`; class doc updated | `STREAM_TYPE_MAIN_AUDIO` may now be unused (warning). `AirPlaySession.remoteAddress` (internal) may be unused (warning). The constructor is `CarPlayMediaEngine(sink, audioCaptureDirectory = null)`; `CarPlayMediaEngineTest` already used `CarPlayMediaEngine(sink)`. |
| `airplay/MicrophonePacketizer.kt` (+ `MicrophoneConfig`, `MicrophoneCounters`) | deleted | Referenced only by `MicUplink.kt` (deleted), `CarPlayMediaEngine.kt` (edited) and its test (deleted). |
| `airplay/CarPlayClusterDisplay.kt`, `media/CarPlayPlaybackStatus.kt`, `mfi/RemoteMfiAuthenticationClient.kt` | deleted (no caller) | `AirPlayConfig.cluster` stays (the alt display config type is `AirPlayDisplayConfig`). |
| `transport/Iap2UsbMuxHost.kt`, `UsbMuxPipe.kt`, `TlsDuplexChannel.kt`, `LockdownCarKitClient.kt`, `LockdownPairRecord.kt`, `LockdownPairingClient.kt`, `LockdownPlistChannel.kt`, `LockdownTlsEngineFactory.kt`, `Iap2WiredControlClient.kt`, `Iap2ControlDeadline.kt` | deleted (wired CarPlay) | `IphoneUsbException.kt` is **kept**: `Iap2WirelessControlClient` and `Iap2IdentificationClient` throw it. |
| tests: `AirPlayInfoPlistTest.kt` | `callsAndSiriCanBeLeftToTheCar` → `callsAndSiriStayOnTheCarsBluetooth`; `microphoneInputsAreAdvertisedOnlyWhenEnabled` → `noMicrophoneInputIsAdvertised`; `everyDisplayDeclaresAutomaticAppearance` → `noDisplayPinsAnAppearanceAndIos27UpdatesAreDeclaredOnRequest` | Uses `assertFalse`/`assertTrue`/`assertEquals`, all already imported. |
| tests: `CarPlayClusterDisplayTest.kt`, `MicrophonePacketizerTest.kt`, `RemoteMfiAuthenticationClientTest.kt` | deleted with their classes | — |

### server module

| File | Change | Compile risk / what to check |
|---|---|---|
| `ServerConfig.kt` | removed `carVoice` (`--car-voice` is now an explicit no-op branch `-> {}`), `mfiRemoteServer/Token` (`--mfi-server/--mfi-token`), `usbBridge` (`--usb-bridge`); `mdns` default `"jmdns"`; `uiScale` default `DEFAULT_UI_SCALE = 85` (companion const); usage text | `fromArgs` ignores unknown flags, so an old launcher still starts. `PersistentConfig.DisplayPrefs` references `ServerConfig.DEFAULT_UI_SCALE`. |
| `Main.kt` | MFi error text; Netty `configureBootstrap` gains `childOption(IP_TOS, 0x88)` | Same hook as the existing `SO_SNDBUF` option; the dashplay-tesla fork compiled the identical line against Ktor 3.x. |
| `MfiIdentity.kt` | local identity only | — |
| `ServiceAdvertiser.kt` | `DnsSdAdvertiser` and the macOS probe removed; `Advertisers.create(...)` returns `ServiceAdvertiser?` (null for `--mdns off`), else `JmDnsAdvertiser` | Caller in `CarPlayServer.start()` uses `?.also { it.start() }` and `it?.close()`. The slf4j import was dropped from this file. |
| `WifiInfo.kt`, `WiredBootstrap.kt`, `MicUplink.kt`, `NowPlaying.kt` | deleted | `WifiNetwork` is now a two-field data class at the bottom of `WirelessBootstrap.kt`. |
| `WirelessBootstrap.kt` | SSID/channel from `config.wifiSsid/wifiChannel`; `BluetoothBridge.resolvePath` returns the configured path only; doc comments | `wifi.ssid` is non-null `String` now (the old `isNullOrBlank()` call was dropped). |
| `ProcessByteStream.kt` | comment only | — |
| `PersistentConfig.kt` | `mdns` default `"jmdns"`; `DisplayPrefs.uiScale` default from `ServerConfig.DEFAULT_UI_SCALE` | A saved `config.json` keeps its own values. |
| `WebBridge.kt` | microphone members removed (`MicrophoneConfig` import, `microphone`, `onMicrophoneStarted/Stopped`, `endMicrophone`, `sendMicrophonePayload`) | Still implements every remaining `MediaSink` member. |
| `WebHub.kt` | removed: `nowPlaying`/`artwork` state and messages, `microphoneRequested/Stopped`, `onMicrophoneData`, `MIC_FRAME_*`, the binary-frame dispatch (binary frames are now `continue`d), `ServerMessage.nowPlaying/artwork/revision/mic*`. Added: `ServerMessage.level/ms`, `duck(level, durationMs)`, `WsClient.touchDown`, `releaseTouch(client, why)` called from the marker loop on pause and from the `finally` on close | `releaseTouch` invokes `inputHandler` from the marker coroutine, as the reader coroutine already does for every input message. `ClientMessage(type = "touch-release")` relies on `contacts` defaulting to empty. |
| `CarPlayServer.kt` | wired removed (`wired`, `cablePhone`, `wiredSession`, `wiredSocket`, `listenWired`, `setCablePhone`, `wiredSessionActive`, the `wired` branch of `acceptLoop`); mic removed (`endMicrophone`, `onMicrophoneData`, `microphoneEnabled = true`, `microphone/callsAndSiri` in `airPlayConfig`); `nowPlayingFeed` → `artworkDrain` (keeps `Iap2ArtworkReceiver` consuming file transfers, `complete = { _, _, _ -> false }`); `onIncoming` no longer passed to `Iap2WirelessControlClient.run` (its default is `{}`); `--mdns off` handled; `loadPairings` replays without saving, falls back to `.bak`, `persistPairings` writes temp + fsync + copy to `.bak` + atomic rename; iOS memory (`iosFile`, `knownIos`, `rememberIos`, `appearanceUpdatesFor`, `APPEARANCE_MIN_IOS = 27`) and `appearanceUpdates = appearanceUpdatesFor(selectedPhone)` in `airPlayConfig`; `onDeviceInfo` logs `osVersion` and remembers it; `onCommand` handles `duckAudio`/`unduckAudio` (`ducks`/`unducks` counters, `DUCK_DEFAULT_LEVEL = 0.2`); `routeInput` keeps `lastContacts` and handles `"touch-release"` | Imports `Files`, `Path`, `Properties`, `ServerSocket`, `InetSocketAddress`, `Socket`, `Iap2Session` are all still used. `Properties.isEmpty` is Kotlin's synthetic property for `isEmpty()`. `Files.move(..., REPLACE_EXISTING, ATOMIC_MOVE)` is what the dashplay-tesla fork used on the same JDK. |
| tests: `AudioCapabilitiesTest.kt` | rewritten: `offersNoMicrophoneAndNoVoiceStreams` | — |
| tests: `NowPlayingTest.kt` | deleted with `NowPlaying.kt` | — |

### Deleted outside Kotlin

`macos/bt-bridge/main.swift` and `build.sh` (the macOS Bluetooth helper); `web/src/flac-mp4.ts`, `web/check-flac.mjs`
(wired LPCM-as-FLAC).

## Behaviour that needs a box or a car, not just a compile

1. **Artwork drain** (`CarPlayServer.artworkDrain`): with music on the car's Bluetooth the iPhone still starts
   artwork file transfers on the tunneled iAP2 link; the drain must keep the link alive past 256 transfers (it
   declines each SETUP: CANCEL when the receiver's small queue is full or after its 15 s deadline). Watch for
   `iAP2 received-file queue limit exceeded` in the log during a long drive with many song changes.
2. **iOS 27 appearance**: check that night mode flips CarPlay on an iOS 27 phone (`appearance updates=true` in the
   log after the phone's first connection) and still does on iOS 26 (`setNightMode` only); the 2,2 / 1,1 pairs are
   the fork's in-car observation, not documented by Apple.
3. **duck/unduck**: `grep 'audio duckAudio'` in the receiver log shows the raw `volume` the phone sends; the dB /
   linear mapping in `onCommand` is a guess until that log exists.
4. **Pairing store**: after the first start, `state/receiver/pairings.properties.bak` should appear next to the main
   file after the first new pairing; a deliberately emptied main file must fall back to the `.bak` at the next start.
5. **DSCP**: `tcpdump -v` on the box should show TOS 0x88 on the 18443 traffic.
6. **Touch release**: freeze the page with a finger down (reverse gear); the log should say
   `viewer client=N paused with a finger down: lifting it` and the phone should not keep a pressed button.

## Not done (noted, not attempted)

- **HID on a single-thread executor** (media_performance_audit #16, second half): the touch report is still written
  on the WebSocket reader under `eventWriteLock`. Moving it to an executor touches `AirPlaySession.sendTouch` and
  the LagGate ack path; not a trivial change to make blind.
- **Iap2LocationClient.kt** was listed as dead but is used by `Iap2WirelessControlClient` (Start/StopLocationInformation);
  kept, see `TRIM-LOG.md`.
- `AirPlayHid.telephonyHidDevice` / `sendTelephony` / the `"telephony"` input route are kept on purpose (three lines,
  harmless), though no page sends them now.
