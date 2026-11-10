#!/usr/bin/env python3
"""Run the AutoPlay receiver (OpenWrt); keep Wi-Fi credentials and tokens out of logs.

Reads the Wi-Fi handed to the iPhone from the JSON file the supervisor wrote (--hotspot: the network read
from ubus) and uses the system Python and the board's BlueZ/D-Bus.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import time


MILESTONES = [("RTSP listening", "receiver listening"), ("wireless bootstrap: iPhone", "invitation sent"),
              ("accepted by the iPhone", "invitation accepted"), ("CarPlay session active", "session active"),
              ("CarPlay is live", "CarPlay live")]


def durable_write(path, text):
    """Replace a file so that a power cut leaves either the old or the new content, never an empty file."""
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_browser_access(root, token, settings_port=18080):
    """Authorize viewers on the receiver LAN; admin login remains separate. The file carries the token and this box's
    settings port only (1.3.0): the page's Tesla ways are constants (web/src/flags.ts) and its sound is gone with
    the audio route (every sound is on the Tesla's Bluetooth, docs/AUDIO.md), so the carMusic/tesla and
    audioRouteNavigation fields of 1.0.0-1.2.0 are no longer written (boot.ts never read the first two)."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Unexpected browser token format")
    dist = root / "playport/web/dist"
    # Served by the receiver to the box's own page only (WebHub.ownPage): a script any site could include
    # gave the token away (audit 2026-10-13, A2). The player links "Add iPhone / network" to this box's
    # settings page (settings_page.py; port 80, or another one on OpenWrt, where LuCI has 80).
    (dist / "receiver-access.js").unlink(missing_ok=True)
    path = dist / "receiver-access.json"
    content = json.dumps({"token": token, "settingsPort": int(settings_port)}) + "\n"
    # Written only when it changes (the token is stable across starts): the file sits in the program directory on
    # the SD card, where the receiver serves it from; a symlink into tmpfs is not known to be followed by the
    # receiver's own-page check, so the write is avoided instead of moved (reliability_audit #11).
    try:
        if path.read_text() == content and path.stat().st_mode & 0o777 == 0o644:
            return False
    except OSError:
        pass
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(content)
    temporary.chmod(0o644)
    temporary.replace(path)
    assert path.read_text() == content
    return True


def drop_broken_cds_archive(state):
    """A dump interrupted by a restart leaves a truncated archive that the JVM then refuses ("bad magic number",
    "invalid archive") and never replaces, costing ~3 s on every start (DashPlay dp-0017, 2026-10-31: 3.9 MB instead
    of ~39 MB). The previous start's -Xlog:cds says so; drop the archive and the JVM dumps a fresh one on exit."""
    log = state / "cds.log"
    try:
        if log.exists() and any(mark in log.read_text(errors="replace") for mark in ("invalid archive", "bad magic number")):
            (state / "app-cds.jsa").unlink(missing_ok=True)
            return True
    except OSError:
        pass
    return False


# The iAP2 trace's Wi-Fi configuration field, a quoted string with " and \ escaped.
PASSPHRASE_FIELD = re.compile(r'(passphrase:\s*)"(?:[^"\\]|\\.)*"')


def heap_limit(meminfo):
    """The JVM heap ceiling for this board, from /proc/meminfo. 384 MB on the 1-2 GB boxes (F50 measured ~180 MB
    resident). A Snapdragon 410 stick has 512 MB, of which the modem and Wi-Fi firmware keep ~100 MB: a 384 MB
    ceiling there would let the heap outgrow the board, so 224 MB (not yet measured on a stick)."""
    found = re.search(r"^MemTotal:\s+(\d+) kB", meminfo, re.M)
    return "-Xmx224m" if found and int(found.group(1)) < 640 * 1024 else "-Xmx384m"


