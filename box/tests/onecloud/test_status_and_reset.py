"""The status model (docs/STATUS-MODEL.md), the settings page's banners from it, its Host check and its
factory-reset page."""
import json
import re
import urllib.parse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import factory_reset
from settings_page import SettingsPage, host_allowed
from status_model import Status, DOMAINS, read


class StatusModelTests(unittest.TestCase):
    def test_nine_domains_with_state_reason_since(self):
        clock = [1000]
        status = Status(clock=lambda: clock[0], mode="openwrt")
        self.assertEqual(set(DOMAINS), {"bluetooth", "wifi", "uplink", "identity", "phone", "certificate", "update", "system", "tesla"})
        snapshot = status.snapshot()
        for name in DOMAINS:
            self.assertEqual(snapshot[name], {"state": "unknown", "reason": None, "since": 1000})
        self.assertEqual(snapshot["mode"], "openwrt")
        clock[0] = 1010
        self.assertTrue(status.set("bluetooth", "starting", "powering", retry_in=10))
        self.assertEqual(status.domain("bluetooth"), {"state": "starting", "reason": "powering", "since": 1010, "retry_in": 10})
        clock[0] = 1020
        self.assertTrue(status.set("bluetooth", "starting", "powering", retry_in=20), "an extra changed")
        clock[0] = 1030
        self.assertFalse(status.set("bluetooth", "starting", "powering", retry_in=20), "nothing changed: since stays")
        self.assertEqual(status.domain("bluetooth")["since"], 1010, 'telemetry changes do not reset state age')
        with self.assertRaises(KeyError):
            status.set("receiver", "on")

    def test_flat_keys_and_the_file_written_on_change_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            status = Status(path, clock=lambda: 5, home="http://x/")
            status.write()
            first = path.stat().st_mtime_ns
            status["warning"] = "w"
            self.assertEqual(status.get("warning"), "w")
            self.assertIn("warning", status)
            time.sleep(0.01)
            status["warning"] = "w"
            self.assertEqual(json.loads(path.read_text())["warning"], "w")
            after = path.stat().st_mtime_ns
            status.update(warning="w")
            self.assertEqual(path.stat().st_mtime_ns, after, "same content: no write")
            status.pop("warning")
            self.assertNotIn("warning", read(path))
            self.assertEqual(read(path)["bluetooth"]["state"], "unknown")
            self.assertEqual(read(path / "missing"), {})

    def test_failed_publication_can_be_retried(self):
        import status_model
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            status = Status(path)
            with patch.object(status_model.state_files, 'save_json', side_effect=OSError('full')):
                status.set('system', 'ok')
            self.assertFalse(path.exists())
            status.write()
            self.assertEqual(read(path)['system']['state'], 'ok')

    def test_concurrent_publications_cannot_leave_an_older_snapshot(self):
        import status_model
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            status = Status(path)
            entered, release = threading.Event(), threading.Event()
            original = status_model.state_files.save_json
            calls = []
            def save(target, body, **kwargs):
                calls.append(body['system']['state'])
                if len(calls) == 1:
                    entered.set()
                    release.wait(2)
                original(target, body, **kwargs)
            with patch.object(status_model.state_files, 'save_json', side_effect=save):
                old = threading.Thread(target=lambda: status.set('system', 'starting'))
                old.start()
                self.assertTrue(entered.wait(2))
                new = threading.Thread(target=lambda: status.set('system', 'ok'))
                new.start()
                release.set()
                old.join(2); new.join(2)
            self.assertFalse(old.is_alive() or new.is_alive())
            self.assertEqual(read(path)['system']['state'], 'ok')

    def test_removed_metadata_is_not_kept_in_the_published_state(self):
        status = Status()
        status.set('bluetooth', 'starting', 'powering', retry_in=20)
        status.set('bluetooth', 'starting', 'powering')
        self.assertNotIn('retry_in', status.domain('bluetooth'))


class PageBannerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"; self.state.mkdir()
        self.status = Status(clock=lambda: 1, mode="openwrt", ssid="Car-5G", home="http://100.96.0.1:18080/",
                             identity=True, entries=["https://autoplay.lan:18443/"], name="autoplay.lan")
        self.page = SettingsPage(self.state, self.status.snapshot, lambda reason: None, lambda: [])

    def test_bluetooth_failure_is_a_red_bar_with_the_reason(self):
        self.status.set("bluetooth", "failed", "controller-init-failed", retry_in=60)
        html = self.page.render("")
        self.assertIn("蓝牙没有启动：蓝牙芯片初始化失败", html)
        self.assertIn("可以重启盒子；仍不行请下载诊断记录", html)
        self.assertNotIn("数据线", html)
        self.assertIn("蓝牙就绪后才能添加", html)
        self.status.set("bluetooth", "on")
        html = self.page.render("")
        self.assertNotIn("蓝牙没有启动", html)
        self.assertNotIn("蓝牙就绪后才能添加", html)

    def test_certificate_bars(self):
        self.status.update(own_name="mycar.duckdns.org")
        self.status.set("certificate", "expiring_soon", None, not_after="2026-11-20")
        self.status.set("uplink", "offline")
        html = self.page.render("")
        self.assertIn("证书 2026-11-20 到期", html)
        self.assertIn("插上能上网的 SIM 卡", html)
        self.status.set("certificate", "expired", None, not_after="2026-10-01")
        self.status.set("uplink", "online")
        html = self.page.render("")
        self.assertIn("已于 2026-10-01 过期", html)
        self.assertIn("联网后会自动续签", html)
        self.status.set("certificate", "ok", None, not_after="2027-01-01")
        self.assertNotIn("过期", self.page.render(""))

    def test_no_sound_group_and_no_online_banner(self):
        # 1.3.0: every sound is on the Tesla's Bluetooth (no audio route to show), and an upstream that is online is
        # no news; only a down upstream gets a banner (certificates cannot renew, the car will not stay on the hotspot).
        self.status.update(audio_route="carplay", tesla_upstream="online", tesla_internet="上游在线；特斯拉自带音乐、地图可以上网。")
        html = self.page.render("")
        for text in ("导航播报", "声音", "上游在线", "可以上网"):
            self.assertNotIn(text, html)
        self.status.update(tesla_upstream="offline", tesla_internet="上游不可用（没有 4G 信号）；局域网 CarPlay 正常；特斯拉自带音乐、地图不能上网。")
        self.assertIn("盒子没有网络（没有 4G 信号）", self.page.render(""))
        self.status.update(tesla_upstream="unknown", tesla_internet="上游状态检测中；局域网 CarPlay 正常。")
        self.assertNotIn("检测中", self.page.render(""))

    def test_results_are_said_in_their_group_and_errors_at_the_top(self):
        # 1.4.1: a banner at the top is for states to act on and for errors; what an action did is the footer of the
        # group it happened in, and an invitation's note replaces the iPhone group's usual line for that load.
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        nonce = self.page.pairing.nonce
        self.page.pairing.use = lambda phone: None
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "use", "phone": "02:00:00:00:00:01"})
        self.assertEqual(reply["at"], "phones")
        html = self.page.render(urllib.parse.urlencode(reply))
        self.assertIn(f'<p class=foot>{reply["m"]}</p>', html)
        self.assertNotIn('class="banner', html)
        # 1.5.0: with nothing going on the group has no line at all (until 1.4.3 "添加 iPhone 时，请在车机或…")
        self.assertNotIn("<p class=foot>", self.page.render(""))
        self.page.pairing.stop = lambda: None
        self.assertEqual(self.page.apply("/pair", {"nonce": nonce, "action": "cancel"}), "")
        html = self.page.render(urllib.parse.urlencode({"m": "错误：页面已过期，请刷新后重试。", "at": "phones"}))
        self.assertIn('class="banner bad"', html)
        self.assertIn("页面已过期", html)

    def test_rows_carry_icons_and_no_lines_under_links(self):
        html = self.page.render("")
        for icon in ('class="tile blue"', 'class="tile gray"', 'class="tile green"'):
            self.assertIn(icon, html)
        for gone in ("Wi-Fi 名称、密码或信道改了以后", "画面卡顿、断线时", "我的 iPhone"):
            self.assertNotIn(gone, html.replace("\u2011", "-"))

    def test_wifi_keeps_its_hyphen_in_text_but_fields_keep_what_they_hold(self):
        import settings_ui as ui
        html = ui.keep_words('<p>连上 Wi-Fi 后</p><input name=ssid value="My Wi-Fi"><span title="Wi-Fi">Wi-Fi</span>')
        self.assertEqual(html, '<p>连上 Wi\u2011Fi 后</p><input name=ssid value="My Wi-Fi">'
                               '<span title="Wi-Fi">Wi\u2011Fi</span>')
        self.assertEqual(ui.url("https://car.example.com:18443/"), "https://car.example.com<wbr>:18443/")
        self.assertEqual(ui.url("https://a.example/?x=<1>"), "https://a.example/?x=&lt;1&gt;")

    def test_pairing_lost_tells_the_owner_to_re_add(self):
        self.status.set("phone", "pairing-lost", "pairing-lost")
        self.assertIn("请删除此 iPhone 后重新添加", self.page.render(""))

    def test_box_node_follows_bluetooth_and_receiver(self):
        self.status.set("bluetooth", "failed", "rfkill")
        self.assertIn("蓝牙没有启动</div>", self.page.render(""))
        self.status.set("bluetooth", "on")
        self.status.set("system", "degraded", "receiver-exit-1")
        self.assertIn("程序反复重启", self.page.render(""))
        self.status.set("system", "ok")
        self.assertIn(">运行中<", self.page.render(""))

    def test_no_credentials_and_a_status_endpoint_exist(self):
        self.status.set("identity", "missing", "files-missing")
        html = self.page.render("")
        self.assertIn("还缺 CarPlay 认证文件", html)
        self.assertNotIn("1234", html)
        self.assertIn("恢复出厂设置", html)

    def test_removing_a_phone_is_confirmed_on_the_page_not_in_a_browser_box(self):
        """1.2.0: a car browser draws confirm() at the OS size or not at all, so the question is a screen of the page."""
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        removed = []
        self.page.pairing.remove = removed.append
        nonce = self.page.pairing.nonce
        self.assertNotIn("confirm(", self.page.render(""))
        self.assertIn("删除此 iPhone…", self.page.render(""))
        # first press: nothing removed, the redirect asks for the confirmation screen
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01"})
        self.assertEqual(reply, {"ask": "remove", "phone": "02:00:00:00:00:01"})
        self.assertEqual(removed, [])
        html = self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01")
        self.assertIn("从盒子上删除这部 iPhone？", html)
        self.assertIn("小王的 iPhone", html)
        self.assertIn('name=confirmed value="1"', html)
        self.assertNotIn("添加 iPhone", html, "the question is the whole screen")
        # second press carries the confirmation; the phone leaving the list says it all (no banner, 1.4.1)
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01", "confirmed": "1"})
        self.assertEqual(reply, "")
        self.assertEqual(removed, ["02:00:00:00:00:01"])
        # a phone that is gone: no question, the normal page
        self.page.pairing.devices = lambda: {}
        self.assertIn("添加 iPhone", self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01"))

    def test_an_update_is_confirmed_on_the_page_too(self):
        nonce = self.page.pairing.nonce
        reply = self.page.apply("/update", {"nonce": nonce, "action": "install"})
        self.assertEqual(reply, {"ask": "install"})
        (self.state / "update-check.json").write_text(json.dumps({"available": True, "online": True, "latest": "1.4.0", "current": "1.3.0", "checked_at": 1}))
        html = self.page.render("ask=install")
        self.assertIn("现在升级到 1.4.0？", html)
        self.assertIn("立即升级", html)
        self.assertNotIn("confirm(", html)
        with patch("settings_page.update.launch", return_value="正在升级，请稍候") as launch:
            self.assertEqual(self.page.apply("/update", {"nonce": nonce, "action": "install", "confirmed": "1"}),
                             {"m": "正在升级，请稍候", "at": "update"})
        launch.assert_called_once()
        # nothing to install (offline or none found): the normal page instead of an empty question
        (self.state / "update-check.json").write_text(json.dumps({"available": False, "latest": "1.3.0", "checked_at": 1}))
        self.assertIn("添加 iPhone", self.page.render("ask=install"))


    def test_the_page_demands_the_typed_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "state").mkdir()
            changes = []
            page = SettingsPage(root / "state", lambda: {"mode": "openwrt", "home": "http://x/"}, changes.append, lambda: [], root=root)
            nonce = page.pairing.nonce
            with self.assertRaises(ValueError):
                page.apply("/reset", {"nonce": nonce, "confirm": "yes"})
            (root / "state/receiver").mkdir(); (root / "state/receiver/browser-token").write_text("t")
            page.uci = lambda *a, **k: None
            with patch.object(page.pairing, "reset_all"), patch("settings_page.threading.Timer") as timer:
                message = page.apply("/reset", {"nonce": nonce, "confirm": "重置"})
            self.assertIn("已重置", message)
            self.assertFalse((root / "state/receiver").exists())
            timer.assert_called_once()
            html = page.render_reset()
            self.assertIn("恢复出厂设置", html)
            self.assertIn("删除认证文件", html)


