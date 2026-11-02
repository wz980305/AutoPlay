"""Plain-HTTP settings page on the settings port (18080): iPhones, status, program update, diagnostics.

The router (OpenWrt, LuCI) owns the network and the uci settings; this page adds and removes iPhones, shows
what the box is doing and starts an update. It is also the always-up page while the receiver is not (identity
missing, Wi-Fi waiting, Bluetooth down), and in Tesla mode the responder for the car's connectivity checks
(tesla_checks.py, behind tesla_openwrt's port-80 redirect). Only clients on the Wi-Fi handed to the iPhone may
use it. Markup lives in settings_ui.py; this module holds the behaviour.

The Debian first-run wizard, hotspot/car/internet forms, remote debugging and DuckDNS form of DashPlay are gone
(code_inventory_trimming.md 2.2): the F50 is the only target.
"""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
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
    "helper-starting": "蓝牙正在启动",
    "powering": "蓝牙适配器正在上电",
    "adapter-not-powered": "蓝牙适配器没有上电，盒子会一直重试",
    "controller-init-failed": "蓝牙芯片初始化失败（Marlin3 固件没有接受配置）",
    "controller-timeout": "蓝牙芯片没有响应",
    "bluez-missing": "盒子上缺少蓝牙程序（安装没有完成：重新运行装机的 autoplay 步骤）",
    "rfkill": "找不到唯一的蓝牙开关（rfkill）",
    "hci-busy": "另一个程序占着蓝牙控制器",
    "hci-lost": "蓝牙控制器消失了（Wi-Fi 芯片复位），正在重新启动",
    "storage-conflict": "/var/lib/bluetooth 被别的程序占用",
    "daemon-exit": "蓝牙后台程序退出了，正在重启",
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


