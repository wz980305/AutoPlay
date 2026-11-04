# AutoPlay packages for OpenWrt

[中文](README.md)

The three packages of [AutoPlay](../box/README.en.md) for the ZTE F50 (OpenWrt 25.12, `apk`):

- `autoplay`: the program and its boot service (`/opt/autoplay`, `/etc/init.d/autoplay`, `/etc/config/autoplay`), architecture-independent. The program is the `autoplay-bundle-<version>.tar` built locally by `box/scripts/build-bundle.sh` and handed to the SDK (there is no release page yet; `PKG_SOURCE_URL` in `autoplay/Makefile` is a placeholder and `PKG_HASH:=skip`); no second copy of the source lives here.
- `autoplay-jre`: Eclipse Temurin 21 JRE, musl build (OpenWrt has no Java), aarch64 and x86_64.
- `luci-app-autoplay` (with `luci-i18n-autoplay-zh-cn`): Services → AutoPlay in LuCI, an overview block and four tabs (Network, iPhone, Own address, Program update).

> **Not an Apple-certified product.** It needs the accessory identity you supply: [box/README.en.md](../box/README.en.md#accessory-identity).

Prerequisite: an F50 already flashed to OpenWrt following [mu300-linux](https://github.com/dikeckaan/mu300-linux)'s own documentation (the unit we verified shipped with stock B13; this repository gives no flashing steps). Packages are installed by hand as below; the full procedure is in the [install guide](../交付资料/AutoPlay-1.3.2-安装使用说明.md) (Chinese).

## Installing by hand

```sh
cd /tmp
apk update
apk add --allow-untrusted autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-[0-9]*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk
python3 /opt/autoplay/board_zte_f50.py --setup     # the F50's own BlueZ (below)
```

The packages are unsigned, hence `--allow-untrusted`. About 230 MB of storage, most of it Java.

At install time (uci-defaults `90-autoplay-tesla` and the postinst):

- sets the LAN to `100.96.0.1/24` (RFC 6598 shared address space, which the Tesla browser opens) with gateway and DNS in DHCP; a LAN on another address is changed, and car and phone reconnect once;
- sets the 5 GHz radio to country CN, channel 149 (the car only finds the hotspot on 149–165, which the mu300-linux image's country code TR does not have); a channel already within 149–165 is kept, SSID and password are untouched;
- removes the DashPlay-era uci options and dhcp records (and 1.1.0–1.2.0's `audio_route_navigation`), leaving eleven options: `enabled`, `viewer_port`, `idle_release`, `dns_provider`, `duckdns_domain`, `duckdns_token`, `own_domain`, `dnspod_id`, `dnspod_token`, `update_check`, `update_mirror`;
- when coming from DashPlay, moves `/opt/dashplay/{state,identity}` and the private BlueZ root to `/opt/autoplay` and copies the options from `/etc/config/dashplay` (`autoplay` and `dashplay` conflict; the online update removes the old packages first);
- primes Java's AppCDS archive, which saves a few seconds at boot.

### Bluetooth on the F50

The F50 runs a vendor 5.4 kernel; OpenWrt's `bluez-daemon` pulls in 6.12 kernel modules and breaks Bluetooth and Wi-Fi. `board_zte_f50.py --setup` installs BlueZ from the F50's own official feeds into the private root `/opt/autoplay-bluez`; the supervisor always brings Bluetooth up through it, retrying at 10/20/40 s and then every 60 s, and shows the reason on the settings page and in LuCI.

## Using it

- Settings page: `http://100.96.0.1:18080/` (`http://100.96.0.2/` redirects there).
- Car browser: `https://<your domain>:18443/` — a DuckDNS name or your own domain hosted at Tencent DNSPod, both with a Let's Encrypt certificate and no warning; without a domain it is `https://autoplay.lan:18443/`, with a certificate warning.
- LuCI Services → AutoPlay: overview (one line each for Bluetooth, iPhone, certificate and update, with the reason); "network" shows the AP and the subnet; "iPhone" invites or removes and sets the idle release; "Own address" picks DuckDNS or DNSPod and takes the credentials; "Program update" checks, upgrades, sets the mirror.
- The Tesla's Wi-Fi needs "stay connected while driving", otherwise it drops the Wi-Fi as soon as the car leaves Park. If the car cannot see the AP, check in LuCI → Network → Wireless that the 5 GHz radio is on 149–165 (set to CN / 149 at install).

Status and reason words: [box/docs/STATUS-MODEL.md](../box/docs/STATUS-MODEL.md).

## Updating

**Online update** (since 1.3.1, `docs/RELEASE.md`): every version is a signed Release of `github.com/wz980305/AutoPlay`. A box on 1.3.0 or earlier installs 1.3.1 or later once by the manual route below (they carry the project's own public key; the older packages carry upstream DashPlay's); after that, Services → AutoPlay → Program update, or the settings page's update section: one check a day, a new version is only announced; "upgrade now" downloads the signed release from GitHub (or a mirror), does not run while CarPlay is in use, backs up pairings, certificate and settings first, stops if the plan touches the kernel, kernel modules or the system BlueZ, and reinstalls the previous version when the new one does not come up (receiver not answering within about 4 minutes, or Bluetooth not powered). Progress is journaled in `state/update-journal.json`; after a power cut the next boot finishes or rolls back.

By hand: `apk update && apk add --upgrade --simulate --allow-untrusted /tmp/autoplay-upgrade/*.apk` to see the plan, then without `--simulate` once it contains user-space packages only. Do not remove and reinstall, do not sysupgrade, do not overwrite `/opt/autoplay/{state,identity}`.

## Removing

```sh
apk del luci-i18n-autoplay-zh-cn luci-app-autoplay autoplay autoplay-jre
```

Added iPhones, the certificate and the identity stay under `/opt/autoplay/`; delete them by hand when you are sure (or use the settings page's factory reset first). The LAN is not changed back.

## Building the packages

Needs Docker (the container gets no privileges, host network or devices).

```sh
sh scripts/build-packages.sh out/ autoplay-bundle.tar     # with a locally built bundle (box/scripts/build-bundle.sh); there is no release page, so the no-argument form fails
sh scripts/lab-test.sh out/                               # install, start, check, remove in a clean OpenWrt 25.12.5 container
sh scripts/bump-autoplay.sh <version> autoplay-bundle-<version>.tar   # after a release: version and hash in autoplay/Makefile
```

Dependencies are runtime-only (`EXTRA_DEPENDS`); the build compiles no Python and no kernel modules.

## License and trademarks

GPL-3.0, see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc.; Tesla is a trademark of Tesla, Inc. This project is not affiliated with or endorsed by either.
