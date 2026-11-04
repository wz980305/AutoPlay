#!/usr/bin/env python3
"""Online update of AutoPlay from its signed release manifest (the DashPlay design, docs/在线升级方案-20261019.md).

    update.py check   [--root /opt/autoplay]   # a newer release? -> state/update-check.json
    update.py launch  [--root /opt/autoplay]   # start `install` apart from the service, which it restarts
    update.py install [--root /opt/autoplay]   # download, verify, back up, install, check; go back on failure

Every release carries autoplay-update.json and its Ed25519 signature. Only a manifest signed by the key in
update-key.pem (beside this file) counts, and every downloaded file must match it, so a mirror needs no trust.
The autoplay, luci-app-autoplay and zh-cn packages (the JRE only when its version changed) with apk, refusing a
plan with any kernel, kmod or BlueZ package (the ZTE F50 runs a vendor 5.4 kernel); the packages of the installed
version are fetched first to go back to.
Never while CarPlay is in use, and never by itself: the box only checks (once a day) and says so.
Progress goes to state/update-status.json, which the settings page and LuCI show.
"""
import argparse
import email.utils
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

# The fork's release location (github.com/wz980305/AutoPlay; no signed release exists yet, docs/ROADMAP.md). The DashPlay feeds carry packages
# with the old names, which this box no longer installs).
OWNER = os.environ.get("AUTOPLAY_UPDATE_OWNER", "wz980305")
REPO = os.environ.get("AUTOPLAY_UPDATE_REPO", "AutoPlay")
FEED_REPO = os.environ.get("AUTOPLAY_UPDATE_FEED_REPO", "openwrt-autoplay")
# Where the latest manifest and the installed version's OpenWrt packages (to go back to) come from. The environment
# may point both at a test server (scripts/openwrt/lab-test.sh); the signature check is the same.
LATEST = os.environ.get("AUTOPLAY_UPDATE_LATEST", f"https://github.com/{OWNER}/{REPO}/releases/latest/download/")
PREVIOUS_FEED = os.environ.get("AUTOPLAY_UPDATE_FEED",
                               f"https://github.com/{OWNER}/{FEED_REPO}/releases/download/v{{version}}/")
VERSION_FILE = "version.txt"
MANIFEST = "autoplay-update.json"
SIGNATURE = MANIFEST + ".sig"
KEY = Path(__file__).resolve().with_name("update-key.pem")
OPENSSL = os.environ.get("AUTOPLAY_OPENSSL", "openssl")   # OpenSSL 3 on the boxes (a Mac's own is LibreSSL)
# Tried after GitHub itself, as a URL prefix. The signature makes any mirror safe; uci autoplay.main.update_mirror
# replaces this list, "none" for GitHub only.
MIRRORS = ("https://ghfast.top/",)
OPENWRT_PACKAGES = ("autoplay", "luci-app-autoplay", "luci-i18n-autoplay-zh-cn")
# The DashPlay names of the packages this fork replaces: a box still running them is moved over by the first AutoPlay
# update (they are removed first, their prerm keeps state/, the autoplay postinst migrates /opt/dashplay/state), and
# their release feed is where the way back lies until then.
LEGACY_PACKAGES = ("dashplay", "luci-app-dashplay", "luci-i18n-dashplay-zh-cn")
LEGACY_ROOT = "/opt/dashplay"   # where the old service kept state/ and identity/
FORBIDDEN = re.compile(r"^(kernel|kmod-|bluez)")   # never through an online update (ZTE F50: 5.4 kernel)
CHECK_EVERY = 24 * 3600
BACKUP = "autoplay-update-backup.tar.gz"   # beside the program directory: the owner's data before the last update
CACHE = "autoplay-update-cache"            # beside the program directory: the previous packages, until the next boot proves the new ones
JOURNAL = "state/update-journal.json"      # what an install is doing, for recovery at the next supervisor start (reliability_audit #8)
STATUS_FILE = Path("/var/run/autoplay/status.json")   # the supervisor's status (status_model.py): the health check reads it


