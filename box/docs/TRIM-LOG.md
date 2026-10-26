# Trim log: DashPlay box → AutoPlay box (ZTE F50, Tesla only)

What the `box-trim` branch removed, moved and added relative to the imported
tree (commit `c138aae`, DashPlay `e3beae4` + openwrt-dashplay `5f17702`), in
the order of the work items. The design notes referred to are the ones the
brief cites (D1–D15 Tesla constants, S1 wired removal, F50 reliability audit
6a–6j, transition 7).

## Numbers

`git diff --shortstat c138aae...HEAD -- box openwrt`:

    140 files changed, 4867 insertions(+), 12650 deletions(-)

Lines in the tree (`git show` of every tracked file, `wc -l`):

| | before (`c138aae`) | after (`HEAD`) |
|---|---|---|
| program (py, sh, js, po, json, Makefile, `files/`) | 13,837 | 8,807 |
| tests | 6,435 | 4,046 |
| docs (`.md`) | 1,235 | 1,293 |
| **total** | **21,507** | **14,146** |

(`TEST-BASELINE.md` counted 20,425 with `wc -l` over source files only; the
table above includes the `.md` files and the LuCI `.po`, so the two totals are
not meant to match. Both are measured the same way before and after.)

Tests: 375 onecloud + 7 runnable bluetooth before; 225 onecloud + 7 runnable
bluetooth after. The onecloud count fell with the deleted Debian/N1/wired/STA
tests (16 files) and rose with the tests of the new modules (6 files, listed
under "Added"). The three bluetooth modules that import `dbus_next` still
cannot run here (see `TEST-BASELINE.md`).

## 1. Baseline

`docs/TEST-BASELINE.md`, `.gitignore` for `__pycache__/`.

## 2. Hidden couplings (nothing deleted yet)

Moved so that the OpenWrt side stopped importing the Debian first-run wizard:

- `state.py` ← the state-file helpers, `SHARED_LAN`, `tesla_reaches()`,
  `LOCAL_NAME` (`autoplay.lan`) from `setup_wizard.py`;
- `tesla_checks.py` ← the connectivity-check names and the ConnMan reply
  (`check_name()`, `check_response()`) from `setup_wizard.py`;
- `platform_openwrt.py` made standalone (`boot_id()`, `parse_stations`,
  `pick_network()` AP-only), `platform_api.get_platform()` returns it;
- `build-bundle.sh` moved from `scripts/onecloud/firmware/` to `scripts/`.

## 3. Wired CarPlay (S1: no USB host on the F50)

Deleted: `iphone-usb-bridge.py`, `test_iphone_usb_bridge.py`, the `wired`
status, the wired wizard steps and the "数据线" copy on the settings page.

## 4. Other targets, other modes

Deleted, with their tests:

| area | files |
|---|---|
| Debian/Armbian supervisor and platform | `supervisor.py`, `platform_debian.py`, `dashplay.service`, `setup_wizard.py`, `setup_flow.py`, `status_light.py`, `mdns_name.py`, `bluetooth_address.py`, `board_phicomm_n1.py`, `board-probe.sh`, `KeystoreRewrap.java` |
| OneCloud/N1 firmware tooling and notes | `scripts/onecloud/firmware/` (`README.md`, `burnimg.py`, `dashplay-firstboot.service`, `install.sh`, `make-bundle.sh`, `make-n1-image.sh`, `pack-image.sh`, `prepare-image.sh`, `update-programs.py`, `upgrade.py`), `install-image.py`, `docs/DashPlay玩客云固件使用说明.md`, `docs/DashPlay-AI安装说明.md` (OneCloud/N1 notes for an AI assistant; its section on identity files and DuckDNS is now in the READMEs, the rest described removed options) |
| STA / phone-hotspot uplink, external and public IPv6 reach | `phone_uplink.py`, `debug_uplink.py`, `external`/`public_ipv6` handling in `own_domain.py`, `boxnet.py` and the matching LuCI options (the "reach" tab keeps only the DuckDNS name and token) |
| local CA (D7) | the CA generation in `boxnet.py`; kept: the PKCS12 wrap of the Let's Encrypt chain, and the keystore is deleted when the chain is gone so the JVM self-signs |
| F50 flashing tooling outside the installer | `build-mac-tools.sh`, `build-windows-tools.sh`, `mac-bootstrap.sh`, `windows-bootstrap.ps1`, `apply-playport-patches.sh`, `tools/` (never imported) |
| lab probes | `carplay-night-probe.mjs`, `carplay-timeline.py`, `serial-boot-log.py`, `linux/bt-bridge/Dockerfile.hardware`, `hardware-entrypoint.sh`, `probe_adapter.py` |
| tests | `test_bluetooth_address`, `test_board_phicomm_n1`, `test_burnimg`, `test_car_foundations`, `test_debug_uplink`, `test_install_image`, `test_iphone_usb_bridge`, `test_phone_uplink`, `test_platform`, `test_setup_flow`, `test_setup_wizard`, `test_status_light`, `test_tesla_offline`, `test_timeline`, `test_upgrade`, `bluetooth/test_probe` |

Kept on purpose: the F50 path of `f50-install.py` and the host-side helpers
it calls (`f50-backup.py`, `f50-root-plan.py`, `prepare-f50-root-candidate.py`,
`prepare-f50-trustos.py`, `prepare-mu300-panel-installer.py`,
`verify-f50-tos-candidate.py`, `f50-root-bootstrap.sh`, `install_progress.py`,
`fetch-install-assets.py` with `downloads.json` trimmed to the F50 groups);
none of them was changed beyond the rename. `build-playport.sh`,
`fetch-java.py` (its pinned runtimes) and `scan-sensitive.py` (publication
hygiene) stay as build tooling.

