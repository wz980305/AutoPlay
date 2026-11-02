# Status model

One place for "how is the box doing", with a reason word for every failure, so
that the settings page, LuCI, the health check of an update and the log all say
the same thing (settings_onboarding_audit S2/S7/S13, reliability_audit #13).

Implementation: `scripts/onecloud/status_model.py` (`Status`), filled by
`supervisor_openwrt.py`, written to `/var/run/autoplay/status.json` (tmpfs, on
change only) and served by the settings page at `/status.json`. The receiver
log at `/var/run/autoplay/receiver.log` is the source of the `phone` reasons.

## Shape

```json
{
  "updated": 1761475200,
  "mode": "openwrt", "ssid": "AutoPlay", "home": "http://100.96.0.1:18080/",
  "entries": ["https://autoplay.lan:18443/"], "name": "autoplay.lan",
  "bluetooth":   {"state": "on",       "reason": null, "since": 1761475130},
  "wifi":        {"state": "up",       "reason": null, "since": 1761475125, "ssid": "AutoPlay", "channel": 149, "address": "100.96.0.1"},
  "uplink":      {"state": "offline",  "reason": null, "since": 1761475125},
  "identity":    {"state": "provided", "reason": null, "since": 1761475120},
  "phone":       {"state": "idle",     "reason": null, "since": 1761475120, "active": false},
  "certificate": {"state": "self_signed", "reason": null, "since": 1761475120, "not_after": null},
  "update":      {"state": "current",  "reason": "1.2.0", "since": 1761475120},
  "system":      {"state": "ok",       "reason": null, "since": 1761475140, "temp_c": 61},
  "tesla":       {"state": "on",       "reason": null, "since": 1761475126}
}
```

Every domain is `{state, reason, since, ...extra}`. `since` is the wall-clock
time the state *or the reason* last changed; a page that polls can grey out an
entry whose `since` is far behind `updated`. `reason` is a short machine word
(or `null`); the page maps the words to sentences (`settings_page.BLUETOOTH_TEXT`,
`own_domain.message`), LuCI shows them as they are. The flat keys next to the
domains (`mode`, `ssid`, `home`, `entries`, `name`, `warning`, `own_name`,
`tesla_offline`, `tesla_upstream`, ...) are what the page and the receiver
already read from DashPlay; they stay.

## Domains

### bluetooth — the F50's controller and bluetoothd (6a)

| state | reason | meaning |
|---|---|---|
| `starting` | `helper-starting` | `board_zte_f50.py` is bringing up btattach/bluetoothd |
| `starting` | `powering` | the adapter is being powered, retries at 10/20/40 s (`retry_in`) |
| `on` | — | powered; the receiver may start |
| `failed` | `adapter-not-powered` | still not powered after three tries; retried every 60 s for ever |
| `failed` | `controller-init-failed` | Marlin3 firmware refused the configuration |
| `failed` | `controller-timeout` | the controller did not come up |
| `failed` | `bluez-missing` | the private BlueZ root is not installed (run `python3 /opt/autoplay/board_zte_f50.py --setup`) |
| `failed` | `rfkill` | the Bluetooth rfkill was not found after hci0 appeared, or unblocking it failed (1.1.0: every bluetooth-type rfkill is unblocked; `rfkill-hard` = hard-blocked) |
| `failed` | `hci-busy` | another program owns the HCI |
| `failed` | `hci-lost` | hci0 vanished (Wi-Fi chip reset); the helper is restarted |
| `failed` | `storage-conflict` | `/var/lib/bluetooth` belongs to something else |
| `failed` | `daemon-exit`, `helper-exit-<code>` | the helper exited; restart with back-off |

Extras: `retry_in` (seconds), `degraded` (true after five failures in ten
minutes; the restart delay is then at its cap). The page shows a red bar with
the sentence for the reason while the state is `failed`.

### wifi — the box's own AP

| state | reason |
|---|---|
| `up` | — (`ssid`, `channel`, `address`) |
| `waiting` | the platform's text, e.g. `Wi-Fi AutoPlay is not up yet` |

The AP is counted down only after three consecutive misses (`supervision.Misses`),
so one slow `ubus` answer does not restart anything.

### uplink — can the box itself reach the internet (SIM)

`online`, `offline`, `unknown`. Derived from the Tesla check plumbing
(`tesla_upstream`). Only informational: the car and the iPhone never depend on
it; DuckDNS and the certificate do.

### identity — the owner's accessory identity

`provided` or `missing` (`files-missing`). Only the presence of the two files
under `identity/offline-mfi/` is checked; their contents are never read by the
box side.

### phone — the paired iPhone (6i)

| state | reason |
|---|---|
| `live` | — : CarPlay is streaming (`active`) |
| `idle` | last bridge word, if any: `page-timeout`, `busy`, `aborted`, `timeout`, `refused`, `not-paired`, `powered-off`, `blocked`, `no-adapter`, `bluez-gone`, `auth-failed`, `unknown` |
| `declined` | — : the owner declined the last invitation on the page |
| `pairing-lost` | `pairing-lost` or `auth-failed` twice in a row: the iPhone forgot the pairing; the page says "请删除此 iPhone 后重新添加" |

The words come from `bt-bridge: reason=<word>` lines that `bridge.py` prints
on failure (`bridge_reasons.py`); the supervisor reads the last five.

### certificate — the viewer's TLS (6f)

| state | reason | page |
|---|---|---|
| `self_signed` | — | no own name (DuckDNS or DNSPod): the JVM self-signs, the car's browser warns once |
| `issuing` | `route` (no default route yet), `dns` (provider or CA does not resolve), `waiting-for-internet`, or — | acme.sh is running, or the readiness probe says the network is not there yet (looked at every 15 s, no back-off spent; 1.1.0 D1) |
| `ok` | — (`not_after`) | |
| `renewing` | — | within the renewal window |
| `expiring_soon` | retry reason or — | under 30 days: orange bar |
| `expired` | retry reason or — | orange bar: renews when the box is online |
| `failed` | `not-obtained`, or a failure code (1.1.0 D3): `curl<N>` (curl's exit code from acme.sh's log: 6 name lookup, 7 connect, 28 timeout), `timeout` (acme.sh's 600 s cap or openssl hanging), `network`, `certificate` (the issued chain did not verify), `acme` (anything else acme.sh refused) | the settings page turns the code into words (`own_domain.reason_text`); never a message, which could carry the token |

Retries 60/120/300/900 s then hourly; a WAN-up or NTP hotplug event wakes the
maintainer at once (`/var/run/autoplay/wan-up`). Every acme.sh request runs through a
curl shim with `--connect-timeout 10 --max-time 90 --retry 2` (`state/acme/bin/curl`,
1.1.0 D2; acme.sh 3.1.6 itself sends requests without a timeout and stays byte-identical).

### update — the online update (6e)

`current` (reason = latest version), `available` (reason = version),
`installing` (reason = phase), `failed` (reason = message), `check-failed`,
`check-off`. `update.healthy()` — used by the update's own health check and by
`recover()` after a power cut — requires `system` `ok` and `bluetooth` `on`.

### system — the receiver JVM and the board (6b)

| state | reason |
|---|---|
| `starting` | — |
| `ok` | — |
| `restarting` | `receiver-exit-<code>`, `receiver-liveness` (three missed `/api/display` probes), `retry_in` |
| `degraded` | same words; five failures in ten minutes, delay at cap; the page says "程序反复重启" |
| any | `hot` when the SoC is at 95 °C or more (`temp_c`); cleared when it cools |

### tesla — answering the car's connectivity checks (6c)

`on` (DNS entries and the port-80 redirect are in place), `off`, `failed`
(`plumbing: <error>`). The car is never deauthenticated to make it re-check;
the checks are answered as long as the AP is up.

## Rules

- Set, never toggle: a domain is written with its full `(state, reason)`
  every time it is evaluated; `since` moves only when something changed.
- A check that cannot run is a *reason*, not an exception: every periodic
  check runs under `supervision.Guard`, which logs the first failure and
  keeps the loop alive.
- Words are stable: a reason word is an interface for the page, LuCI and the
  log. Add words, do not rename them.
- The file is tmpfs and written on change only (`state.save_json(sync=False)`),
  so polling it costs nothing on the SD card.

## Receiver-side tasks noted here

- **`/time` hint for the clock floor (6g).** `clock_floor.py` never lets the
  clock go earlier than the last time seen, but without a SIM the box has no
  second time source. The viewer page already has `Date.now()` and the WebSocket
  to the receiver; a small receiver endpoint (or a line in `/api/display`) that
  exposes the newest client time would let the supervisor call
  `clock_floor.touch()` with a real time. Until then the floor only stops the
  clock from going backwards.
- **`receiver-access.json` in tmpfs.** `run-receiver.py` writes it only on
  change; moving it under `/var/run/autoplay` needs the receiver to read the
  path from an argument.