class UpdateError(Exception):
    """Why an update stops, in words for the owner (Chinese, shown on the page)."""


class NotFound(UpdateError):
    """Every source answered 404: the file is not published, not a network problem."""


def is_openwrt():
    return Path("/etc/openwrt_release").exists()


def run(*args, timeout=300):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)


def version_key(version):
    """'2026.10.19.1' -> (2026, 10, 19, 1); None for anything else (unknown versions are never newer)."""
    if not version or not re.fullmatch(r"\d+(\.\d+)*", version):
        return None
    return tuple(int(part) for part in version.split("."))


def newer(latest, current):
    latest, current = version_key(latest), version_key(current)
    return latest is not None and (current is None or latest > current)


def mirrors(root=None, openwrt=True):
    """GitHub first, then the configured mirrors (prefixes)."""
    try:
        value = run("uci", "-q", "get", "autoplay.main.update_mirror", timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        value = ""
    if value == "none":
        return ()
    return tuple(value.split()) if value else MIRRORS


def fetch(url, prefixes=(), limit=1 << 20, target=None, sha256=None, size=None):
    """Bytes of url (or, with target, the file written there), from GitHub or else each mirror prefix. With sha256
    and size the download must match them exactly."""
    errors, codes = [], []
    for candidate in [url] + [prefix + url for prefix in prefixes]:
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "AutoPlay-update"})
            with urllib.request.urlopen(request, timeout=30) as response:
                digest, total = hashlib.sha256(), 0
                out = open(target, "wb") if target else None
                chunks = []
                try:
                    while True:
                        chunk = response.read(1 << 16)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > (size if size is not None else limit):
                            raise UpdateError("下载的文件比预期大，已停止")
                        digest.update(chunk)
                        (out.write(chunk) if out else chunks.append(chunk))
                finally:
                    if out:
                        out.close()
            if sha256 and (digest.hexdigest() != sha256 or total != size):
                raise UpdateError("下载的文件与签名清单不符")
            return target if target else b"".join(chunks)
        except (OSError, UpdateError, ValueError, http.client.HTTPException) as error:
            if hasattr(error, "close"):   # an HTTPError holds its response open
                error.close()
            errors.append(f"{candidate.split('/')[2]}: {error}")
            codes.append(getattr(error, "code", None))
    if all(code == 404 for code in codes):
        raise NotFound("下载失败（" + "；".join(errors)[-300:] + "）")
    raise UpdateError("下载失败（" + "；".join(errors)[-300:] + "）。网络恢复后再试，或在设置里换一个镜像")


def verify(data, signature, key=KEY):
    """True when signature is the release key's Ed25519 signature of data (OpenSSL 3)."""
    with tempfile.TemporaryDirectory(prefix="autoplay-verify.") as work:
        (Path(work) / "m").write_bytes(data)
        (Path(work) / "s").write_bytes(signature)
        try:
            out = run(OPENSSL, "pkeyutl", "-verify", "-pubin", "-inkey", str(key), "-rawin",
                      "-in", str(Path(work) / "m"), "-sigfile", str(Path(work) / "s"), timeout=30)
        except FileNotFoundError:
            raise UpdateError("系统缺少 openssl，无法核对签名")
    return out.returncode == 0 and "Signature Verified Successfully" in out.stdout


def latest_manifest(root, openwrt, key=KEY):
    prefixes = mirrors(root, openwrt)
    data = fetch(LATEST + MANIFEST, prefixes, limit=1 << 20)
    signature = fetch(LATEST + SIGNATURE, prefixes, limit=4096)
    if not verify(data, signature, key):
        raise UpdateError("更新清单的签名不对，已忽略（可能是镜像或网络被篡改）")
    manifest = json.loads(data)
    if manifest.get("format") != 1 or not version_key(manifest.get("version")):
        raise UpdateError("更新清单格式不认识：请先手动升级到较新的版本")
    return manifest


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def program_matches(root, files):
    """The program under root has every file of the release ({relative path: sha256}) as released."""
    root = Path(root)
    return bool(files) and all((root / path).is_file() and file_sha256(root / path) == digest
                               for path, digest in files.items())