## 5. Tesla constants (D1, D2, D4, D8, D10, D11, D14, D15)

- LAN `100.96.0.1/24` set by the package's uci-defaults, not by a wizard;
  `SHARED_SPACE` conflicts are a warning, not a mode switch.
- Connectivity checks answered always (`OfflineChecks.start/refresh`), DNS
  entries only through `OfflineChecks`; the `--tesla` receiver flag is always
  passed; settings port `18080`, viewer `18443`, port 80 redirected to the
  settings page on the `.2` alias.
- The viewer name is derived: the DuckDNS domain when set, else `autoplay.lan`.
- uci `autoplay.main` has seven keys (`enabled`, `viewer_port`,
  `idle_release`, `duckdns_domain`, `duckdns_token`, `update_check`,
  `update_mirror`); obsolete options are removed by the uci-defaults script.
- LuCI: an overview block and four tabs (network, iPhone, reach, update).

## 6. Reliability (F50 audit)

| item | what | module |
|---|---|---|
| 6a | Bluetooth power retried in the background at 10/20/40 s then every 60 s; `bluetooth` status domain with reason words; red bar on the page | `supervisor_openwrt.BluetoothManager`, `supervision.Schedule`, `settings_page.BLUETOOTH_TEXT` |
| 6b | per-child restart with back-off, `degraded` after five failures in ten minutes; guarded periodic checks; three-miss Wi-Fi; subprocess timeouts; JVM liveness probe (`/api/display`); `-XX:+ExitOnOutOfMemoryError` | `supervision.Restarter/Liveness/Misses/Guard`, `ReceiverManager`, `run-receiver.py` |
| 6c | `tesla` domain with a reason; no deauth of the car | `supervisor_openwrt`, `tesla_openwrt` |
| 6d | tmpfs log ring mirrored to the card every 60 s (5 MB cap, at once on an error line); no global `os.sync`; presence file written on change only; `PYTHONDONTWRITEBYTECODE`; `-XX:ErrorFile`; AppCDS archive primed at install | `diagnostics.LogMirror`, `state.save_json`, `phone-presence.py`, `autoplay.init`, `run-receiver --prime-cds` |
| 6e | update journal, recovery at start, rollback; health = receiver answering + Bluetooth powered; persistent package cache | `update.py` |
| 6f | DuckDNS/acme retries 60/120/300/900 s then hourly, woken by WAN-up/NTP hotplug; `certificate` domain, orange bar under 30 days | `own_domain.py`, `hotplug-iface`, `hotplug-ntp` |
| 6g | clock floor file (never earlier than the last time seen); a second time source is a receiver-side task | `clock_floor.py` |
| 6h | `X-Frame-Options: DENY`, Host allow-list, no `root`/`1234` on the page; `oom_score_adj` +500 for the JVM, −500 for bluetoothd | `settings_page.py`, `run-receiver.py`, `board_zte_f50.py` |
| 6i | `bt-bridge: reason=<word>` on failure, stdin hang-up cancels the attempt, two authentication failures → "请删除此 iPhone 后重新添加" | `linux/bt-bridge/bridge_reasons.py`, `bridge.py`, `supervisor_openwrt.pairing_lost` |
| 6j | factory reset from the page (`/reset`), secrets shredded, identity only with a second typed confirmation | `factory_reset.py` |

## 7. Rename with a transition

Package `autoplay` (`CONFLICTS dashplay`), `/opt/autoplay`, uci `autoplay`,
`luci-app-autoplay`, `skills/autoplay-install`. The autoplay postinst moves
`/opt/dashplay/{state,identity}` and the private BlueZ root over and copies
the old uci options; `update.py` removes the DashPlay packages before
installing the AutoPlay ones and, on a failed first update, reinstalls them and
moves the state back (`return_state_to_legacy`). DashPlay stays named where it
is attribution.

## 8. Docs

This file, `STATUS-MODEL.md`, `README.md`/`README.en.md` (box and openwrt),
`NOTICE.md` (box and openwrt), `linux/bt-bridge/README.md`.

## Added

Modules: `state.py`, `tesla_checks.py`, `status_model.py`, `supervision.py`,
`settings_ui.py`, `clock_floor.py`, `factory_reset.py`,
`linux/bt-bridge/bridge_reasons.py`; package files `90-autoplay-tesla`,
`hotplug-iface`, `hotplug-ntp`.

Tests: `test_platform_openwrt`, `test_supervision`, `test_status_and_reset`,
`test_clock_floor`, `test_factory_reset`, `bluetooth/test_reason`, plus the
legacy-transition and journal cases in `test_update`.

## Not finished

- `skills/autoplay-install/SKILL.md` still describes N1/OneCloud and the
  DashPlay-era commands and links to the deleted `docs/DashPlay-AI安装说明.md`;
  only the file was renamed.
- `tools/` (pinned `spd_dump`/`lz4`) was never imported, so the installer's
  `check` and `flash` stages need those binaries from a DashPlay checkout.
- The dbus-next Bluetooth tests (`test_bluez`, `test_recovery`) need a machine
  with `dbus-next 0.2.3`.
- `/time` hint for the clock floor and moving `receiver-access.json` into tmpfs
  are receiver-side tasks (`STATUS-MODEL.md`).
- The update feed and manifest URLs point at `openwrt-autoplay` placeholders
  (`AUTOPLAY_UPDATE_OWNER/REPO/FEED_REPO`, `AUTOPLAY_FEED`) until the fork
  publishes releases.
