# AutoPlay OpenWrt packages — notices and attribution

The package definitions and scripts in this directory are distributed under the GNU General Public
License v3.0 (see `LICENSE`). They started as openwrt-dashplay
(<https://github.com/yizhixiaoheigou/openwrt-dashplay>, GPL-3.0, commit `5f17702`), the package
repository of [DashPlay](https://github.com/yizhixiaoheigou/DashPlay), and were renamed and trimmed for
AutoPlay, DashPlay's hard fork for the ZTE F50 and Tesla (`../box/docs/TRIM-LOG.md`).

The built packages contain:

- **autoplay**: the AutoPlay program bundle of the release named in `autoplay/Makefile` — AutoPlay
  (GPL-3.0), the receiver (PlayPort with DashPlay's patches, GPL-3.0) with its Maven dependencies
  (licenses inside each JAR), acme.sh 3.1.6 (GPL-3.0, unmodified main script and DuckDNS hook, for the
  optional own name) and dbus-next 0.2.3 (MIT). `../box/NOTICE.md` lists the projects AutoPlay derives
  from.
- **autoplay-jre**: Eclipse Temurin 21 JRE, Alpine Linux (musl) build, by the Eclipse Adoptium
  project (<https://adoptium.net/>), GPL-2.0 with the Classpath Exception; unmodified except that the
  unused `lib/libjsound.so` is left out and a `libc.musl-<cpu>.so.1` link to OpenWrt's musl is added.
- **luci-app-autoplay**: from openwrt-dashplay's luci-app-dashplay (GPL-3.0), reworked.

`board_zte_f50.py --setup` (in the bundle) installs BlueZ and D-Bus from the F50's own official OpenWrt
feeds into a private root at run time; they are not part of these packages.

No accessory authentication identity, certificate, private key, pairing record, password or token is
included in this directory or the packages.

CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc. This is an independent project; no Apple
affiliation or endorsement is implied.
