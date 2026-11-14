"""The box page on the settings port (18080, plain HTTP): iPhones, status, program update, diagnostics.

The router (OpenWrt, LuCI) owns the network and the uci settings; this page adds and removes iPhones, shows
what the box is doing and starts an update. It is also the always-up page while the receiver is not (identity
missing, Wi-Fi waiting, Bluetooth down), and in Tesla mode the responder for the car's connectivity checks
(tesla_checks.py, behind tesla_openwrt's port-80 redirect). Only clients on the Wi-Fi handed to the iPhone may
use it. Markup lives in settings_ui.py; this module holds the behaviour. Since 1.5.0 the page is laid out as the
CarPlay page's "AutoPlay 设置" panel: categories (iPhone, 网络, 更新, 高级) and one column of groups.

The Debian first-run wizard, hotspot/car/internet forms, remote debugging and DuckDNS form of DashPlay are gone
(code_inventory_trimming.md 2.2): the F50 is the only target.
"""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import re
from pathlib import Path
import secrets
import threading
import time
import urllib.parse

import factory_reset
import own_domain
from pairing_window import PairingWindow
import settings_ui as ui
import state as state_files
import tesla_checks
import diagnostics
import update

MAX_BODY = 4096
CHECK_LOG_EVERY = 60   # s: one diag line per car connectivity check and reply, repeats counted into the next
# Names a request may carry in its Host header besides the box's own addresses (reliability_audit #16: a Host
# check against DNS rebinding; the Tesla check names are answered before this and never reach the page).
LOCAL_HOSTS = {state_files.LOCAL_NAME, "dashplay.lan", state_files.MDNS_NAME, "localhost"}
BLUETOOTH_TEXT = {   # reason codes of the bluetooth domain (status_model) -> what the owner reads (S2)
    # Plain words since 1.4.1; the chip, rfkill and paths are in the diagnostics record. bluez-missing keeps its
    # command: only whoever installed the box sees it, and it is the fix.
    "helper-starting": "蓝牙正在启动",
    "powering": "蓝牙正在上电",
    "adapter-not-powered": "蓝牙没有上电",
    "controller-init-failed": "蓝牙芯片初始化失败",
    "controller-timeout": "蓝牙芯片没有响应",
    "bluez-missing": "安装没有完成，在盒子上运行 python3 /opt/autoplay/board_zte_f50.py --setup",
    "rfkill": "蓝牙被系统关闭，打不开",
    "rfkill-hard": "蓝牙被硬件开关关闭",
    "hci-busy": "蓝牙被另一个程序占用",
    "hci-lost": "蓝牙芯片复位了，正在重新启动",
    "storage-conflict": "蓝牙的数据被另一个程序占用",
    "daemon-exit": "蓝牙程序退出了，正在重启",
}


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def host_allowed(host, allowed_networks, names=()):
    """Whether a request's Host header names this box: one of its names, or an address on a network whose
    clients may use the page (the router's own address there), or the loopback."""
    name = (host or "").rsplit(":", 1)[0].strip("[]").lower().rstrip(".")
    if not name:
        return False
    if name in LOCAL_HOSTS or name in {n.lower() for n in names if n}:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address == state_files.SHARED_LAN.ip or any(address in net for net in allowed_networks)


TITLE = "AutoPlay 盒子"   # what the CarPlay page's row calls it (连接 → AutoPlay 盒子); "AutoPlay 设置" is that page's own panel
# After a pairing, "connecting" is said under the iPhone group this long at most (1.5.4): the pairing's status keeps
# "paired" until the next pairing or a restart, and an iPhone that never joined the Wi-Fi held the page on a screen with
# no categories and no way back.
PAIRED_SHOWN_FOR = 180
# Which category a button's answer is shown on: the redirect after a POST carries it as the address's fragment.
PANE_AFTER = {"/update": "#update"}

# The longest a check started from the page shows as running. "Checking" stays until the check ends: update.latest_manifest gives up as a whole after update.CHECK_LIMIT (60 s,
# 1.5.3); this is only the guard against a check that never comes back. It was 90 s while a check could take two
# minutes and more (30 s per place, file and connection, one after another), so the page went back to the last result
# and stopped refreshing while the check went on.
CHECK_SHOWN_FOR = update.CHECK_LIMIT + 15


