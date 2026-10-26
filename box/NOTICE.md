# AutoPlay — notices and attribution

AutoPlay is distributed under the GNU General Public License v3.0 (see `LICENSE`). It is a hard fork
of DashPlay and, through it, a set of modifications of PlayPort; it stays under the same license.

## What this fork derives from

- **DashPlay** — <https://github.com/yizhixiaoheigou/DashPlay> (GPL-3.0), commit `e3beae4`, and its
  package repository openwrt-dashplay, commit `5f17702`. The box-side programs (supervisor, settings
  page, Bluetooth bridge, DuckDNS/acme integration, online update, installer), the OpenWrt packages
  and the LuCI app started as DashPlay's and were trimmed to one target (`docs/TRIM-LOG.md`).
  Module docstrings, lab notes and the transition code keep the DashPlay name where it is the origin
  of a design or an identifier the migration still reads.
- **PlayPort** — <https://github.com/youcci/playport> (GPL-3.0), commit
  `9a0882dd0ffe48e467b59d58b12d81391df55ade`. The receiver in the repository's `receiver/` is PlayPort
  with DashPlay's patches applied in-tree; its own notices are there.
- **DiPlay** by shihabal3amri and **xcertplay** by shilapi (GPL-3.0) — the protocol stack PlayPort
  derives from. The CarPlay view-area switching in the receiver follows DiPlay pull request #246 and its
  `docs/VIEW_AREAS.md` <https://github.com/shihabal3amri/DiPlay>.
- **WheelPlay** — <https://github.com/fython/wheelplay> (GPL-3.0), commit
  `c1bd07717c8e87a3130ef03477d2ca318fb66caa`. The iAP2 file-transfer (album artwork) receiver was
  ported from it by DashPlay. DashPlay's wired CarPlay transport, also ported from WheelPlay, is removed
  from the box side of this fork (the F50 has no USB host).
- **dashplay-tesla** (a Tesla-oriented fork of DashPlay, GPL-3.0): the design of the Bluetooth bridge's
  reason words (`bt-bridge: reason=<word>` on failure, "two authentication failures mean the pairing is
  lost") was taken from reading its `bridge.py`. `linux/bt-bridge/bridge_reasons.py` and the cancel on
  stdin hang-up are re-implementations; no code was copied.

## Bundled third-party software

The program bundle `autoplay-bundle-<version>.tar` (built by `scripts/build-bundle.sh`, unpacked to
`/opt/autoplay` by the OpenWrt package) contains, besides this repository's programs and the receiver
with its Maven dependencies (licenses inside each JAR):

- **dbus-next** 0.2.3 — <https://github.com/altdesktop/python-dbus-next>, MIT, unmodified
  (`licenses/dbus-next-0.2.3-MIT.txt`); the Bluetooth bridge's only dependency.
- **acme.sh** 3.1.6 — <https://github.com/acmesh-official/acme.sh>, GPL-3.0, unmodified main script and
  DuckDNS hook with its LICENSE.md; used only when the owner sets a DuckDNS name.

The Java runtime and the OpenWrt packaging are described in `openwrt/NOTICE.md`.

## Tools the installer downloads but does not redistribute

`scripts/f50-install.py` and `skills/autoplay-install/downloads.json` pin, download and hash-check on
the owner's computer: the OpenWrt build for the F50 from **mu300-linux**
<https://github.com/dikeckaan/mu300-linux> (GPL-2.0 kernel, OpenWrt's licenses), the Root image and
**Magisk** installer from <https://github.com/Xio-Shark/f50-b16> and <https://github.com/topjohnwu/Magisk>
(GPL-3.0), Google's Android **platform-tools** (adb; Android SDK terms), and on Windows **Zadig**
<https://zadig.akeo.ie/> (GPL-3.0) for the WinUSB driver. The installer's `flash` stage also expects the
`spd_dump` and `lz4` binaries that DashPlay shipped under `tools/` (from **spreadtrum_flash**
<https://github.com/TomKing062/spreadtrum_flash>, Unlicense, with **libusb** LGPL-2.1, and **lz4**
<https://github.com/lz4/lz4>, GPL-2.0/BSD-2-Clause); they were not imported into this fork. None of these
is in this repository.

## Accessory identity

No accessory authentication identity, accessory certificate or private key is included in the
repository, packages, documentation or tests; tests generate synthetic identities at runtime. AutoPlay
does not download identities. The receiver needs the owner-supplied `identity.pk8` (PKCS#8 EC P-256
private key) and matching `certificate.p7b` under `/opt/autoplay/identity/offline-mfi/` and refuses to
start without them. PlayPort documents possible sources; mentioning them is attribution, not a grant to
redistribute their contents. Shared experimental identities can be revoked. AutoPlay is not an
Apple-certified product and is intended for personal experimentation; do not sell or redistribute
authentication identities.

## Artwork

The box settings icon is original geometric artwork generated for DashPlay by
`scripts/generate-box-settings-icon.py` (2026-10-11), GPL-3.0 with this project, using no third-party
icon or font assets: [icon provenance](assets/ICON-SOURCE.md). The receiver keeps the resource name
`f50-settings.png`.

CarPlay, iPhone, AirPlay and MFi are trademarks of Apple Inc. This is an independent project; no
Apple, PlayPort, DiPlay, xcertplay, WheelPlay or DashPlay affiliation or endorsement is implied.