def redact(line, token, password):
    """A receiver log line without the viewer token or the hotspot password."""
    line = line.replace(token, "[REDACTED]")
    if line.lstrip().startswith("raw-body="):
        # The iAP2 trace's hex preview of a frame: for the Wi-Fi configuration it held the first
        # bytes of the password, which the plain-text redaction cannot see (2026-10-12).
        return line[:line.index("raw-body=")] + "raw-body=[not logged]\n"
    # The trace escapes " and \ in the password, so a plain replace missed such passwords (review 2026-10-12).
    line = PASSPHRASE_FIELD.sub(r'\1"[REDACTED]"', line)
    return line.replace(password, "[REDACTED]") if password else line



def kept_location(saved: dict) -> dict:
    """The viewer page's car-location switch and datum (1.4.0, docs/LOCATION.md), which only the receiver writes:
    config.json is rebuilt at every start, and without this a reboot switched the feature off again."""
    datum, picked = saved.get("carLocationDatum"), saved.get("carLocationDatumPicked") is True
    # 1.5.0: "auto" (GCJ-02 where the car's browser says mainland China, else WGS-84) is the default. A "wgs84" the
    # owner never chose - all 1.4.x wrote it - follows the default; "gcj02" was always a choice.
    if datum not in ("auto", "wgs84", "gcj02") or (datum == "wgs84" and not picked):
        datum = "auto"
    return {"carLocation": saved.get("carLocation") is True, "carLocationDatum": datum,
            "carLocationDatumPicked": picked or datum == "gcj02"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--channel", type=int, required=True, help="AP channel; may not be up yet")
    parser.add_argument("--hotspot", type=Path, required=True, help="JSON {ssid, passphrase} of the Wi-Fi handed to the iPhone")
    parser.add_argument("--bind-wait", type=int, default=0,
                        help="seconds the server may wait for --bind to be configured (started before the network)")
    parser.add_argument("--security", default="wpa2", choices=["open", "wpa2", "wpa3-transition", "wpa3"],
                        help="how that Wi-Fi is secured, as handed to the iPhone")
    parser.add_argument("--web-host", default="",
                        help="address the viewer listens on, e.g. 0.0.0.0 when the head unit reaches the box "
                             "through the car hotspot while AirPlay stays on --bind")
    parser.add_argument("--java", default="/usr/bin/java", help="Java 21 (OpenWrt: the autoplay-jre package)")
    parser.add_argument("--settings-port", type=int, default=18080, help="port of the box settings page")
    parser.add_argument("--viewer-port", type=int, default=0,
                        help="port of the viewer page (default: the saved config's, else 18443)")
    # Tesla mode (constant on this box; the flag stays so that a lab receiver can run without it, D8): every sound
    # over the car's own Bluetooth (the receiver offers no audio and no microphone) and the Tesla browser's fullscreen.
    parser.add_argument("--tesla", action="store_true", help="Tesla mode: car Bluetooth audio and the Tesla browser's fullscreen")
    parser.add_argument("--idle-release", type=int, default=300,
                        help="end wireless CarPlay after this many seconds without a viewer page (0: never)")
    parser.add_argument("--no-wireless", action="store_true",
                        help="no Bluetooth/Wi-Fi handoff yet (Bluetooth still coming up; the supervisor relaunches)")
    parser.add_argument("--prime-cds", action="store_true",
                        help="package postinst: start the JVM once on the loopback and stop it cleanly, so the AppCDS "
                             "archive exists before the first drive (it is otherwise written only at a clean exit)")
    args = parser.parse_args()
    root = args.root.resolve()
    os.umask(0o077)
    state = root / "state" / "receiver"
    state.mkdir(parents=True, exist_ok=True)
    config_path = state / "config.json"
    try:
        saved = json.loads(config_path.read_text())
    except (OSError, ValueError):
        # Missing, or cut to 0 bytes by a power loss while it was being saved (2026-10-11: the
        # receiver then failed every start); fall back to the default display.
        saved = {}
    hotspot = json.loads(args.hotspot.read_text())
    ssid = hotspot["ssid"]
    password = "" if args.security == "open" else hotspot["passphrase"]
    viewer = args.viewer_port if 1024 <= args.viewer_port <= 65535 else 0
    config = {
        "deviceName": "AutoPlay", "model": "AutoPlay", "manufacturer": "AutoPlay",
        "airPlayPort": 7000, "httpPort": viewer or saved.get("httpPort", 18443),
        "display": saved.get("display", {"width": 1280, "height": 720, "fps": 30, "uiScale": 100, "hevc": False}),
        "wireless": not args.no_wireless, "wifiSsid": ssid, "wifiPassphrase": password,
        "wifiChannel": args.channel, "wifiSecurity": args.security,
        "bluetoothDeviceAddress": None, "mdns": "jmdns",
        **kept_location(saved),
    }
    durable_write(config_path, json.dumps(config, indent=2) + "\n")
    assert json.loads(config_path.read_text()) == config
    token_path = state / "browser-token"
    try:
        token = token_path.read_text().strip()
    except OSError:
        token = ""
    if not re.fullmatch(r"[0-9a-f]{32}", token):   # missing, or emptied by a power cut
        token = secrets.token_hex(16)
        durable_write(token_path, token + "\n")
    write_browser_access(root, token, args.settings_port)
    env = dict(os.environ, BT_BRIDGE_PYTHON="/usr/bin/python3", BT_BRIDGE_READY_WAIT="15", BT_BRIDGE_CONNECT_TIMEOUT="8",
               BT_BRIDGE_RECOVERY_STATE=str(state / "bluetooth-recovery.stamp"),
               CARPLAY_PRESENCE_HELPER=str(root / "phone-presence.py"),
               CARPLAY_PRESENCE_INTERFACE=args.interface, CARPLAY_DEFAULT_PHONE="",
               CARPLAY_PRESENCE_STATE=str(state / "phone-presence.json"))
    if args.web_host:
        env["CARPLAY_WEB_HOST"] = args.web_host
    if args.bind_wait:
        env["CARPLAY_BIND_WAIT_MS"] = str(args.bind_wait * 1000)
    env["CARPLAY_IDLE_RELEASE_SECONDS"] = str(max(0, args.idle_release))
    # AppCDS keeps working after jar updates only if the archive is rebuilt; this JDK mapped a stale
    # archive, logged "shared class paths mismatch" and neither used nor re-dumped it (2026-10-10),
    # costing ~3 s per start. Drop the archive whenever any classpath jar changes.
    # The JVM's own archive too: after a Java update the old one failed its checksum and AppCDS was off for that start.
    jvm = Path(args.java).resolve().parent.parent / "lib/server"
    jars = [root / "launcher/onecloud-launcher.jar",
            *sorted((root / "playport/server/build/install/server/lib").glob("*.jar")),
            *(path for path in (jvm / "libjvm.so", jvm / "classes.jsa") if path.exists())]
    fingerprint = "\n".join(f"{jar.name} {jar.stat().st_size} {jar.stat().st_mtime_ns}" for jar in jars)
    stamp = state / "app-cds.classpath"
    if not stamp.exists() or stamp.read_text() != fingerprint:
        (state / "app-cds.jsa").unlink(missing_ok=True)
        stamp.write_text(fingerprint)
    drop_broken_cds_archive(state)
    crash = state / "crash"
    crash.mkdir(exist_ok=True)
    options = [
        "-Xms64m", heap_limit(Path("/proc/meminfo").read_text()),
        # An OutOfMemoryError in the accept or supervisor thread left a JVM that never invited the iPhone again;
        # exit instead, the supervisor restarts the receiver (reliability_audit #5). The crash report goes to the
        # SD card, where diagnostics can find it, not the program directory.
        "-XX:+ExitOnOutOfMemoryError", "-XX:ErrorFile=" + str(crash / "hs_err_%p.log"),
        # iAP2 bootstrap steps (message ids only, no credentials) for diagnosing a stalled Wi-Fi handoff.
        "-Dorg.slf4j.simpleLogger.log.wireless=debug",
        # Milliseconds since JVM start on every line, for boot-time profiling.
        "-Dorg.slf4j.simpleLogger.showDateTime=true",
        # Prefer ChaCha20 for the browser TLS link; see tls.security for the measured reason.
        "-Djava.security.properties=" + str(root / "tls.security"),
        # AppCDS: archive loaded application classes on first clean exit, map them on later starts.
        "-Xlog:cds=info:file=" + str(state / "cds.log"),
        "-Xlog:gc:file=" + str(state / "gc.log"),
        "-XX:+AutoCreateSharedArchive", "-XX:SharedArchiveFile=" + str(state / "app-cds.jsa"), "-cp",
        # launcher/onecloud-launcher.jar (source in launcher/) warms the handshake crypto in parallel.
        str(root / "launcher/onecloud-launcher.jar") + ":" + str(root / "playport/server/build/install/server/lib/*"),
        "onecloud.Launcher", "--bind", args.bind,
        # Receiver builds before 1.3.0 default to page audio (and 1.0.0's to calls on the page): these two flags keep
        # every sound on the Tesla's Bluetooth with them too. A 1.3.0 receiver accepts and ignores both.
        *(["--car-voice", "--audio-route-navigation", "bluetooth"] if args.tesla else []),
        "--identity-dir", str(root / "identity"), "--state-dir", str(state),
        "--bt-bridge", str(root / "linux-bt-bridge/bt-bridge"), "--token", token,
    ]
    argfile = state / "java.args"
    argfile.write_text("\n".join(json.dumps(value) for value in options) + "\n")

    def expendable():
        # Under memory pressure the OOM killer should take the JVM first, never bluetoothd (board_zte_f50.py -500)
        # or the supervisor: +500 for the JVM.
        try:
            Path("/proc/self/oom_score_adj").write_text("500\n")
        except OSError:
            pass

    if args.prime_cds:
        return prime_cds(args.java, argfile, root, state, env)
    # The supervisor signals the whole process group; outlive the JVM so it can finish writing the
    # AppCDS archive on exit (exiting first let systemd SIGKILL it mid-dump). A Python function
    # handler, unlike SIG_IGN, is reset to default in the exec'd JVM, which keeps its own handling.
    signal.signal(signal.SIGTERM, lambda *_: None)
    with subprocess.Popen(
        [args.java, "@" + str(argfile)], cwd=root / "playport", env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", preexec_fn=expendable,
    ) as process:
        (state / "java.pid").write_text(str(process.pid) + "\n")
        for line in process.stdout:
            line = redact(line, token, password)
            print(line, end="", flush=True)
            # The JVM's timestamps follow the wall clock, which jumps when time is synced during boot
            # (~27 s on 2026-10-11); mark milestones on the boot clock, comparable with "boot" lines.
            milestone = next((name for key, name in MILESTONES if key in line), None)
            if milestone:
                print(f"boot {time.monotonic():.2f}s {milestone}", flush=True)
        raise SystemExit(process.wait())


def prime_cds(java, argfile, root, state, env, listen_timeout=60, exit_timeout=45):
    """Run the JVM once until it listens, then stop it cleanly so that -XX:+AutoCreateSharedArchive writes the
    AppCDS archive (reliability_audit #19: a box that is only ever power-cut never exits cleanly, and every
    update drops the archive). The archive is skipped when it is already current for this classpath."""
    if (state / "app-cds.jsa").exists():
        print("AppCDS archive present", flush=True)
        return 0
    print("priming the AppCDS archive", flush=True)
    with subprocess.Popen([java, "@" + str(argfile)], cwd=root / "playport", env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace") as process:
        deadline = time.monotonic() + listen_timeout
        listening = False
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline and process.poll() is None:
            if selector.select(timeout=1):
                line = process.stdout.readline()
                if not line:
                    break
                if "RTSP listening" in line or "listening" in line.lower():
                    listening = True
                    break
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=exit_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        ok = (state / "app-cds.jsa").exists()
        print(f"AppCDS archive {'written' if ok else 'not written'} (receiver {'listened' if listening else 'did not listen'})",
              flush=True)
        return 0 if ok else 1


if __name__ == "__main__":
    main()