def apk_version(name, listing=None):
    """'2026.10.19.1-r1' for an installed autoplay-2026.10.19.1-r1, or None. From the list of every installed
    package: `apk info -v NAME` prints the description instead (apk 3, OpenWrt 25.12)."""
    out = (listing if listing is not None else run("apk", "info", "-v", timeout=30).stdout).split()
    for word in out:
        if word.startswith(name + "-") and re.fullmatch(r"[0-9][^-]*-r\d+", word[len(name) + 1:]):
            return word[len(name) + 1:]
    return None


def bundled_version(root):
    """The release a program bundle was built for (build-bundle.sh writes version.txt for a release), or None
    for a development build and the releases before 2026.10.20."""
    try:
        return (Path(root) / VERSION_FILE).read_text().strip() or None
    except OSError:
        return None


def installed_name(listing=None):
    """"autoplay" or, on a box not yet moved over, "dashplay"; None when neither is installed."""
    for name in ("autoplay", "dashplay"):
        if apk_version(name, listing):
            return name
    return None


def current_version(root=None, openwrt=True):
    full = apk_version("autoplay") or apk_version("dashplay")
    return full.rsplit("-r", 1)[0] if full else None


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def compare(root, openwrt, manifest):
    """What the page shows about the installed program and this release."""
    current = current_version(root, openwrt)
    online, reason = bool(manifest.get("online")), "" if manifest.get("online") else "这一版改了系统"
    available = newer(manifest["version"], current)
    return {"current": current, "latest": manifest["version"], "notes": manifest.get("notes", ""),
            "available": available, "online": online, "reason": reason}


def check(root, openwrt=None, key=KEY, manifest=None):
    """Compare the installed program with the latest signed release; write and return state/update-check.json."""
    root = Path(root)
    openwrt = is_openwrt() if openwrt is None else openwrt
    result = {"checked_at": int(time.time())}
    try:
        result.update(compare(root, openwrt, manifest or latest_manifest(root, openwrt, key)))
    except UpdateError as error:
        result["error"] = str(error)
    except (ValueError, KeyError, subprocess.SubprocessError) as error:
        result["error"] = f"检查更新失败：{error}"
    save(root / "state/update-check.json", result)
    return result


def carplay_in_use(root):
    return bool(read(Path(root) / "state/receiver/phone-presence.json").get("active"))


def forbidden_in_plan(simulation):
    """Packages an apk --simulate output would touch that an online update must not (kernel, kmod, BlueZ)."""
    names = re.findall(r"^\(\d+/\d+\) (?:Installing|Upgrading|Downgrading|Replacing|Purging) (\S+)", simulation, re.M)
    return sorted({name for name in names if FORBIDDEN.match(name)})


def previous_packages(version, prefixes, work, names=OPENWRT_PACKAGES, key=KEY):
    """The installed release's packages, checked against Ed25519-signed SHA256SUMS. `work` is
    the persistent cache (CACHE), so a power cut mid-install still finds them at the next start (recover).
    names: the package names of that release (LEGACY_PACKAGES for a DashPlay box being moved over)."""
    base = PREVIOUS_FEED.format(version=version)
    try:
        data = fetch(base + "SHA256SUMS", prefixes, limit=1 << 16)
        signature = fetch(base + "SHA256SUMS.sig", prefixes, limit=4096)
    except NotFound:
        raise UpdateError(f"找不到当前版本 {version} 的安装包（它不是正式发布的版本），升级失败时无法退回，已停止。"
                          "请按装机说明手动升级") from None
    if not verify(data, signature, key):
        raise UpdateError("回滚包校验清单的签名不对，无法信任回滚包，已停止升级")
    sums = data.decode()
    files = []
    for line in sums.splitlines():
        digest, _, name = line.partition("  ")
        if any(re.fullmatch(rf"{re.escape(package)}-[0-9][^/]*\.apk", name) for package in names):
            target = Path(work) / "previous" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            fetch(base + name, prefixes, target=target, limit=256 << 20)   # no size here: the hash below decides
            if file_sha256(target) != digest.strip():
                raise UpdateError("当前版本的安装包校验不符，无法保证能退回，已停止")
            files.append(target)
    if len(files) != len(names):
        raise UpdateError(f"找不到当前版本 {version} 的安装包，升级失败时无法退回，已停止")
    return files


