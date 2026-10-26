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

import own_domain
from pairing_window import PairingWindow
import settings_ui as ui
import tesla_checks
import diagnostics
import update

MAX_BODY = 4096
CHECK_LOG_EVERY = 60   # s: one diag line per car connectivity check and reply, repeats counted into the next


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class SettingsPage:
    def __init__(self, state: Path, status, on_change, allowed_networks, admin="/cgi-bin/luci/admin/network/wireless"):
        """status() -> dict for display (supervisor_openwrt); on_change(reason) restarts the service;
        allowed_networks() -> the networks whose clients may use the page; admin: LuCI's Wi-Fi page."""
        self.state = state
        self.admin = admin
        self.pairing = PairingWindow(state.parent)
        self.status, self.on_change, self.allowed = status, on_change, allowed_networks
        self.server = None
        self.checks_seen, self.checks_lock = {}, threading.Lock()

    def start(self, port=18080):
        page = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):   # keep tokens/passwords out of the journal
                pass

            def _allowed(self):
                client = ipaddress.ip_address(self.client_address[0].removeprefix("::ffff:"))
                return client.is_loopback or any(client in net for net in page.allowed())

            def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
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
                                      {"Content-Disposition": 'attachment; filename="dashplay-diag.txt"'})
                if self.path.split("?")[0] != "/":
                    return self._send(404, "not found")
                self._send(200, page.render(self.path.partition("?")[2]))

            def do_POST(self):
                if not self._allowed():
                    return self._send(403, "forbidden")
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, "too large")
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode(),
                                                                 keep_blank_values=True).items()}
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
        raise ValueError("网络在 OpenWrt 后台设置。")

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

    def chain(self, devices, presence, phase):
        return ui.chain(self.hotspot_node(), self.phone_node(devices, presence.get("active"), phase))

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
        if self.status().get("bluetooth") is False:
            # No Bluetooth adapter was powered when the service started: say so instead of inventing a cable.
            block = ui.banner("蓝牙没有启动，暂时不能添加或邀请 iPhone。重启盒子；仍然不行请下载诊断记录。", "bad") + block
        return block, refresh, devices

    def entries_block(self, status, refresh):
        entries = "".join(f'<div class=cell><span class=main><b>{escape(u)}</b></span></div>'
                          for u in status.get("entries", []) if u.startswith("https"))
        if not entries or refresh:
            return ""
        foot = f"车机连接 Wi-Fi「{escape(status.get('ssid', ''))}」后，在车机浏览器输入上面的地址；画面端口在 OpenWrt 后台的 DashPlay 页设置。"
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
                '<span>Wi-Fi 名称、密码或信道改了以后，DashPlay 会自动跟着改</span></span><span class=chev></span></a>')

    def notices(self):
        status = self.status()
        html = ""
        if status.get("identity") is False:
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
        advanced = ('<a class=cell href="/diag.txt"><span class=main><b>下载诊断记录</b>'
                    '<span>画面卡顿、断线时，把它交给 AI 助手或开发者分析</span></span><span class=chev></span></a>')
        intro = ui.other_screen(self.home()) if not devices and not refresh else ""
        body = (f'<h1 class=span>盒子设置</h1>{notice}{self.chain(devices, presence, phase)}<div>'
                + self.entries_block(status, refresh)
                + ui.group("网络", self.network_block())
                + intro + ui.group("iPhone", block) + '</div><div>'
                + (ui.group("自己的网址", reach) if reach else "")
                + ui.group("程序更新", self.update_block(nonce),
                           "每天自动检查一次，只提示不自动安装。升级前会备份配对、证书和设置，新版本起不来会自动退回。")
                + ui.group("高级", advanced)
                + '</div>')
        return ui.page("盒子设置", body, refresh or update.running(self.state.parent), wide=True)
