# AutoPlay receiver: notices and attribution

AutoPlay's receiver (`receiver/`: `protocol/`, `server/`, `web/`) is free software under the **GNU General Public
License v3.0** (see [LICENSE](LICENSE)). It is a hard fork, trimmed to one target (a ZTE F50 running OpenWrt, showing
wireless CarPlay in a Tesla's built-in browser, with music, calls and Siri on the car's own Bluetooth). Everything it
derives from is GPL-3.0; distributed copies and modifications must keep this license and make their source available.

## Lineage

- **PlayPort** by youcci (<https://github.com/youcci/playport>, commit `9a0882d`), GPL-3.0: the JVM server (Ktor/Netty,
  AirPlay session, wireless bootstrap, browser hub) and the WebCodecs browser viewer this receiver is built from.
- **DashPlay** by 一只小黑狗 (yizhixiaoheigou, <https://github.com/yizhixiaoheigou/DashPlay>, `e3beae4`, v2026.10.25),
  GPL-3.0: the 63-patch series over PlayPort that made it a car box (view areas, display restart, decode backlog, the
  Tesla hop, compatible display, performance mode, LagGate, the revive path, prompt boost, idle close, i18n and much
  else), applied here as one commit per patch. The author published DashPlay's updates and how-tos on Douyin and
  Xiaohongshu; the viewer used to carry two QR codes to those accounts, which the Tesla-only trim removed from the page
  (31 KB per load, the brightest elements at night). This notice is where that attribution now lives.
- **DiPlay** by shihabal3amri (<https://github.com/shihabal3amri/DiPlay>), itself based on **xcertplay** by shilapi
  (<https://github.com/shilapi/xcertplay>), both GPL-3.0: the AirPlay, iAP2 and accessory-authentication protocol
  stack in `protocol/` (a port of DiPlay's `shared` sources), the view-area protocol (`updateViewArea`) and parts of
  the viewer's behaviour (the compatible-display idea, the day/night appearance keys that were later removed).
- **WheelPlay**, GPL-3.0: the wired (USB, Lockdown/usbmux) iAP2 transport PlayPort carried. AutoPlay deleted that code
  (wireless only); `transport/IphoneUsbException.kt` keeps WheelPlay's error taxonomy, which the wireless clients use.
- **dashplay-tesla** (a fork of DashPlay, GPL-3.0): the iOS 27 day/night design re-implemented in
  `AirPlayConfig.appearanceUpdates`, `AirPlayInfoPlist.appearanceCommands`, the per-phone iOS memory in
  `CarPlayServer` and the removal of the four DiPlay `*AppearanceMode = 0` keys (its in-car observation of
  `appearanceMode/appearanceSetting` 2,2 dark and 1,1 light), and the DSCP AF41 mark on the viewer connections. The
  fork's code was read for the design only; nothing was copied wholesale.

## Not part of this repository

The accessory (MFi) identity the protocol needs is third-party key material recovered during the DiPlay project's
investigation. It is not relicensed, not shipped and never committed (`receiver/identity/` is ignored by git).

CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc. Tesla is a trademark of Tesla, Inc. AutoPlay is an
independent project; no affiliation with or endorsement by Apple, Tesla, or the authors of the projects above is
implied.