def settings_port():
    port = run("uci", "-q", "get", "autoplay.main.settings_port", timeout=5).stdout.strip()
    return int(port) if port.isdigit() else 18080


def healthy(snapshot, port_answers):
    """The service is up: the settings page answers, the receiver (JVM) serves and Bluetooth is powered
    (reliability_audit #8: "the port answers" alone let a version whose JVM or Bluetooth failed pass)."""
    if not port_answers:
        return False
    if not snapshot:
        return False
    system = snapshot.get("system", {})
    bluetooth = snapshot.get("bluetooth", {})
    return system.get("state") == "ok" and bluetooth.get("state") == "on"


def service_up(port, seconds=240, steady=15, status_file=STATUS_FILE, clock=time.monotonic, sleep=time.sleep):
    """The autoplay service runs: its settings page answers, its status says the receiver serves and Bluetooth is
    powered, and that still holds `steady` seconds later (on the F50 the page answered 2 s after apk returned,
    before a crash could show). Waits up to `seconds`: the JVM takes ~40 s, Bluetooth up to a minute."""
    def answers():
        try:
            socket.create_connection(("127.0.0.1", port), 3).close()
            return True
        except OSError:
            return False

    def snapshot():
        try:
            return json.loads(Path(status_file).read_text())
        except (OSError, ValueError):
            return {}

    until = clock() + seconds
    while clock() < until:
        if healthy(snapshot(), answers()):
            sleep(steady)
            if healthy(snapshot(), answers()):
                return True
        sleep(3)
    return False


def backup(root, openwrt):
    """The owner's data (pairings, certificates, identity, settings), logs left out; only the latest is kept."""
    root = Path(root)
    target = root.parent / BACKUP
    with tarfile.open(target.with_suffix(".tmp"), "w:gz") as out:
        for name in ("state", "identity"):
            if (root / name).exists():
                out.add(root / name, arcname=name,
                        filter=lambda info: None if re.match(r"state/(logs|diag)(/|$)", info.name) else info)
        config = Path("/etc/config/autoplay")
        if config.exists():
            out.add(config, arcname="config/" + config.name)
    os.chmod(target.with_suffix(".tmp"), 0o600)
    os.replace(target.with_suffix(".tmp"), target)
    return target


def journal_path(root):
    return Path(root) / JOURNAL


def write_journal(root, **fields):
    save(journal_path(root), {**fields, "at": int(time.time())})


