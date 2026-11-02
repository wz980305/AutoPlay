# AutoPlay packages for OpenWrt

[中文](README.md)

The three packages of [AutoPlay](../box/README.en.md) for the ZTE F50 (OpenWrt 25.12, `apk`):

- `autoplay`: the program and its boot service (`/opt/autoplay`, `/etc/init.d/autoplay`, `/etc/config/autoplay`), architecture-independent. The program is the `autoplay-bundle-<version>.tar` attached to each AutoPlay release (`PKG_SOURCE_URL` and `PKG_HASH` in `autoplay/Makefile`); no second copy of the source lives here.
- `autoplay-jre`: Eclipse Temurin 21 JRE, musl build (OpenWrt has no Java), aarch64 and x86_64.
- `luci-app-autoplay` (with `luci-i18n-autoplay-zh-cn`): Services → AutoPlay in LuCI, an overview block and four tabs (network, iPhone, name, update).

> **Not an Apple-certified product.** It needs the accessory identity you supply: [box/README.en.md](../box/README.en.md#accessory-identity).

Normally nothing here is installed by hand: the `autoplay` stage of the [installer](../box/scripts/f50-install.py) installs the packages and moves the LAN to `100.96.0.1/24`. Below is the manual route and what the packages do.

## Installing by hand

```sh
cd /tmp
apk update
apk add --allow-untrusted autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-[0-9]*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk
python3 /opt/autoplay/board_zte_f50.py --setup     # the F50's own BlueZ (below)
```

The packages are unsigned, hence `--allow-untrusted`. About 230 MB of storage, most of it Java.

The postinst:

- sets the LAN to `100.96.0.1/24` (RFC 6598 shared address space, which the Tesla browser opens) with gateway and DNS in DHCP; a LAN on another address is changed, and car and phone reconnect once;
- removes the DashPlay-era uci options and dhcp records, leaving seven options: `enabled`, `viewer_port`, `idle_release`, `duckdns_domain`, `duckdns_token`, `update_check`, `update_mirror`;
- when coming from DashPlay, moves `/opt/dashplay/{state,identity}` and the private BlueZ root to `/opt/autoplay` and copies the options from `/etc/config/dashplay` (`autoplay` and `dashplay` conflict; the online update removes the old packages first);
- primes Java's AppCDS archive, which saves a few seconds at boot.

### Bluetooth on the F50

The F50 runs a vendor 5.4 kernel; OpenWrt's `bluez-daemon` pulls in 6.12 kernel modules and breaks Bluetooth and Wi-Fi. `board_zte_f50.py --setup` installs BlueZ from the F50's own official feeds into the private root `/opt/autoplay-bluez`; the supervisor always brings Bluetooth up through it, retrying at 10/20/40 s and then every 60 s, and shows the reason on the settings page and in LuCI.

## Using it

- Settings page: `http://100.96.0.1:18080/` (`http://100.96.0.2/` redirects there).
- Car browser: `https://autoplay.lan:18443/`; with a DuckDNS name, `https://<name>.duckdns.org:18443/` with a Let's Encrypt certificate and no warning.
- LuCI Services → AutoPlay: overview (one line each for Bluetooth, iPhone, certificate and update, with the reason); "network" shows the AP and the subnet; "iPhone" invites or removes; "name" takes the DuckDNS name and token; "update" checks, upgrades, sets the mirror.
- The Tesla's Wi-Fi needs "stay connected while driving", otherwise it drops the Wi-Fi as soon as the car leaves Park. If the car cannot see the AP, set the wireless country to CN and channel 149 (`--country`/`--channel` of the installer's `tesla` stage).

Status and reason words: [box/docs/STATUS-MODEL.md](../box/docs/STATUS-MODEL.md).

## Updating

Services → AutoPlay → update, or "程序更新" on the settings page: one check a day, a new version is only announced; "upgrade now" downloads the signed release from GitHub (or a mirror), does not run while CarPlay is in use, backs up pairings, certificate and settings first, stops if the plan touches the kernel, kernel modules or the system BlueZ, and reinstalls the previous version when the new one does not come up (receiver not answering within about 4 minutes, or Bluetooth not powered). Progress is journaled in `state/update-journal.json`; after a power cut the next boot finishes or rolls back.

By hand: `apk update && apk add --upgrade --simulate --allow-untrusted /tmp/autoplay-upgrade/*.apk` to see the plan, then without `--simulate` once it contains user-space packages only. Do not remove and reinstall, do not sysupgrade, do not overwrite `/opt/autoplay/{state,identity}`.

## Removing

```sh
apk del luci-i18n-autoplay-zh-cn luci-app-autoplay autoplay autoplay-jre
```

Added iPhones, the certificate and the identity stay under `/opt/autoplay/`; delete them by hand when you are sure (or use the settings page's factory reset first). The LAN is not changed back.

## Building the packages

Needs Docker (the container gets no privileges, host network or devices).

```sh
sh scripts/build-packages.sh out/                         # the SDK downloads the release bundle and checks its hash
sh scripts/build-packages.sh out/ autoplay-bundle.tar     # or your own bundle (box/scripts/build-bundle.sh)
sh scripts/lab-test.sh out/                               # install, start, check, remove in a clean OpenWrt 25.12.5 container
sh scripts/bump-autoplay.sh <version> autoplay-bundle-<version>.tar   # after a release: version and hash in autoplay/Makefile
```

Dependencies are runtime-only (`EXTRA_DEPENDS`); the build compiles no Python and no kernel modules.

## License and trademarks

GPL-3.0, see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; this project is not affiliated with or endorsed by Apple.