class SettingsPage:
    def __init__(self, state: Path, status, on_change, allowed_networks, admin="/cgi-bin/luci/admin/network/wireless",
                 root=None):
        """status() -> dict for display (a status_model snapshot); on_change(reason) restarts the service;
        allowed_networks() -> the networks whose clients may use the page; admin: LuCI's Wi-Fi page;
        root: the program directory (factory reset)."""
        self.state = state
        self.root = root or state.parent
        self.admin = admin
        self.pairing = PairingWindow(state.parent)
        self.status, self.on_change, self.allowed = status, on_change, allowed_networks
        self.uci = factory_reset.subprocess.run   # the factory reset's uci runner (tests replace it)
        self.server = None
        self.checks_seen, self.checks_lock = {}, threading.Lock()

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
                    return self._send(403, "forbidden")
                if self.path == "/diag.txt":
                    return self._send(200, diagnostics.DiagLog(page.state / "diag").text(), "text/plain; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="autoplay-diag.txt"'})
                if self.path == "/status.json":
                    return self._send(200, json.dumps(page.status(), ensure_ascii=False), "application/json")
                if self.path.split("?")[0] == "/reset":
                    return self._send(200, page.render_reset())
                if self.path.split("?")[0] != "/":
                    return self._send(404, "not found")
                self._send(200, page.render(self.path.partition("?")[2]))

            def do_POST(self):
                if not self._allowed():
                    return self._send(403, "forbidden")
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
                self._send(303, "", extra={"Location": "/?" + urllib.parse.urlencode({"m": result})})

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
            if action == "cancel":
                self.pairing.stop()
                return "已取消添加。"
            if action == "pick":
                self.pairing.pick(form.get("phone", ""))
                return ""
            if action == "remove":
                self.pairing.remove(form.get("phone", ""))
                return "已从盒子上删除。这部 iPhone 以后要用，需要重新添加；也可以在它的「设置 → 通用 → CarPlay」里忘记此车辆。"
            if action == "use":
                self.pairing.use(form.get("phone", ""))
                return "已邀请这部 iPhone 接入，约 1 分钟内有效。请保持它的蓝牙打开。"
            if action in ("yes", "no"):
                self.pairing.confirm(form.get("request_id", ""), action == "yes")
                return "" if action == "yes" else "已拒绝这次配对。"
            raise ValueError("未知操作。")
        if path == "/update":
            self.check_nonce(form)
            if form.get("action") == "check":
                threading.Thread(target=update.check, args=(self.state.parent,), name="update-check", daemon=True).start()
                return "正在检查更新，几秒后刷新页面就能看到结果。"
            if form.get("action") == "install":
                return update.launch(self.state.parent)
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
        return ("已重置：删除了配对、证书和设置" + ("，以及认证文件" if identity else "")
                + f"（{len(removed)} 项）。盒子约 1 分钟后以出厂状态重新启动，请重新添加 iPhone。")

    # Blocks ----------------------------------------------------------------------------------

    def update_block(self, nonce):
        """Program update (update.py): what the daily check found, the last outcome and the button. The update itself
        runs apart from this service, which it restarts."""
        found = update.read(self.state / "update-check.json")
        progress = update.read(self.state / "update-status.json")
        if update.running(self.state.parent):
            return (f'<div class=cell><span class=main><b>正在升级</b><span>{escape(progress.get("message", ""))}</span>'
                    '</span></div><p class=note>约 2–5 分钟，期间 CarPlay 会断开，页面会自己刷新。</p>')
        version = update.bundled_version(self.state.parent)
        cells = (f'<div class=cell><span class=main><b>本机程序</b></span><span class=value>{escape(version)}</span></div>'
                 if version else "")
        # A failure no longer matters once a later check finds the box up to date (updated by hand, say).
        settled = progress.get("phase") == "failed" and found.get("latest") and not found.get("available") \
            and not found.get("error") and found.get("checked_at", 0) > progress.get("at", 0)
        if progress.get("phase") in ("done", "failed") and time.time() - progress.get("at", 0) < 86400 and not settled:
            cells += (f'<div class=cell><span class=main><b>{"上次升级" if progress["phase"] == "done" else "上次升级没有完成"}</b>'
                      f'<span>{escape(progress.get("message", ""))}</span></span></div>')
        if found.get("error"):
            cells += f'<div class=cell><span class=main><b>检查更新没有成功</b><span>{escape(found["error"])}</span></span></div>'
        elif found.get("available"):
            notes = escape(found.get("notes", "")).replace("\n", "<br>")
            cells += (f'<div class=cell><span class=main><b>有新版本 {escape(found["latest"])}</b><span>{notes}</span></span>'
                      f'<span class=value>当前 {escape(found.get("current") or "较旧版本")}</span></div>')
            cells += (f'<form method=post action=/update>{ui.hidden(nonce)}<button class="cell action" name=action '
                      'value=install onclick="return confirm(\'升级约 2–5 分钟，期间 CarPlay 会断开。现在升级？\')">'
                      '立即升级（约 2–5 分钟，期间 CarPlay 会断开）</button></form>' if found.get("online") else
                      f'<p class=note>{escape(found.get("reason") or "这一版改了系统")}，不能在线升级：请按装机说明用刷机包升级。</p>')
        elif found.get("latest"):
            cells += (f'<div class=cell><span class=main><b>已是最新</b></span>'
                      f'<span class=value>{escape(found["latest"])}</span></div>')
        checked = (time.strftime("上次检查 %m-%d %H:%M", time.localtime(found["checked_at"]))
                   if found.get("checked_at") else "还没有检查过")
        return cells + (f'<form method=post action=/update>{ui.hidden(nonce)}<button class="cell action" name=action '
                        f'value=check>检查更新</button></form><p class=note>{checked}</p>')

    def audio_block(self):
        """Where navigation prompts play (uci audio_route_navigation, LuCI sets it; docs/AUDIO.md). Music, Siri and
        calls are on the Tesla's Bluetooth either way; this cell says what the page does with navigation."""
        route = self.status().get("audio_route")
        if not route:
            return ""
        if route == "carplay":
            title, text = "在 CarPlay 页面", "上车后轻点页面一次开启声音；音乐、Siri、通话走特斯拉蓝牙。"
        else:
            title, text = "走特斯拉蓝牙", "盒子不向 iPhone 提供音频，所有声音从特斯拉蓝牙播出，CarPlay 页面无声。"
        return (f'<div class=cell><span class=main><b>导航播报</b><span>{text} 在 LuCI「服务 → AutoPlay → iPhone」里更改。'
                f'</span></span><span class=value>{title}</span></div>')

    def ddns_block(self):
        """The own DuckDNS name: LuCI sets it; this page only tells how it is going."""
        name = self.status().get("own_name")
        if not name:
            return ""
        return (f'<div class=cell><span class=main><b>自己的域名</b><span>{escape(own_domain.message(self.state, name))}'
                f'</span></span><span class=value>{escape(name)}</span></div>')

    def phone_node(self, devices, active, phase):
        if active and active in devices:
            return ("on", devices[active], "正在使用")
        if phase != "closed":
            return ("wait", "iPhone", "正在添加")
        return ("off", "iPhone", f"已添加 {len(devices)} 部" if devices else "未添加")

    def hotspot_node(self):
        status = self.status()
        return ("on", status.get("ssid", ""), "路由器 Wi-Fi") if status.get("ssid") else ("wait", "Wi-Fi", "等待 Wi-Fi")

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

    def phones_block(self, nonce):
        """Pairing flow while it runs; otherwise the device list and the add button. Returns (html, refresh, devices)."""
        pair = self.pairing.status()
        panel, refresh = ui.pairing_panel(pair, nonce)
        presence = self.pairing.presence()
        devices = self.pairing.devices()
        if panel:
            return panel, refresh, devices
        # "paired" stays in the status file after the window closes; it only matters until someone connects.
        connecting = pair.get("phase") == "paired" and not presence.get("active")
        notice = ui.banner("配对完成，正在引导 iPhone 连接 Wi-Fi 并打开 CarPlay。") if connecting else ""
        rows = ui.phone_rows(devices, presence.get("active"), presence.get("last_phone"), nonce, not presence.get("active"))
        add = (f'<form method=post action=/pair>{ui.hidden(nonce)}'
               f'<button class="{"btn plain" if devices else "btn"}" name=action value=start>添加 iPhone</button></form>')
        # Pairing is done on another screen (the head unit): the iPhone stays on its Bluetooth page (S5).
        foot = ("配对一次后，iPhone 连上这个 Wi-Fi 就能接入；有人正在使用时，其他 iPhone 不会把它挤掉。"
                "添加新的 iPhone 时，请在车机或另一台设备上打开本页操作。"
                if devices else "第一次使用需要用蓝牙配对一次，之后 iPhone 连上这个 Wi-Fi 就能接入。")
        return notice + ui.group("我的 iPhone", rows, foot) + add, connecting, devices

    def iphone_blocks(self, nonce):
        """Bluetooth pairing: the only way an iPhone reaches this box (no USB host on the F50, S1).
        Returns (html, refresh, devices)."""
        block, refresh, devices = self.phones_block(nonce)
        bluetooth = self.status().get("bluetooth") or {}
        if bluetooth.get("state") not in (None, "on", "unknown"):
            # Bluetooth is not up: say so instead of inventing a cable (the banner at the top says why).
            block = ui.banner("蓝牙还没就绪，暂时不能添加或邀请 iPhone；就绪后会自动继续。", "wait") + block
        return block, refresh, devices

    def entries_block(self, status, refresh):
        entries = "".join(f'<div class=cell><span class=main><b>{escape(u)}</b></span></div>'
                          for u in status.get("entries", []) if u.startswith("https"))
        if not entries or refresh:
            return ""
        foot = f"车机连接 Wi-Fi「{escape(status.get('ssid', ''))}」后，在车机浏览器输入上面的地址；画面端口在 OpenWrt 后台的 AutoPlay 页设置。"
        return ui.group("CarPlay 画面", entries, foot)

    def network_block(self):
        status = self.status()
        admin = self.admin
        if admin.startswith("/"):
            # On the router's own web server (port 80), not on this page's port (a 404 there).
            host = urllib.parse.urlsplit(status.get("home", "")).hostname
            admin = f"http://{host}{admin}" if host else admin
        return (f'<div class=cell><span class=main><b>交给 iPhone 的 Wi-Fi</b></span>'
                f'<span class=value>{escape(status.get("ssid", "") or "等待 Wi-Fi")}</span></div>'
                f'<a class=cell href="{escape(admin)}"><span class=main><b>在 OpenWrt 后台设置 Wi-Fi</b>'
                '<span>Wi-Fi 名称、密码或信道改了以后，AutoPlay 会自动跟着改</span></span><span class=chev></span></a>')

    def notices(self):
        status = self.status()
        html = ""
        bluetooth = status.get("bluetooth") or {}
        if bluetooth.get("state") in ("failed", "starting") and bluetooth.get("reason") not in (None, "helper-starting", "powering"):
            # S2: the real reason at the top of the chain, never a cable story.
            reason = BLUETOOTH_TEXT.get(bluetooth["reason"], bluetooth["reason"])
            html += ui.banner(f"蓝牙没有启动：{reason}（重启盒子 / 查看诊断）", "bad")
        elif bluetooth.get("state") == "failed":
            html += ui.banner("蓝牙没有启动，盒子会一直重试（重启盒子 / 查看诊断）", "bad")
        phone = status.get("phone") or {}
        if phone.get("state") == "pairing-lost":
            html += ui.banner("iPhone 连续两次拒绝了蓝牙连接：它忘记了这台盒子。请删除此 iPhone 后重新添加。", "bad")
        certificate = status.get("certificate") or {}
        if certificate.get("state") in ("expiring_soon", "expired", "failed"):
            until = certificate.get("not_after")
            text = {"expiring_soon": f"正式证书将于 {until} 到期",
                    "expired": f"正式证书已于 {until} 过期，特斯拉会看到证书警告",
                    "failed": "正式证书还没申请到"}[certificate["state"]]
            uplink = (status.get("uplink") or {}).get("state")
            advice = "盒子现在没网无法续签：插上能上网的 SIM 卡开机一次。" if uplink == "offline" else "盒子联网后会自动续签。"
            html += ui.banner(text + "。" + advice, "wait")
        identity = status.get("identity")
        if identity is False or (isinstance(identity, dict) and identity.get("state") == "missing"):
            host = urllib.parse.urlsplit(self.home()).hostname or ""
            # No credentials here: the F50's root password is the installer's, never 1234 (S3).
            html += ui.banner(f"还缺 CarPlay 认证文件。把「AI 安装说明」交给你的 AI 助手，并告诉它盒子地址 {host}"
                              "（按安装时记录的登录方式）。文件放好后盒子会自动开始工作，添加 iPhone 可以先做。", "wait")
        if status.get("warning"):
            html += ui.banner(status["warning"], "bad")
        internet = status.get("tesla_internet", "")
        if internet:
            html += ui.banner(internet, "wait" if ("不可用" in internet or "检测" in internet) else "ok")
        error = status.get("tesla_error", "")
        if error:
            html += ui.banner("特斯拉模式局域网设置失败：" + error + "；CarPlay 不受影响。", "bad")
        return html

    # Page ------------------------------------------------------------------------------------

    def render(self, query):
        params = urllib.parse.parse_qs(query)
        notice = ui.flash(params.get("m", [""])[0]) + self.notices()
        nonce = self.pairing.nonce
        status = self.status()
        block, refresh, devices = self.iphone_blocks(nonce)
        presence = self.pairing.presence()
        phase = self.pairing.status().get("phase", "closed")
        reach = self.ddns_block()
        audio = self.audio_block()
        advanced = ('<a class=cell href="/diag.txt"><span class=main><b>下载诊断记录</b>'
                    '<span>画面卡顿、断线时，把它交给 AI 助手或开发者分析</span></span><span class=chev></span></a>'
                    '<a class="cell destructive" href="/reset">恢复出厂设置…</a>')
        intro = ui.other_screen(self.home()) if not devices and not refresh else ""
        body = (f'<h1 class=span>AutoPlay 设置</h1>{notice}{self.chain(devices, presence, phase)}<div>'
                + self.entries_block(status, refresh)
                + ui.group("网络", self.network_block())
                + intro + ui.group("iPhone", block)
                + (ui.group("声音", audio) if audio else "") + '</div><div>'
                + (ui.group("自己的网址", reach) if reach else "")
                + ui.group("程序更新", self.update_block(nonce),
                           "每天自动检查一次，只提示不自动安装。升级前会备份配对、证书和设置，新版本起不来会自动退回。")
                + ui.group("高级", advanced)
                + '</div>')
        return ui.page("AutoPlay 设置", body, refresh or update.running(self.state.parent), wide=True)

    def render_reset(self):
        """The factory-reset page: what goes, two typed confirmations (no JS confirm() to bypass)."""
        nonce = self.pairing.nonce
        body = (f'<a class=back href="/">‹ AutoPlay 设置</a><h1>恢复出厂设置</h1>'
                '<p class=sub>删除这台盒子上所有属于你的数据，然后以出厂状态重新启动。</p>'
                + ui.group("会被删除", '<div class=cell><span class=main><b>已添加的 iPhone</b><span>蓝牙配对、CarPlay 配对记录、上次使用的记录</span></span></div>'
                           '<div class=cell><span class=main><b>证书与密钥</b><span>正式证书、DuckDNS 申请账户、网页访问令牌</span></span></div>'
                           '<div class=cell><span class=main><b>设置与记录</b><span>自己的网址、画面端口、诊断记录和日志；OpenWrt 的 Wi-Fi 不变</span></span></div>')
                + f'<form method=post action=/reset>{ui.hidden(nonce)}'
                + ui.group("确认", f'<label class=cell><span class=main><b>输入「{factory_reset.RESET_CONFIRMATION}」</b></span>'
                           '<input type=text name=confirm autocomplete=off autocapitalize=off style="text-align:right" required></label>'
                           f'<label class=cell><span class=main><b>同时删除 CarPlay 认证文件</b><span>只有在转让或出售盒子时才需要；输入「{factory_reset.IDENTITY_CONFIRMATION}」</span></span>'
                           '<input type=text name=identity autocomplete=off autocapitalize=off style="text-align:right"></label>',
                           "认证文件删除后，重装时要重新提供；不删的话，重置后盒子仍能工作，只需重新添加 iPhone。")
                + '<button class="btn destructive">恢复出厂设置</button></form>')
        return ui.page("恢复出厂设置", body)