class PageLayoutTests(unittest.TestCase):
    """1.5.0: the box page is laid out as the CarPlay page's "AutoPlay 设置" panel - a title bar, categories, one
    column of groups - and shows the colours CarPlay shows."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"; self.state.mkdir()
        self.status = Status(clock=lambda: 1, mode="openwrt", ssid="Car-5G", home="http://100.96.0.1:18080/", identity=True,
                             entries=["https://mycar.duckdns.org:18443/", "https://100.96.0.1:18443/"],
                             name="mycar.duckdns.org", own_name="mycar.duckdns.org")
        self.page = SettingsPage(self.state, self.status.snapshot, lambda reason: None, lambda: [],
                                 thermal=lambda: ({"soc": 58}, {}))
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}

    def pane(self, html, key):
        """One category's page: from its opening tag to the next one's (or to the list of categories)."""
        start = html.index(f"id={key} ")
        ends = [at for at in (html.find('<section class="pane', start), html.find("<nav", start)) if at > 0]
        return html[start:min(ends)]

    def test_categories_and_what_each_holds(self):
        html = self.page.render("")
        self.assertIn("<title>AutoPlay 盒子</title>", html)
        self.assertIn("<h1>AutoPlay 盒子</h1>", html)
        self.assertEqual(re.findall(r'<a href="#(\w+)"[^>]*>([^<]+)', html.split("<nav", 1)[1]),
                         [("iphone", "iPhone"), ("net", "网络"), ("update", "更新"), ("more", "高级")])
        shown = html.replace("\u2011", "-").replace("<wbr>", "")
        for key, texts in {"iphone": ('class=chain', "小王的 iPhone", "添加 iPhone"),
                           "net": ("交给 iPhone 的 Wi-Fi", "Car-5G", "在 OpenWrt 后台设置", "在车机浏览器打开",
                                   "https://mycar.duckdns.org:18443/", "https://100.96.0.1:18443/", "自己的网址", "证书"),
                           "update": ("程序更新", "检查更新"),
                           "more": ("盒子温度", "58 °C", "下载诊断记录", 'href="/reset"', "恢复出厂设置")}.items():
            pane = self.pane(shown, key)
            for text in texts:
                self.assertIn(text, pane, f"{text} belongs under {key}")
        self.assertNotIn("添加 iPhone", self.pane(shown, "net"))
        # No fragment shows the first category: its page comes after the others (the style sheet hides it when one
        # of them is the address's target), and the list of categories after all pages.
        order = [html.index(f"id={key} ") for key in ("net", "update", "more", "iphone")]
        self.assertEqual(order, sorted(order))
        self.assertIn('<section class="pane first" id=iphone ', html)
        self.assertGreater(html.index("<nav"), order[-1])

    def test_no_standing_lines_of_explanation(self):
        # Asked for in the car (2026-11-10): as on the CarPlay page's panel, a row says its name and its value.
        html = self.page.render("")
        self.assertNotIn("<p class=foot>", html)
        for gone in ("每天自动检查一次", "车机连上", "配对一次后", "添加 iPhone 时，请在车机", "蓝牙 …", "正在使用。它断开后"):
            self.assertNotIn(gone, html)
        # Until the first iPhone is added, where to add it from is a group of its own; afterwards it is gone.
        self.assertNotIn("http://100.96.0.1<wbr>:18080/", html)
        self.page.pairing.devices = lambda: {}
        html = self.page.render("")
        self.assertIn("请在车机或另一台设备上打开", html)
        self.assertIn("http://100.96.0.1<wbr>:18080/", html)

    def test_the_bars_button_leads_to_the_carplay_page_this_browser_came_from(self):
        # The CarPlay page keeps its settings per address: back to the one on the name this browser used here. The
        # button carries both of its names; which one shows, and whether it leads to the settings panel, is decided
        # in the browser from what the CarPlay page's link said (from=panel / from=page).
        for host, entry in (("mycar.duckdns.org:18080", "https://mycar.duckdns.org:18443/"),
                            ("100.96.0.1:18080", "https://100.96.0.1:18443/"), ("MYCAR.duckdns.org", "https://mycar.duckdns.org:18443/"),
                            ("autoplay.lan:18080", "https://mycar.duckdns.org:18443/"), ("", "https://mycar.duckdns.org:18443/")):
            html = self.page.render("", host)
            self.assertIn(f'<a class="done out" href="{entry}"><span class=fwd>CarPlay 画面</span><span class=back>返回</span></a>', html, host)
        # its own address first in the list as well
        net = self.pane(self.page.render("", "100.96.0.1:18080"), "net")
        self.assertLess(net.index("https://100.96.0.1<wbr>:18443/"), net.index("https://mycar.duckdns.org<wbr>:18443/"))
        self.status.update(entries=[])
        self.assertNotIn("class=done", self.page.render(""), "no CarPlay page yet (the Wi-Fi is not up), no button")
        # A task's screen has no way out but its own buttons; the reset page's is "cancel".
        self.status.update(entries=["https://100.96.0.1:18443/"])
        self.page.pairing.status = lambda: {"phase": "confirm", "name": "iPhone", "passkey": "123456", "request_id": "r"}
        html = self.page.render("")
        self.assertNotIn("class=done", html)
        self.assertNotIn("<nav", html)
        self.assertIn('<a class=done href="/#more">取消</a>', self.page.render_reset())

    def test_colours_follow_carplay_or_the_browser(self):
        import settings_ui as ui
        html = self.page.render("night=1")
        self.assertIn("<title>AutoPlay 盒子</title>", html, "the query is the browser's business; the page is the same")
        head = html.split("</head>", 1)[0]
        self.assertIn(f"<script>{ui.VISIT}</script>", head, "before anything is drawn")
        for part in ("night=([01])", "from=(panel|page)", 'sessionStorage.setItem("autoplay-visit"', "history.replaceState", "36e5",
                     '"data-theme"', '"data-from"'):
            self.assertIn(part, ui.VISIT)
        # The way back: 返回 shows for a visit that came from the CarPlay page, and leads to its settings panel when
        # the visit began there (the CarPlay page opens the panel at 连接 for this fragment).
        self.assertIn(":root[data-from] .done .back{display:inline}", ui.CSS)
        self.assertIn(".done .back,:root[data-from] .done .fwd{display:none}", ui.CSS)
        self.assertIn('getAttribute("data-from")==="panel")out.href=out.href.split("#")[0]+"#settings=connection"', ui.SCRIPT)
        # Both sets of colours: the handed-over theme wins, the browser's preference decides without one.
        self.assertIn(":root{" + ui.LIGHT, ui.CSS)
        self.assertIn("@media (prefers-color-scheme:dark){:root:not([data-theme=light]){" + ui.DARK + "}}", ui.CSS)
        self.assertIn(":root[data-theme=dark]{" + ui.DARK + "}", ui.CSS)
        self.assertIn("--bg:#000;--cell:#1C1C1E", ui.DARK, "the CarPlay page's own colours")
        self.assertIn('<meta name=color-scheme content="light dark">', head)

    def test_the_panel_and_this_page_share_their_colours(self):
        """The CarPlay page's settings panel and the box page are twins: the same value for every colour they both
        name, by day and by night. The two style sheets live apart (TypeScript bundle, Python string), so this holds
        them together."""
        import settings_ui as ui
        sheet = Path(__file__).resolve().parents[3] / "receiver/web/src/style.css"
        if not sheet.exists():
            self.skipTest("the CarPlay page's sources are not in this tree")
        css = sheet.read_text()

        def values(block):
            return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+?)\s*[;}]", block))
        mine = {"dark": values(ui.DARK + ";"), "light": values(ui.LIGHT + ";")}
        theirs = {"dark": values(css.split("{", 1)[1].split("}", 1)[0] + ";"),
                  "light": values(re.search(r":root\[data-theme=light\] dialog \{([^}]*)\}", css).group(1) + ";")}
        shared = ("--bg", "--cell", "--press", "--sep", "--label", "--secondary", "--tint", "--green", "--red", "--orange", "--fill", "--chev")
        for theme in ("dark", "light"):
            for name in shared:
                self.assertEqual(mine[theme][name].replace(" ", ""), theirs[theme][name].replace(" ", ""), f"{name} by {theme}")
        self.assertEqual(mine["dark"]["--btn"], theirs["dark"]["--tint-under-white"])
        self.assertEqual(mine["light"]["--btn"], theirs["light"]["--tint-under-white"])

    def test_the_style_sheet_keeps_its_lines_and_carries_no_comments(self):
        import settings_ui as ui
        self.assertNotIn("/*", ui.CSS)
        self.assertNotIn("@LIGHT@", ui.CSS); self.assertNotIn("@DARK@", ui.CSS)
        # .cell clears its border with the same weight as the rule that draws the line between rows: the line's rule
        # has to come later, or rows that are .cell lose it (seen while building 1.5.0).
        self.assertGreater(ui.CSS.index(".group>*+*"), ui.CSS.index("background:none;border:0;border-radius:0"))
        # The chosen category: the first without a fragment, the target's otherwise.
        for rule in (".pane.first,.pane:target{display:block}", ".pane:target~.pane.first{display:none}",
                     '#net:target~.nav a[href="#net"]', "scroll-margin-top:100vh"):
            self.assertIn(rule, ui.CSS)

    def test_a_buttons_answer_comes_back_on_its_category(self):
        import http.client
        self.page.start(0)   # any free port; a request from the loopback is the box's own
        self.addCleanup(self.page.stop)
        port = self.page.server.server_address[1]

        def post(path, **form):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("POST", path, urllib.parse.urlencode({"nonce": self.page.pairing.nonce, **form}),
                               {"Content-Type": "application/x-www-form-urlencoded", "Host": f"127.0.0.1:{port}"})
            reply = connection.getresponse(); reply.read(); connection.close()
            return reply.status, reply.getheader("Location")

        with patch("settings_page.update.check"):
            self.assertEqual(post("/update", action="check"), (303, "/?m=#update"))
        self.assertEqual(post("/update", action="install"), (303, "/?ask=install#update"))
        self.page.pairing.stop = lambda: None
        self.assertEqual(post("/pair", action="cancel"), (303, "/?m="), "the first category needs no fragment")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/?night=0", headers={"Host": f"127.0.0.1:{port}"})
        reply = connection.getresponse(); html = reply.read().decode(); connection.close()
        self.assertEqual(reply.status, 200)
        self.assertIn("<h1>AutoPlay 盒子</h1>", html)


class HostCheckTests(unittest.TestCase):
    def test_only_the_boxs_own_names_and_addresses(self):
        import ipaddress
        nets = [ipaddress.ip_network("100.96.0.0/24")]
        names = ("mycar.duckdns.org", "autoplay.lan")
        for host in ("100.96.0.1:18080", "100.96.0.1", "autoplay.lan:18080", "MyCar.duckdns.org", "127.0.0.1:18080", "dashplay.lan"):
            self.assertTrue(host_allowed(host, nets, names), host)
        self.assertTrue(host_allowed("[::1]:18080", nets, names), "the IPv6 loopback is the box itself")
        for host in ("evil.example", "10.0.0.1:18080", "192.168.1.1", "", "[fd00::1]:18080"):
            self.assertFalse(host_allowed(host, nets, names), host)


if __name__ == "__main__":
    unittest.main()