def install_openwrt(root, manifest, status, work, key=KEY):
    current = current_version(root, True)
    if not current:
        raise UpdateError("没有找到已安装的 autoplay 软件包")
    legacy = installed_name() == "dashplay"   # the first AutoPlay update of a DashPlay box
    prefixes = mirrors(root, True)
    arch = Path("/etc/apk/arch").read_text().strip()
    feed = manifest["openwrt"]
    wanted = {name: feed["packages"][name] for name in OPENWRT_PACKAGES}
    if apk_version("autoplay-jre") != feed["jre"]["version"]:
        if arch not in feed["jre"]["files"]:
            raise UpdateError(f"这一版没有 {arch} 的 Java 运行环境")
        wanted["autoplay-jre"] = feed["jre"]["files"][arch]
    # The way back first: without it nothing is installed, so the new release is not fetched for nothing. Both
    # package sets go to the persistent cache, so a power cut leaves recover() something to work with.
    cache = Path(root).parent / CACHE
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    status("downloading", f"正在下载当前版本 {current} 的安装包（升级失败时用来退回）")
    previous = previous_packages(current, prefixes, cache, LEGACY_PACKAGES if legacy else OPENWRT_PACKAGES, key)
    status("downloading", f"正在下载 {manifest['version']}（{sum(f['size'] for f in wanted.values()) // 1048576} MB）")
    files = []
    for entry in wanted.values():
        files.append(fetch(feed["base"] + entry["file"], prefixes, target=cache / entry["file"],
                           sha256=entry["sha256"], size=entry["size"]))
    status("checking", "正在核对升级计划")
    run("apk", "update", timeout=300)   # without the index the simulation misses dependencies (F50, 2026-10-19)
    simulation = run("apk", "add", "--upgrade", "--simulate", "--allow-untrusted", *map(str, files))
    if simulation.returncode != 0:
        raise UpdateError("升级计划不成立：" + (simulation.stderr or simulation.stdout).strip()[-300:])
    blocked = forbidden_in_plan(simulation.stdout)
    if blocked:
        raise UpdateError("升级会改动内核、内核模块或系统蓝牙（" + "、".join(blocked) + "），已停止，请按说明手动升级")
    status("installing", "正在安装，CarPlay 会断开约 1 分钟")
    port = settings_port()
    write_journal(root, phase="installing", target=manifest["version"], previous=current, legacy=legacy,
                  new_files=[str(f) for f in files], previous_files=[str(f) for f in previous])
    if legacy:
        # Different package names: the DashPlay packages go first (their prerm stops the service and keeps
        # /opt/dashplay/state), the autoplay postinst then moves state, identity and the uci section over.
        run("apk", "del", *LEGACY_PACKAGES, timeout=300)
    result = run("apk", "add", "--upgrade", "--allow-untrusted", *map(str, files), timeout=600)
    if result.returncode == 0 and service_up(port):
        write_journal(root, phase="done", target=manifest["version"], previous=current)
        return
    status("restoring", "新版本没有正常启动，正在退回原来的版本")
    write_journal(root, phase="restoring", target=manifest["version"], previous=current, legacy=legacy,
                  previous_files=[str(f) for f in previous])
    if legacy:
        # Different names again: the autoplay packages go, the DashPlay ones come back. The state is still at
        # /opt/autoplay here; install() moves it back to /opt/dashplay as its very last step (return_state_to_legacy),
        # after the journal and the status file are written, so nothing is left behind at /opt/autoplay/state that
        # would stop the postinst of the next attempt from migrating.
        run("apk", "del", *OPENWRT_PACKAGES, timeout=300)
    back = run("apk", "add", "--allow-untrusted", *map(str, previous), timeout=600)
    up = back.returncode == 0 and service_up(port)
    write_journal(root, phase="rolled-back" if up else "failed", target=manifest["version"], previous=current,
                  legacy=legacy)
    raise UpdateError(f"新版本没有正常启动，已退回 {current}" if up else
                      "新版本没有正常启动，退回也没有成功：请按说明用电脑恢复（数据备份在 /opt/" + BACKUP + "）")


def return_state_to_legacy(root, legacy_root=None):
    """After a DashPlay box's first AutoPlay update was rolled back: move state/ and identity/ back to where the
    reinstalled DashPlay service reads them. The journal (phase rolled-back, legacy) says whether that happened; the
    update-status file travels with the state, so the old settings page shows "已退回". Returns what was moved."""
    root = Path(root)
    journal = read(journal_path(root))
    if not (journal.get("legacy") and journal.get("phase") == "rolled-back"):
        return []
    legacy_root = Path(legacy_root or LEGACY_ROOT)
    moved = []
    for name in ("state", "identity"):
        if (root / name).exists() and not (legacy_root / name).exists():
            try:
                legacy_root.mkdir(parents=True, exist_ok=True)
                shutil.move(str(root / name), str(legacy_root / name))
                moved.append(name)
            except OSError:
                pass
    return moved


