# Test baseline (untouched import, commit c138aae)

> 历史记录（2026-10-26）。截至 1.2.0（2026-11-03）：`tests/onecloud` 263 个全部通过，`test_f50_tools.py` 仍在并通过；下文的"待删除"没有发生。

Recorded 2026-10-26 before any trimming, on the tree imported from DashPlay
`e3beae4` (box/) and openwrt-dashplay `5f17702` (openwrt/).

Toolchain: Python 3.13.16, stdlib `unittest` only, no network. Both suites are
run from `box/`; the tests put `scripts/onecloud` (or `linux/bt-bridge`) on
`sys.path` themselves.

## `python3 -m unittest discover -s tests/onecloud`

    Ran 375 tests in 27.8s
    FAILED (errors=1)

The one error is environmental, not a code defect:

- `test_f50_tools.MacToolsTests.test_prebuilt_helpers_match_their_checksums_and_pinned_sources`
  reads `box/tools/mac-arm64/SHA256SUMS`. The `tools/` directory (prebuilt
  `spd_dump`/`lz4` binaries for macOS and Windows) was not imported into this
  fork, so the file does not exist. The test and `tools/` are both scheduled
  for deletion (work item 4: mac/windows bootstrap scripts and `tools/`).

Everything else passes: 374 tests.

## `python3 -m unittest discover -s tests/bluetooth`

    Ran 7 tests in 0.14s
    FAILED (errors=3)

The three errors are import failures: `test_bluez.py` (20 tests),
`test_recovery.py` (9 tests) and `test_probe.py` (4 tests) import `dbus_next`,
which is not installed here and cannot be fetched without network access.
`dbus-daemon` itself is present (`/usr/bin/dbus-daemon`). Only
`test_relay.py` (4 tests, plus 3 loader stubs counted by unittest) runs.

So the Bluetooth bring-up/recovery tests are **not executable in this
environment**. They are kept and must be run on a machine with `dbus-next
0.2.3` (`linux/bt-bridge/requirements.txt`) before a release. Tests added by
this fork for `bridge.py` are written so that the pure functions (reason-code
mapping) run without `dbus_next`.

## Source size

`wc -l` over `*.py *.sh *.js *.java Makefile *.init *.config *.po *.json
autoplay-update` under `box/` and `openwrt/`, excluding `__pycache__`:
**20,425 lines**.

Per-tree: `box/scripts/onecloud` + `box/scripts` + `box/linux` ≈ 11.5k,
`box/tests` ≈ 6.1k, `openwrt/` ≈ 0.9k, the rest JSON/skill data.