def release_summary(notes):
    """What the page shows of a release's notes: the opening paragraph without Markdown marks (1.4.1). The notes are
    the release's whole CHANGELOG section, which since 1.4.0 runs to a page."""
    opening = notes.strip().split("\n\n", 1)[0]
    return "\n".join(line.strip() for line in re.sub(r"\*\*|`", "", opening).splitlines())


def check_failure(error):
    """A failed check for updates in one sentence (1.5.4). The page showed update.check's whole error: the places it
    asked, their errors, and advice about a mirror setting this page does not have. The details went to the
    diagnostics (update.check), where they are read."""
    if "签名" in error:
        return "下载到的更新清单没有通过签名核对，已忽略。"
    if error.startswith("下载失败"):
        return "连不上 GitHub 和下载镜像，稍后再试。"
    if "格式不认识" in error:
        return "这个版本看不懂新的更新清单，请按安装说明手动升级。"
    return "检查没有完成，稍后再试。"


class SettingsPage:
    def __init__(self, state: Path, status, on_change, allowed_networks, admin="/cgi-bin/luci/admin/network/wireless",
                 root=None, thermal=None):
        """status() -> dict for display (a status_model snapshot); on_change(reason) restarts the service;
        allowed_networks() -> the networks whose clients may use the page; admin: LuCI's Wi-Fi page;
        root: the program directory (factory reset); thermal() -> (temps by zone, cooling at work), as
        platform_openwrt.thermal gives them (1.5.0; none: the page says nothing about heat)."""
        self.thermal = thermal or (lambda: ({}, {}))
        self.state = state
        self.root = root or state.parent
        self.admin = admin
        self.pairing = PairingWindow(state.parent)
        self.status, self.on_change, self.allowed = status, on_change, allowed_networks
        self.uci = factory_reset.subprocess.run   # the factory reset's uci runner (tests replace it)
        self.server = None
        self.checks_seen, self.checks_lock = {}, threading.Lock()
        # A check for updates started from this page (1.4.1): shown in place, the page refreshing until it is done.
        self.checking, self.check_started = threading.Event(), 0.0

    def start(self, port=18080):
        page = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 10   # incomplete requests must not keep a worker thread forever

            def log_message(self, *_):   # keep tokens/passwords out of the journal
                pass

            def _allowed(self):
                client = ipaddress.ip_address(self.client_address[0].removeprefix("::ffff:"))
                if not (client.is_loopback or any(client in net for net in page.allowed())):
                    return False
                status = page.status()
                names = (status.get("name"), status.get("own_name"), urllib.parse.urlsplit(status.get("home", "")).hostname)
                return host_allowed(self.headers.get("Host", ""), page.allowed(), names)

            def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                host = self.headers.get("Host", "")
                reply = page.tesla_check(host, self.path)
                page.note_check(host, self.path, reply[0] if reply else "off")
                if reply:
                    return self._send(reply[0], reply[1], "text/html", reply[2])
                if not self._allowed():
                    return self._send(403, page.render_refused())
                if self.path == "/diag.txt":
                    header = {"event": "download", "wall": round(time.time()), "uptime": round(time.monotonic(), 1),
                              "version": update.bundled_version(Path(__file__).resolve().parent)}
                    return self._send(200, diagnostics.DiagLog(page.state / "diag").text(header), "text/plain; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="autoplay-diag.txt"'})
                if self.path == "/status.json":
                    return self._send(200, json.dumps(page.status(), ensure_ascii=False), "application/json")
                if self.path.split("?")[0] == "/reset":
                    return self._send(200, page.render_reset())
                if self.path.split("?")[0] != "/":
                    return self._send(404, page.render_missing())
                self._send(200, page.render(self.path.partition("?")[2], self.headers.get("Host", "")))

            def do_POST(self):
                if not self._allowed():
                    return self._send(403, page.render_refused())
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
                    return self._send(400, "invalid request framing")
                raw_length = lengths[0] if lengths else "0"
                if not raw_length.isascii() or not raw_length.isdecimal():
                    return self._send(400, "invalid content length")
                length = int(raw_length)
                if length > MAX_BODY:
                    return self._send(413, "too large")
                try:
                    body = self.rfile.read(length)
                    if len(body) != length:
                        return self._send(400, "incomplete body")
                    form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode(),
                                                                     keep_blank_values=True).items()}
                except (UnicodeDecodeError, TimeoutError):
                    return self._send(400, "invalid body")
                try:
                    result = page.apply(self.path, form)
                except ValueError as error:
                    result = "错误：" + str(error)
                # A message shows as a banner; a dict asks the page for a confirmation screen (ask=...).
                params = result if isinstance(result, dict) else {"m": result}
                self._send(303, "", extra={"Location": "/?" + urllib.parse.urlencode(params) + PANE_AFTER.get(self.path, "")})

        self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=self.server.serve_forever, name="settings-page", daemon=True).start()

    def stop(self):
        self.pairing.stop()
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def home(self):
        return self.status().get("home", "/")

    # Tesla connectivity checks ------------------------------------------------------------------

    def tesla_check(self, host, path="/"):
        """The reply to a car's connectivity check while OfflineChecks answers them, else None."""
        if not self.status().get("tesla_offline"):
            return None
        return tesla_checks.check_response(host, path)

    def note_check(self, host, path, reply):
        """A car's request for a check name into state/diag/ (host, path, our reply or "off"), so a user's diagnostics
        show which checks the car makes and what it got. Only these names, never the settings page's own requests."""
        name = tesla_checks.check_name(host)
        if not name:
            return
        key, now = (name, path.split("?")[0][:100], reply), time.monotonic()
        with self.checks_lock:
            last, repeats = self.checks_seen.get(key, (None, 0))
            if last is not None and now - last < CHECK_LOG_EVERY:
                self.checks_seen[key] = (last, repeats + 1)
                return
            self.checks_seen[key] = (now, 0)
        record = {"uptime": round(now, 1), "event": "tesla_check", "host": name, "path": key[1], "reply": reply}
        if repeats:
            record["repeats"] = repeats
        try:
            diagnostics.DiagLog(self.state / "diag").append(record)
        except OSError:
            pass

    # Behaviour -------------------------------------------------------------------------------

    def check_nonce(self, form):
        if not secrets.compare_digest(form.get("nonce", ""), self.pairing.nonce):
            raise ValueError("页面已过期，请刷新后重试。")

    def apply(self, path, form):
        if path == "/pair":
            self.check_nonce(form)
            action = form.get("action")
            if action == "start":
                self.pairing.start()
                return ""
            # What an action did shows where it happened (1.4.1): the list says it, or the group's footer does;
            # a banner at the top of the page is for states the owner has to act on, and for errors.
            if action == "cancel":
                self.pairing.stop()
                return ""
            if action == "pick":
                self.pairing.pick(form.get("phone", ""))
                return ""
            if action == "remove":
                # Confirmed on this page, not by the browser's confirm() box: a car browser draws that at the OS size or
                # not at all (1.2.0). The first press returns to a screen with the question; the second press carries confirmed=1.
                if form.get("confirmed") != "1":
                    return {"ask": "remove", "phone": form.get("phone", "")}
                self.pairing.remove(form.get("phone", ""))
                return ""   # the phone leaves the list; the confirmation screen said what that means
            if action == "use":
                self.pairing.use(form.get("phone", ""))
                return {"m": "已邀请，1 分钟内有效。请保持 iPhone 的蓝牙打开。", "at": "phones"}
            if action in ("yes", "no"):
                self.pairing.confirm(form.get("request_id", ""), action == "yes")
                return "" if action == "yes" else {"m": "已拒绝这次配对。", "at": "phones"}
            raise ValueError("未知操作。")
        if path == "/update":
            self.check_nonce(form)
            if form.get("action") == "check":
                self.start_check()
                return ""   # the update group shows "checking" and the page refreshes itself until the result is in
            if form.get("action") == "install":
                if form.get("confirmed") != "1":
                    return {"ask": "install"}
                message = update.launch(self.state.parent)
                # Started: the group shows the upgrade running. Refused (CarPlay in use) or failed: said in the group.
                return "" if message.startswith("已开始升级") else {"m": message, "at": "update"}
            raise ValueError("未知操作。")
        if path == "/reset":
            self.check_nonce(form)
            return self.reset(form)
        raise ValueError("网络在 OpenWrt 后台设置。")

    def reset(self, form):
        """Factory reset (reliability_audit #24): the typed word confirms; the identity needs its own words."""
        if form.get("confirm", "").strip() != factory_reset.RESET_CONFIRMATION:
            raise ValueError(f"请在确认框里输入「{factory_reset.RESET_CONFIRMATION}」。")
        if self.pairing.presence().get("active"):
            raise ValueError("当前有人使用 CarPlay，请先断开再重置。")
        identity = form.get("identity", "").strip() == factory_reset.IDENTITY_CONFIRMATION
        self.pairing.stop()
        try:
            self.pairing.reset_all()   # BlueZ forgets the iPhones too (best effort: BlueZ may be down)
        except Exception:   # noqa: BLE001
            pass
        removed = factory_reset.wipe(self.root, identity=identity, uci=self.uci)
        threading.Timer(1.0, self.on_change, args=("factory reset",)).start()
        return ("已重置" + ("，认证文件也已删除" if identity else "")
                + f"（{len(removed)} 项）。盒子约 1 分钟后重新启动，之后请重新添加 iPhone。")

    # Blocks ----------------------------------------------------------------------------------

    def start_check(self):
        """A check for updates from the button, one at a time, apart from the page's request."""
        if self.check_running():
            return

        def run():
            try:
                update.check(self.state.parent)
            finally:
                self.checking.clear()
        self.checking.set()
        self.check_started = time.monotonic()
        threading.Thread(target=run, name="update-check", daemon=True).start()

    def check_running(self):
        # Never "checking" for ever: update.check gives up as a whole within update.CHECK_LIMIT.
        return self.checking.is_set() and time.monotonic() - self.check_started < CHECK_SHOWN_FOR

    def update_block(self, nonce, note=""):
        """Program update (update.py), as iOS's Software Update: this box's version, what the last check found, the
        buttons. A check from the button runs in place ("checking", the page refreshing) instead of a banner asking
        to reload (1.4.1). The update itself runs apart from this service, which it restarts.
        Returns (cells, footer). The footer speaks only while something is happening or was refused (1.5.0: the
        standing line "每天自动检查一次，不会自动安装。" is gone, as every line of that kind on the CarPlay page's panel)."""
        found = update.read(self.state / "update-check.json")
        progress = update.read(self.state / "update-status.json")
        if update.running(self.state.parent):
            return (f'<div class=cell aria-busy=true><span class=spin></span><span class=main><b>正在升级</b>'
                    f'<span>{escape(progress.get("message", ""))}</span></span></div>',
                    "约 2–5 分钟，期间 CarPlay 断开。")
        version = update.bundled_version(self.state.parent)
        mine = (f'<div class=cell>{ui.tile("gray", "box")}<span class=main><b>本机程序</b></span>'
                f'<span class=value>{escape(version)}</span></div>' if version else "")
        foot = escape(note)
        check = (f'<form method=post action=/update>{ui.hidden(nonce)}<button class="cell action" name=action '
                 'value=check>检查更新</button></form>')
        if self.check_running():
            return mine + ('<div class=cell aria-busy=true><span class=spin></span><span class=main><b>正在检查更新…</b>'
                           '</span></div>'), foot
        cells = ""
        # A failure no longer matters once a later check finds the box up to date (updated by hand, say).
        settled = progress.get("phase") == "failed" and found.get("latest") and not found.get("available") \
            and not found.get("error") and found.get("checked_at", 0) > progress.get("at", 0)
        if progress.get("phase") in ("done", "failed") and time.time() - progress.get("at", 0) < 86400 and not settled:
            done = progress["phase"] == "done"
            cells += (f'<div class=cell>{ui.tile("green" if done else "orange", "check" if done else "alert")}'
                      f'<span class=main><b>{"上次升级" if done else "上次升级没有完成"}</b>'
                      f'<span>{escape(progress.get("message", ""))}</span></span></div>')
        if found.get("error"):
            cells = mine + cells + (f'<div class=cell>{ui.tile("orange", "alert")}<span class=main><b>检查更新没有成功</b>'
                                    f'<span>{check_failure(found["error"])}</span></span></div>')
        elif found.get("available"):
            notes = escape(release_summary(found.get("notes", ""))).replace("\n", "<br>")
            more = f"https://github.com/{update.OWNER}/{update.REPO}/releases/tag/v{found['latest']}"
            # This box's version is the row above; of a page-long CHANGELOG section only the opening paragraph, four
            # lines at most, the rest a tap away (1.4.1).
            current = mine or (f'<div class=cell>{ui.tile("gray", "box")}<span class=main><b>本机程序</b></span>'
                               f'<span class=value>{escape(found["current"])}</span></div>' if found.get("current") else "")
            cells = current + cells + (
                f'<div class="cell tall">{ui.tile("red", "download")}<span class=main><b>有新版本 {escape(found["latest"])}</b>'
                f'{f"<span class=clamp>{notes}</span>" if notes else ""}'
                f'<span><a class=more href="{escape(more)}">完整更新说明</a></span></span></div>')
            if found.get("online"):
                cells += (f'<form method=post action=/update>{ui.hidden(nonce)}<button class="cell action" name=action '
                          'value=install>立即升级</button></form>')
            else:
                foot = foot or f'{escape(found.get("reason") or "这一版改了系统")}，需要按发布说明手动升级。'
        elif found.get("latest"):
            # One row says both: this box's version and that there is none newer.
            cells += (f'<div class=cell>{ui.tile("green", "check")}<span class=main><b>已是最新</b></span>'
                      f'<span class=value>{escape(version or found["latest"])}</span></div>')
        else:
            cells = mine + cells
        return cells + check, foot

    def ddns_block(self):
        """The own DuckDNS name: LuCI sets it; this page only tells how it is going. Two rows: the name, and its
        certificate - a date when there is one, otherwise what is happening, in the row's second line."""
        name = self.status().get("own_name")
        if not name:
            return ""
        line = own_domain.message(self.state, name)
        valid = re.fullmatch(r"证书有效期至 (\d{4}-\d\d-\d\d)", line)
        if valid:
            certificate = (f'<div class=cell>{ui.tile("green", "lock")}<span class=main><b>证书</b></span>'
                           f'<span class=value>至 {valid.group(1)}</span></div>')
        else:
            certificate = (f'<div class=cell>{ui.tile("orange", "lock")}<span class=main><b>证书</b>'
                           f'<span>{escape(line)}</span></span></div>')
        return (f'<div class=cell>{ui.tile("blue", "globe")}<span class=main><b>{escape(name)}</b></span></div>'
                + certificate)

    def phone_node(self, devices, active, phase):
        if active and active in devices:
            return ("on", devices[active], "正在使用")
        if phase != "closed":
            return ("wait", "iPhone", "正在添加")
        return ("off", "iPhone", f"已添加 {len(devices)} 部" if devices else "未添加")

    def hotspot_node(self):
        status = self.status()
        return ("on", status.get("ssid", ""), "AutoPlay 热点") if status.get("ssid") else ("wait", "AutoPlay 热点", "正在开启")

    def box_node(self):
        """The box in the chain: red when Bluetooth or the receiver is down, orange while they start."""
        status = self.status()
        bluetooth = (status.get("bluetooth") or {}).get("state")
        system = (status.get("system") or {}).get("state")
        if bluetooth == "failed" or system == "degraded":
            return ("bad", "盒子", "蓝牙没有启动" if bluetooth == "failed" else "程序反复重启")
        if bluetooth == "starting" or system in ("starting", "restarting"):
            return ("wait", "盒子", "正在启动")
        return ("on", "盒子", "运行中")

    def chain(self, devices, presence, phase):
        return ui.chain(self.hotspot_node(), self.phone_node(devices, presence.get("active"), phase), self.box_node())

    def phones_block(self, nonce, note=""):
        """The pairing flow while it runs (its own screen); otherwise the iPhone group: the phones, then "添加 iPhone" as
        the group's last row, and a footer line only while something is going on. Returns (html, refresh, devices,
        screen): screen when the html is the pairing's own screen, refresh while it or a new iPhone's connecting runs."""
        pair = self.pairing.status()
        presence = self.pairing.presence()
        devices = self.pairing.devices()
        # Before the first iPhone the pairing screen says where to do it (the iPhone stays on its Bluetooth page).
        panel, refresh = ui.pairing_panel(pair, nonce, "" if devices else self.home())
        if panel:
            return panel, refresh, devices, True
        # "paired" stays in the status file after the window closes; it matters until someone connects, and for a few
        # minutes at most (1.5.4): until then this line was a screen of its own, without the categories or 返回, for as
        # long as the iPhone did not come.
        connecting = pair.get("phase") == "paired" and not presence.get("active") \
            and time.time() - pair.get("at", 0) < PAIRED_SHOWN_FOR
        rows = ui.phone_rows(devices, presence.get("active"), presence.get("last_phone"), nonce, not presence.get("active"))
        add = (f'<form method=post action=/pair>{ui.hidden(nonce)}'
               '<button class="cell action" name=action value=start>添加 iPhone</button></form>')
        bluetooth = self.status().get("bluetooth") or {}
        # One line under the list, the most pressing first. These were banners inside the group (1.4.1).
        if bluetooth.get("state") not in (None, "on", "unknown"):
            # Bluetooth is not up: say so instead of inventing a cable (the alert at the top says why).
            foot = "蓝牙就绪后才能添加或接入 iPhone。"
        elif connecting:
            foot = "配对完成，iPhone 正在连上 AutoPlay 热点并打开 CarPlay。"
        else:
            # Nothing going on: no line (1.5.0). The steps of adding an iPhone are on the screen that adds it.
            foot = note
        # No title: the category is 「iPhone」 already (1.5.4).
        return ui.group("", rows + add, escape(foot)), connecting, devices, False

    def entries(self, status, host=""):
        """The CarPlay page's addresses, the one on the name this browser used for this page first: it is where the
        title bar's button leads, and the page its settings are kept under."""
        found = [u for u in status.get("entries", []) if u.startswith("https")]
        name = (host or "").rsplit(":", 1)[0].strip("[]").lower()
        return sorted(found, key=lambda u: (urllib.parse.urlsplit(u).hostname or "").lower() != name)

    def entries_block(self, entries):
        if not entries:
            return ""
        return ui.group("在车机浏览器打开", "".join(
            f'<div class=cell>{ui.tile("green", "screen")}<span class=main><b>{ui.url(u)}</b></span></div>' for u in entries))

    def network_block(self):
        status = self.status()
        admin = self.admin
        if admin.startswith("/"):
            # On the router's own web server (port 80), not on this page's port (a 404 there).
            host = urllib.parse.urlsplit(status.get("home", "")).hostname
            admin = f"http://{host}{admin}" if host else admin
        # No line under the link (1.4.1): AutoPlay follows whatever is changed there by itself.
        return (f'<div class=cell>{ui.tile("blue", "wifi")}<span class=main><b>名称</b></span>'
                f'<span class=value>{escape(status.get("ssid", "") or "正在开启")}</span></div>'
                f'<a class=cell href="{escape(admin)}">{ui.tile("gray", "settings")}<span class=main><b>在 OpenWrt 后台设置</b>'
                '</span><span class=chev></span></a>')

    def notices(self):
        status = self.status()
        html = ""
        bluetooth = status.get("bluetooth") or {}
        if bluetooth.get("state") in ("failed", "starting") and bluetooth.get("reason") not in (None, "helper-starting", "powering"):
            # S2: the real reason at the top of the chain, never a cable story.
            reason = BLUETOOTH_TEXT.get(bluetooth["reason"], bluetooth["reason"])
            html += ui.banner(f"蓝牙没有启动：{reason}。可以重启盒子；仍不行请下载诊断记录。", "bad")
        elif bluetooth.get("state") == "failed":
            html += ui.banner("蓝牙没有启动，盒子在不断重试。可以重启盒子；仍不行请下载诊断记录。", "bad")
        phone = status.get("phone") or {}
        if phone.get("state") == "pairing-lost":
            html += ui.banner("有一部 iPhone 忘记了这台盒子（连续两次拒绝连接），请删除此 iPhone 后重新添加。", "bad")
        certificate = status.get("certificate") or {}
        if certificate.get("state") in ("expiring_soon", "expired", "failed"):
            until = certificate.get("not_after")
            text = {"expiring_soon": f"证书 {until} 到期",
                    "expired": f"证书已于 {until} 过期，车机浏览器会提示不安全",
                    "failed": "证书还没申请到"}[certificate["state"]]
            uplink = (status.get("uplink") or {}).get("state")
            advice = "盒子没网，无法续签：插上能上网的 SIM 卡开机一次。" if uplink == "offline" else "盒子联网后会自动续签。"
            html += ui.banner(text + "。" + advice, "wait")
        identity = status.get("identity")
        if identity is False or (isinstance(identity, dict) and identity.get("state") == "missing"):
            host = urllib.parse.urlsplit(self.home()).hostname or ""
            # No credentials here: the F50's root password is the installer's, never 1234 (S3).
            html += ui.banner(f"还缺 CarPlay 认证文件：把「AI 安装说明」、盒子地址 {host} 和安装时记下的登录方式交给你的"
                              " AI 助手。放好后自动开始工作；添加 iPhone 可以先做。", "wait")
        if status.get("warning"):
            html += ui.banner(status["warning"], "bad")
        # Only an upstream that is down is news (1.3.0): "online" said nothing a driver could act on, and the
        # first seconds of probing are no problem either.
        # The page's own words since 1.4.1 ("上游" was ours, not the owner's); tesla_internet stays in the diagnostics.
        if status.get("tesla_upstream") == "offline":
            html += ui.banner("盒子没有网络（没有 4G 信号）：CarPlay 照常，车机自带的音乐、地图不能上网。", "wait")
        error = status.get("tesla_error", "")
        if error:
            html += ui.banner("车机网络设置失败：" + error + "。CarPlay 不受影响。", "bad")
        hottest, slowed = self.heat()
        if slowed:
            # 1.5.0: said only while the system is really holding the processor back for heat, which the owner can
            # do something about. The drive of 2026-11-10 reached 72 C parked in the sun with nobody told.
            html += ui.banner(f"盒子过热（{hottest} °C），系统正在降低它的速度，CarPlay 可能卡顿。"
                              "请把它移到晒不到的地方或靠近出风口。", "wait")
        return html

    def heat(self):
        """(the hottest zone in whole degrees or None, whether the kernel holds the processor back for heat): only
        the processor's own cooling devices count (thermal-cpufreq-N, thermal-cpu-N), not a charger's."""
        try:
            temps, cooling = self.thermal()
        except Exception:   # a page must not fail over a sensor
            return None, False
        return (max(temps.values()) if temps else None), any(name.startswith("cpu") for name in cooling)

    # Page ------------------------------------------------------------------------------------

    def confirm_screen(self, kind, params, nonce):
        """The question a destructive button used to put in the browser's confirm() box, as a screen of this page: a car
        browser draws confirm() at the OS size, outside this page's scale, or suppresses it (1.2.0). Since 1.5.4 every
        one-task screen has one shape: the task is the title, 取消 is the bar's button, the body holds what it is about
        and the one button that does it (the question used to be the smallest text on the screen, a group's title).
        Returns (title, where 取消 goes, body), or None when there is nothing to ask (the phone is gone, an unknown
        kind): the normal page follows.

        The button is a row of the list in the destructive style (red text) or the action style, as on the rest of this
        page and as Apple's guidelines give it: a destructive action is never the prominent (filled) button, and an
        action sheet's message is left out when the title and the context say enough (1.5.4: until then a full-width
        red button, and a line under the phone)."""
        if kind == "remove":
            phone = params.get("phone", [""])[0]
            name = self.pairing.devices().get(phone)
            if not name:
                return None
            twins = ui.same_names(self.pairing.devices().values())   # the address only tells two of one name apart
            return ("删除 iPhone", "/", ui.group("", f'<div class=cell>{ui.tile("gray", "phone")}{ui.device_name(name, phone, twins)}</div>')
                    + f'<form method=post action=/pair>{ui.hidden(nonce, phone=phone, confirmed="1")}'
                    + ui.group("", '<button class="cell destructive" name=action value=remove>删除此 iPhone</button>') + '</form>')
        if kind == "install":
            found = update.read(self.state / "update-check.json")
            if not found.get("available") or not found.get("online"):
                return None
            return (f'升级到 {found.get("latest", "")}', "/#update",
                    f'<form method=post action=/update>{ui.hidden(nonce, confirmed="1")}'
                    + ui.group("", '<button class="cell action" name=action value=install>立即升级</button>', "约 2–5 分钟，期间 CarPlay 断开。")
                    + '</form>')
        return None

    def render(self, query, host=""):
        """host: the request's Host header, which says under which of its names this browser knows the box."""
        params = urllib.parse.parse_qs(query)
        message, at = params.get("m", [""])[0], params.get("at", [""])[0]
        # An action's result is said in its own group (at=phones / at=update); only an error, or a result with no
        # place of its own (the factory reset), is an alert at the top.
        placed = at in ("phones", "update") and not message.startswith("错误：")
        notice = ("" if placed else ui.flash(message)) + self.notices()
        nonce = self.pairing.nonce
        ask = params.get("ask", [""])[0]
        if ask:
            screen = self.confirm_screen(ask, params, nonce)
            if screen:
                title, back, body = screen
                return ui.page(title, ui.flow(notice + body), done=("取消", back))
        status = self.status()
        block, connecting, devices, pairing = self.phones_block(nonce, message if placed and at == "phones" else "")
        if pairing:
            # Pairing in progress (1.2.0): the passkey and its buttons are the whole page. In the Tesla's windowed
            # browser (773x601 CSS px) they sat below the Wi-Fi group, off the screen. No categories and no chain
            # here: the panel says itself what is happening. Its title is the task, 取消 in the bar (1.5.4).
            return ui.page("添加 iPhone", ui.flow(notice + block), True, done=ui.pair_cancel(nonce))
        presence = self.pairing.presence()
        phase = self.pairing.status().get("phase", "closed")
        entries = self.entries(status, host)
        reach = self.ddns_block()
        hottest, slowed = self.heat()
        heat = "" if hottest is None else (
            f'<div class=cell>{ui.tile("orange" if slowed else "gray", "heat")}<span class=main><b>盒子温度</b>'
            + ("<span>过热，正在降速</span>" if slowed else "") + f'</span><span class=value>{hottest} °C</span></div>')
        advanced = (heat + f'<a class=cell href="/diag.txt">{ui.tile("gray", "doc")}<span class=main><b>下载诊断记录</b></span>'
                    f'<span class=chev></span></a><a class=cell href="/reset">{ui.tile("red", "reset")}<span class=main>'
                    '<b>恢复出厂设置</b></span><span class=chev></span></a>')
        updates, update_foot = self.update_block(nonce, message if placed and at == "update" else "")
        # The categories of the CarPlay page's panel, for the box (1.5.0): what is used every day first (the chain and
        # the iPhones), then the network, the program's update, and what is rarely needed. One column in every window,
        # so no group stands beside an empty half (until 1.4.3 two columns, the right one twice the left's height).
        panes = {
            "iphone": self.chain(devices, presence, phase) + block,
            "net": (ui.group("AutoPlay 热点", self.network_block()) + self.entries_block(entries)
                    + (ui.group("自己的网址", reach) if reach else "")),
            "update": ui.group("程序更新", updates, update_foot),
            "more": ui.group("", advanced),   # no title: the category is 「高级」 already (1.5.4)
        }
        found = update.read(self.state / "update-check.json")
        marked = ("update",) if found.get("available") and not found.get("error") else ()
        # An upgrade reloads every 3 s; a check from the button every 2 s until its result is in; a new iPhone's
        # connecting every 3 s until it is there (PAIRED_SHOWN_FOR at most).
        refresh = True if update.running(self.state.parent) else 2 if self.check_running() else connecting
        # The bar's button is this page's way out, as 完成 is the panel's: back to where the visit began on the
        # CarPlay page (settings_ui.page), at the address this browser knows it by.
        return ui.page(TITLE, ui.alerts(notice) + ui.layout(panes, marked), refresh, out=entries[0] if entries else None)

    def render_reset(self):
        """The factory-reset page: what goes, two typed confirmations (no JS confirm() to bypass). 1.5.4: names only,
        no lines under them or under the groups; what to type for the identity files is the field's placeholder; the
        button is a red row, as Apple's guidelines give a destructive action (it was a full-width red button)."""
        nonce = self.pairing.nonce
        body = (ui.group("会被删除", f'<div class=cell>{ui.tile("gray", "phone")}<span class=main><b>已添加的 iPhone</b></span></div>'
                           f'<div class=cell>{ui.tile("orange", "lock")}<span class=main><b>证书与密钥</b></span></div>'
                           f'<div class=cell>{ui.tile("gray", "doc")}<span class=main><b>设置与记录</b></span></div>')
                + f'<form method=post action=/reset>{ui.hidden(nonce)}'
                + ui.group("", f'<label class=cell><span class=main><b>输入「{factory_reset.RESET_CONFIRMATION}」</b></span>'
                           '<input type=text name=confirm autocomplete=off autocapitalize=off placeholder="在此输入" required></label>'
                           '<label class=cell><span class=main><b>同时删除认证文件</b></span>'
                           f'<input type=text name=identity autocomplete=off autocapitalize=off placeholder="输入「{factory_reset.IDENTITY_CONFIRMATION}」"></label>')
                + ui.group("", '<button class="cell destructive">恢复出厂设置</button>')
                + '</form>')
        return ui.page("恢复出厂设置", ui.flow(body), done=("取消", "/#more"))

    @staticmethod
    def render_refused():
        """403 (1.5.4: was the bare word "forbidden"): a browser that is not on the box's Wi-Fi, or came by a name the
        page does not answer to. Nothing of the box on it, and no button: there is nowhere here to go back to."""
        return ui.page(TITLE, ui.flow(ui.banner("从这个地址打不开 AutoPlay 盒子。连上 AutoPlay 热点后，从「AutoPlay 设置 → 连接 → "
                                                "AutoPlay 盒子」打开。", "wait")))

    @staticmethod
    def render_missing():
        """404 (1.5.4: was the bare words "not found"), with the bar's way back to the page."""
        return ui.page(TITLE, ui.flow(ui.banner("没有这一页。", "wait")), done=("返回", "/"))