def recover(root, say=print, version=None, run_apk=None):
    """At supervisor start: finish or roll back an update the power cut (reliability_audit #8). Returns a short
    text when something was done, None when the journal is clean. version/run_apk are for tests."""
    root = Path(root)
    journal = read(journal_path(root))
    phase = journal.get("phase")
    if phase not in ("installing", "restoring"):
        if phase in ("done", "rolled-back", "failed") and time.time() - journal.get("at", 0) > 2 * 86400:
            journal_path(root).unlink(missing_ok=True)   # old news
            shutil.rmtree(root.parent / CACHE, ignore_errors=True)
        return None
    current = version if version is not None else current_version(root, True)
    apk = run_apk or (lambda files: run("apk", "add", "--allow-untrusted", *files, timeout=600).returncode == 0)
    if phase == "installing" and current == journal.get("target"):
        # apk finished, the health check never ran: let this boot be the check (the supervisor's status says).
        write_journal(root, phase="done", target=journal.get("target"), previous=journal.get("previous"), recovered=True)
        return f"install of {current} completed before the power cut; running it now"
    previous = [path for path in journal.get("previous_files", []) if Path(path).is_file()]
    if not previous:
        write_journal(root, phase="failed", target=journal.get("target"), previous=journal.get("previous"),
                      recovered=True, note="previous packages missing")
        say("update journal: the interrupted update left no packages to go back to")
        return "interrupted update: nothing to roll back with"
    if apk(previous):
        write_journal(root, phase="rolled-back", target=journal.get("target"), previous=journal.get("previous"), recovered=True)
        save(root / "state/update-status.json", {"phase": "failed", "at": int(time.time()),
                                                 "message": f"上次升级到 {journal.get('target')} 时断电，已退回 {journal.get('previous')}"})
        return f"rolled back the interrupted update to {journal.get('previous')}"
    write_journal(root, phase="failed", target=journal.get("target"), previous=journal.get("previous"), recovered=True)
    return "interrupted update: rollback failed"


def install(root, openwrt=None, key=KEY):
    root = Path(root)
    openwrt = is_openwrt() if openwrt is None else openwrt
    status_file = root / "state/update-status.json"

    def status(phase, message, **extra):
        save(status_file, {"phase": phase, "message": message, "at": int(time.time()), **extra})

    status("checking", "正在检查最新版本")
    try:
        manifest = latest_manifest(root, openwrt, key)
        found = check(root, openwrt, key, manifest)
        if not found.get("available"):
            status("done", f"已是最新版本 {manifest['version']}")
            return 0
        if not found.get("online"):
            raise UpdateError(f"{found.get('reason') or '这一版改了系统'}，不能在线升级 {manifest['version']}："
                              "请按装机说明用刷机包升级")
        if carplay_in_use(root):
            raise UpdateError("正在使用 CarPlay：停车、断开后再升级")
        if shutil.disk_usage(tempfile.gettempdir()).free < 200 << 20:
            raise UpdateError("临时空间不足 200 MB，无法下载")
        status("backup", "正在备份配对、证书和设置")
        saved = backup(root, openwrt)
        with tempfile.TemporaryDirectory(prefix="autoplay-update.") as work:
            install_openwrt(root, manifest, status, work, key)
        status("done", f"已升级到 {manifest['version']}", version=manifest["version"], backup=str(saved))
        check(root, openwrt, key, manifest)
        return 0
    except UpdateError as error:
        status("failed", str(error))
    except Exception as error:   # whatever happened, the page must not keep saying "installing"
        status("failed", f"升级出错：{type(error).__name__}: {str(error)[-200:]}")
    return_state_to_legacy(root)   # last: after this nothing may write under root/state
    return 1


def running(root):
    """An install started less than 20 minutes ago that has not finished."""
    state = read(Path(root) / "state/update-status.json")
    return state.get("phase") not in (None, "done", "failed") and time.time() - state.get("at", 0) < 1200


def launch(root, openwrt=None):
    """Start an install apart from the autoplay service (it restarts that service, and procd would end a child with
    it). Returns a message for the page. A procd service made for this one run over ubus, not an init script, since
    installing a package starts every init script in it (default_postinst; the F50 began an update by itself when the
    package with one was installed, 2026-10-19)."""
    root = Path(root)
    openwrt = is_openwrt() if openwrt is None else openwrt
    if running(root):
        return "正在升级，请稍候"
    if carplay_in_use(root):
        return "正在使用 CarPlay：停车、断开后再升级"
    install = [sys.executable, str(Path(__file__).resolve()), "install", "--root", str(root)]
    service = {"name": "autoplay-update", "instances": {"update": {"command": install, "stdout": True, "stderr": True}}}
    command = ["ubus", "call", "service", "set", json.dumps(service)]
    save(root / "state/update-status.json", {"phase": "starting", "message": "正在开始升级", "at": int(time.time())})
    try:
        # The finished run before, if any: procd would not start an unchanged instance again.
        run("ubus", "call", "service", "delete", json.dumps({"name": "autoplay-update"}), timeout=30)
        out = run(*command, timeout=30)
        why = "" if out.returncode == 0 else (out.stderr or out.stdout).strip()[-200:] or f"退出码 {out.returncode}"
    except (OSError, subprocess.SubprocessError) as error:   # e.g. a version without the update service
        why = str(error)
    if why:   # never leave "starting" behind: it would refuse every try for 20 minutes
        save(root / "state/update-status.json", {"phase": "failed", "message": "无法启动升级：" + why,
                                                 "at": int(time.time())})
        return "无法启动升级：" + why
    return "已开始升级，约 2–5 分钟，期间 CarPlay 会断开"


# Plain HTTP on purpose: its Date header needs no clock, while HTTPS fails on a clock off by months. The F50 has no
# battery-backed clock: it starts from its last saved time, and without a SIM NTP never gets through.
CLOCK_URLS = ("http://www.baidu.com/", "http://connectivitycheck.gstatic.com/generate_204")
CLOCK_SLACK = 600


def clock_from_http(urls=CLOCK_URLS, now=time.time, set_clock=None, opener=urllib.request.urlopen):
    """Set the system clock from the first reachable server's Date header when it is off by more than 10 minutes.
    Returns the offset applied in seconds, 0 when the clock was right, None when no server answered."""
    for url in urls:
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "AutoPlay-clock"}), timeout=10) as response:
                date = response.headers.get("Date")
        except Exception:
            continue
        try:
            server = email.utils.parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            continue
        offset = server - now()
        if abs(offset) <= CLOCK_SLACK:
            return 0
        (set_clock or (lambda t: time.clock_settime(time.CLOCK_REALTIME, t)))(server)
        return offset
    return None


def checker(root, stopped, enabled=True, first=120):
    """Supervisor thread body: check once soon after start, then daily. Never installs."""
    if not enabled or stopped.wait(first):
        return
    while True:
        try:
            clock_from_http()
        except Exception:   # a wrong clock must not stop the check either
            pass
        try:
            check(root)
        except Exception:   # a check must never take the service down
            pass
        if stopped.wait(CHECK_EVERY):
            return


def main(argv=None):
    os.umask(0o077)   # status, check and backup files hold nothing for others; the backup holds keys
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "launch", "install"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    if args.command == "check":
        print(json.dumps(check(args.root), ensure_ascii=False))
        return 0
    if args.command == "launch":
        print(launch(args.root))
        return 0
    return install(args.root)


if __name__ == "__main__":
    sys.exit(main())
