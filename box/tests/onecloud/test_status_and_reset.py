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
import update
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
        # 1.6.0: the reason is the title, what to do the line under it (it was 「蓝牙未启动：蓝牙芯片初始化失败。请重启盒子。」)
        self.assertIn('<p class="banner bad" role=status><span><b>蓝牙芯片初始化失败</b><span>请重启盒子。</span></span></p>', html)
        self.assertNotIn("蓝牙未启动：", html)
        self.assertIn("<div class=state>蓝牙未启动</div>", html, "the box's state in the chain stays, a word beside it")
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
        self.assertIn("<b>证书将于 2026-11-20 到期</b>", html)
        self.assertIn("请插入可上网的 SIM 卡。", html)
        self.status.set("certificate", "expired", None, not_after="2026-10-01")
        self.status.set("uplink", "online")
        html = self.page.render("")
        self.assertIn("<b>证书已于 2026-10-01 过期</b><span>车机会提示不安全。联网后会自动续签。</span>", html)
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
        self.assertIn("盒子无 4G 网络", self.page.render(""))
        self.status.update(tesla_upstream="unknown", tesla_internet="上游状态检测中；局域网 CarPlay 正常。")
        self.assertNotIn("检测中", self.page.render(""))

    def test_results_are_said_in_their_group_and_errors_at_the_top(self):
        # 1.4.1: a banner at the top is for states to act on and for errors; what an action did is the footer of the
        # group it happened in, and an invitation's note replaces the iPhone group's usual line for that load.
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        nonce = self.page.pairing.nonce
        self.page.pairing.use = lambda phone: None
        # 1.6.0: an invitation says nothing under the group - the phone's row says 「正在接入…」 (below)
        self.assertEqual(self.page.apply("/pair", {"nonce": nonce, "action": "use", "phone": "02:00:00:00:00:01"}), "")
        self.page.pairing.joining = lambda: "02:00:00:00:00:01"
        html = self.page.render("")
        self.assertIn('<span class="value busy"><span class=spin></span>正在接入…</span>', html)
        self.assertNotIn("<p class=foot>", html)
        self.assertNotIn('class="banner', html)
        self.assertIn("http-equiv=refresh content=3", html, "until it is there")
        self.page.pairing.joining = lambda: None
        # 1.5.0: with nothing going on the group has no line at all (until 1.4.3 "添加 iPhone 时，请在车机或…")
        self.assertNotIn("<p class=foot>", self.page.render(""))
        self.page.pairing.stop = lambda: None
        self.assertEqual(self.page.apply("/pair", {"nonce": nonce, "action": "cancel"}), "")
        # What an action could not do is a capsule at the page's foot (1.6.2; an alert in 1.6.0-1.6.1, a red banner
        # at the top before)
        html = self.page.render(urllib.parse.urlencode({"m": "错误：页面已过期，请再试一次。", "at": "phones"}))
        self.assertNotIn('class="banner', html)
        self.assertIn('<p class=capsule role=status>页面已过期，请再试一次</p>', html)

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
        self.assertIn("请删除后重新添加", self.page.render(""))

    def test_box_node_follows_bluetooth_and_receiver(self):
        self.status.set("bluetooth", "failed", "rfkill")
        self.assertIn("蓝牙未启动</div>", self.page.render(""))
        self.status.set("bluetooth", "on")
        self.status.set("system", "degraded", "receiver-exit-1")
        self.assertIn("程序反复重启", self.page.render(""))
        self.status.set("system", "ok")
        self.assertIn(">运行中<", self.page.render(""))

    def test_no_credentials_and_a_status_endpoint_exist(self):
        self.status.set("identity", "missing", "files-missing")
        html = self.page.render("")
        self.assertIn("缺少 CarPlay 认证文件", html)
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
        # 1.6.0: one shape for every one-task screen - the task is the title, 取消 the bar's button, one button below
        self.assertIn("<h1>删除 iPhone</h1>", html)
        self.assertIn('<a class=done href="/">取消</a>', html)
        self.assertNotIn("class=group-title", html, "the question was the smallest text on the screen")
        self.assertIn("小王的 iPhone", html)
        self.assertNotIn("<p class=foot>", html, "the title and the phone say enough (an action sheet's message is optional)")
        self.assertNotIn("蓝牙 …", html, "the address only where two phones share a name")
        self.assertIn('name=confirmed value="1"', html)
        self.assertEqual(html.count("<button"), 1, "取消 is the bar's")
        # Apple's guidelines: a destructive action is red text, never the prominent filled button
        self.assertIn('<button class="cell destructive" name=action value=remove>删除此 iPhone</button>', html)
        self.assertNotIn("添加 iPhone", html, "the question is the whole screen")
        # second press carries the confirmation; the phone leaving the list says it all (no banner, 1.4.1)
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01", "confirmed": "1"})
        self.assertEqual(reply, "")
        self.assertEqual(removed, ["02:00:00:00:00:01"])
        # a phone that is gone: no question, the normal page
        self.page.pairing.devices = lambda: {}
        self.assertIn("添加 iPhone", self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01"))

    def test_an_upgrade_starts_at_once(self):
        """1.6.0: no confirmation screen (1.2.0-1.5.3 asked first). Apple's guidelines keep confirmations for what loses
        data unexpectedly; an upgrade loses none, is refused while CarPlay is in use and goes back by itself."""
        nonce = self.page.pairing.nonce
        (self.state / "update-check.json").write_text(json.dumps({"available": True, "online": True, "latest": "1.4.0", "current": "1.3.0", "checked_at": 1}))
        with patch("settings_page.update.launch", return_value="已开始升级") as launch:
            self.assertEqual(self.page.apply("/update", {"nonce": nonce, "action": "install"}), "")
        launch.assert_called_once()
        self.assertIn("添加 iPhone", self.page.render("ask=install"), "an old link to the question shows the page")


    def test_a_notice_is_a_title_and_a_line(self):
        """1.6.0: what happened in bold, what to do under it, as an alert has them; one sentence where the words also
        stand alone (LuCI, the diagnostics), split at its first 「：」 or before 「，请」."""
        import settings_page
        import settings_ui as ui
        self.assertEqual(ui.parts("AutoPlay 热点尚未就绪：「Car-5G」尚未开启。"), ("AutoPlay 热点尚未就绪", "「Car-5G」尚未开启。"))
        self.assertEqual(ui.parts("iPhone 未确认配对：请让 iPhone 停留在「设置 → 蓝牙」，再点一次它的名称。"),
                         ("iPhone 未确认配对", "请让 iPhone 停留在「设置 → 蓝牙」，再点一次它的名称。"))
        self.assertEqual(ui.parts("配对已取消，请重试。"), ("配对已取消", "请重试。"))
        self.assertEqual(ui.parts("找不到此页面。"), ("找不到此页面", ""))
        self.assertEqual(ui.banner(("蓝牙被另一个程序占用", "请重启盒子。"), "bad"),
                         '<p class="banner bad" role=status><span><b>蓝牙被另一个程序占用</b><span>请重启盒子。</span></span></p>')
        self.assertEqual(ui.banner("找不到此页面。", "wait"), '<p class="banner wait" role=status><span><b>找不到此页面</b></span></p>')
        # every notice the page can show has a title of its own and no 「蓝牙未启动：」-style prefix before it
        for reason, (title, line) in settings_page.BLUETOOTH_TEXT.items():
            self.assertNotIn("：", title + line.replace("python3 ", ""), reason)
            self.assertFalse(title.startswith("蓝牙未启动"), reason)
        self.assertEqual(settings_page.BLUETOOTH_TEXT["hci-lost"][1], "正在重新启动蓝牙，也可以重启盒子。",
                         "where the box restarts Bluetooth by itself it says so, not only 「请重启盒子」")

    def test_what_an_action_could_not_do_is_a_capsule(self):
        """1.6.2 (owner's call): one sentence in a capsule at the page's foot, gone by itself after 6 s, as on the
        CarPlay page - by CSS, so without JS too. 1.6.0-1.6.1 had Apple's alert with 「好」; before, a red notice at
        the top, out of sight on the 高级 category."""
        import settings_ui as ui
        import pairing_window
        with patch.object(pairing_window, "read_json", return_value={"active": "02:00:00:00:00:01"}):
            with self.assertRaisesRegex(ValueError, "^CarPlay 正在使用中，请先断开再添加 iPhone。$"):
                pairing_window.PairingWindow.start(self.page.pairing)
        html = self.page.render(urllib.parse.urlencode({"m": "错误：CarPlay 正在使用中，请先断开再添加 iPhone。"}))
        self.assertIn("<p class=capsule role=status>CarPlay 正在使用中，请先断开再添加 iPhone</p>", html)
        self.assertNotIn('class="banner bad"', html)
        self.assertNotIn("scrim", html); self.assertNotIn("alertdialog", html)
        self.assertLess(html.index("<p class=capsule"), html.index(ui.SCRIPT), "the script finds the capsule")
        # a result is no capsule
        self.assertNotIn("class=capsule", self.page.render(urllib.parse.urlencode({"m": "已拒绝此次配对。", "at": "phones"})))
        # a page that reloads itself waits for the capsule (6 s) and does it by script, at the address without the
        # message; a refresh tag would bring the message back
        self.page.pairing.status = lambda: {"phase": "waiting", "found": []}
        html = self.page.render(urllib.parse.urlencode({"m": "错误：配对请求已变化，请重新核对配对码。"}))
        self.assertIn("<h1>添加 iPhone</h1>", html)
        self.assertIn("<p class=capsule role=status>配对请求已变化，请重新核对配对码</p>", html)
        self.assertNotIn("http-equiv=refresh", html)
        self.assertIn("<script>setTimeout(function(){location.reload()},6500)</script>", html)
        self.assertIn("http-equiv=refresh content=3", ui.page("x", "", True))
        self.assertNotIn("location.reload", ui.page("x", "", False, capsule=ui.capsule("错误：a，b")))
        # the reset's capsule is on the reset page
        html = self.page.render_reset(urllib.parse.urlencode({"m": "错误：确认词不正确，请输入「重置」。"}))
        self.assertIn("<p class=capsule role=status>确认词不正确，请输入「重置」</p>", html)
        self.assertNotIn("class=capsule", self.page.render_reset(""))
        # the script takes the message out of the address; the capsule rises, and fades after 6 s
        self.assertIn('if(document.querySelector(".capsule")){var q=location.search.replace(/([?&])(m|at)=[^&]*&?/g,"$1").replace(/[?&]$/,"");', ui.SCRIPT)
        self.assertIn("history.replaceState(null,\"\",location.pathname+q+location.hash)", ui.SCRIPT)
        self.assertIn('if(location.hash&&(!n||n.type==="navigate"))setTimeout(function(){scrollTo(0,0)},0)', ui.SCRIPT)
        for rule in (".capsule{position:fixed;left:50%;bottom:", "animation:rise .3s cubic-bezier(.2,.8,.2,1),fade .3s 6s forwards}",
                     "@keyframes fade{to{opacity:0;visibility:hidden}}", ".capsule{animation:fade 0s 6s forwards}",
                     "background:rgba(20,20,22,.88);border:1px solid rgba(255,255,255,.28);"):
            self.assertIn(rule, ui.CSS)
        for gone in (".scrim", ".alert{", ".alert ", "--raised", "alert-title"):
            self.assertNotIn(gone, ui.CSS + ui.SCRIPT)

    def test_the_page_demands_the_typed_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "state").mkdir()
            changes = []
            page = SettingsPage(root / "state", lambda: {"mode": "openwrt", "home": "http://x/"}, changes.append, lambda: [], root=root)
            nonce = page.pairing.nonce
            with self.assertRaisesRegex(ValueError, "^确认词不正确，请输入「重置」。$"):
                page.apply("/reset", {"nonce": nonce, "confirm": "yes"})
            (root / "state/receiver").mkdir(); (root / "state/receiver/browser-token").write_text("t")
            page.uci = lambda *a, **k: None
            with patch.object(page.pairing, "reset_all"), patch("settings_page.threading.Timer") as timer:
                message = page.apply("/reset", {"nonce": nonce, "confirm": "重置"})
            self.assertEqual(message, "已恢复出厂设置：盒子正在重新启动，之后请重新添加 iPhone。")
            self.assertFalse((root / "state/receiver").exists())
            timer.assert_called_once()
            html = page.render_reset()
            self.assertIn("恢复出厂设置", html)
            self.assertIn('placeholder="输入「删除认证文件」"', html)
            # 1.6.0: names only (no line under a row or a group), the button a red row (Apple: never a filled
            # destructive button)
            main = html.split("<main", 1)[1]
            self.assertNotIn("<p class=foot>", main)
            self.assertNotIn("<span>", main)
            self.assertNotIn("class=sub", main)
            self.assertIn('<button class="cell destructive">恢复出厂设置</button>', main)


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
        self.assertIn("<title>AutoPlay 设置</title>", html)
        self.assertIn("<h1>AutoPlay 设置</h1>", html)
        self.assertEqual(re.findall(r'<a href="#(\w+)"[^>]*>([^<]+)', html.split("<nav", 1)[1]),
                         [("iphone", "iPhone"), ("net", "网络"), ("update", "更新"), ("more", "高级")])
        shown = html.replace("\u2011", "-").replace("<wbr>", "")
        for key, texts in {"iphone": ('class=chain', "小王的 iPhone", "添加 iPhone"),
                           "net": ("AutoPlay 热点", "Car-5G", "在 OpenWrt 后台设置", "在车机浏览器打开",
                                   "https://mycar.duckdns.org:18443/", "https://100.96.0.1:18443/", "自定义域名", "证书"),
                           "update": ("程序更新", "检查更新"),
                           "more": ("盒子温度", "58 °C", "下载诊断记录", 'href="/reset"', "恢复出厂设置")}.items():
            pane = self.pane(shown, key)
            for text in texts:
                self.assertIn(text, pane, f"{text} belongs under {key}")
        self.assertNotIn("添加 iPhone", self.pane(shown, "net"))
        # 1.6.0: a group's title does not repeat its category's name (iPhone / iPhone, 高级 / 高级)
        for key in ("iphone", "more"):
            self.assertNotIn("<section><p class=group-title>", self.pane(shown, key))
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
        # Where to add an iPhone from is said on the pairing screen, before the first iPhone only (1.6.0: until then
        # it was a standing group of the iPhone category).
        self.assertNotIn("http://100.96.0.1<wbr>:18080/", html)
        self.page.pairing.devices = lambda: {}
        html = self.page.render("")
        self.assertNotIn("车机或另一台设备", html)
        self.assertNotIn("<p class=foot>", html)
        self.page.pairing.status = lambda: {"phase": "waiting", "found": []}
        html = self.page.render("")
        # 1.6.0: the list alone (three numbered steps under a 怎么做 title, then one line, until then; the owner's rule:
        # no line that tells how to do the task)
        self.assertIn("正在寻找附近的 iPhone…", html)
        self.assertNotIn("<p class=foot>", html)
        self.assertNotIn("怎么做", html)
        self.assertNotIn("<ol", html)
        self.assertNotIn("车机或另一台设备", html)
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        self.assertNotIn("<p class=foot>", self.page.render(""))

    def test_the_bars_button_leads_to_the_carplay_page_this_browser_came_from(self):
        # The CarPlay page keeps its settings per address: back to the one on the name this browser used here. The
        # button carries both of its names; which one shows, and whether it leads to the settings panel, is decided
        # in the browser from what the CarPlay page's link said (from=panel / from=page).
        for host, entry in (("mycar.duckdns.org:18080", "https://mycar.duckdns.org:18443/"),
                            ("100.96.0.1:18080", "https://100.96.0.1:18443/"), ("MYCAR.duckdns.org", "https://mycar.duckdns.org:18443/"),
                            ("autoplay.lan:18080", "https://mycar.duckdns.org:18443/"), ("", "https://mycar.duckdns.org:18443/")):
            html = self.page.render("", host)
            # 1.6.0: Apple's Back button (the chevron alone) on the leading edge; 「CarPlay 画面」 on the trailing edge
            self.assertIn(f'<header><div><a class="done icon out back" href="{entry}" aria-label="返回"><svg', html, host)
            self.assertIn(f'<h1>AutoPlay 设置</h1><a class="done out fwd" href="{entry}">CarPlay 画面</a></div></header>', html, host)
        # its own address first in the list as well
        net = self.pane(self.page.render("", "100.96.0.1:18080"), "net")
        self.assertLess(net.index("https://100.96.0.1<wbr>:18443/"), net.index("https://mycar.duckdns.org<wbr>:18443/"))
        self.status.update(entries=[])
        self.assertNotIn("class=done", self.page.render(""), "no CarPlay page yet (the Wi-Fi is not up), no button")
        # A task's screen has no way out but 取消 in the bar (1.6.0: the pairing's cancel was a button in the body).
        self.status.update(entries=["https://100.96.0.1:18443/"])
        self.page.pairing.status = lambda: {"phase": "confirm", "name": "iPhone", "passkey": "123456", "request_id": "r"}
        html = self.page.render("")
        self.assertIn("<h1>添加 iPhone</h1>", html)
        # 1.6.0: 「配对」, the iPhone's own word, as the one row; no yes/no pair and no line explaining two buttons
        self.assertIn('<button class="cell action" name=action value=yes>配对</button>', html)
        self.assertNotIn("不一致", html)
        self.assertNotIn("value=no", html)
        self.assertNotIn("<p class=foot>", html, "the iPhone shows its own request with the code and 配对")
        self.assertIn('<form method=post action=/pair>', html.split("</header>")[0])
        self.assertIn('<button class=done name=action value=cancel>取消</button>', html.split("</header>")[0])
        self.assertNotIn("CarPlay 画面", html)
        self.assertNotIn("<nav", html)
        self.assertIn('<a class=done href="/#more">取消</a>', self.page.render_reset())

    def test_the_review_against_apples_guidelines(self):
        """1.6.0, the second review against Apple's guidelines: a known size downloads with a bar, an old check is
        made when 更新 opens, a notice about the hotspot links to the page that fixes it, pairing says what it is
        doing."""
        import settings_ui as ui
        # determinate progress while downloading (update.install writes the share)
        (self.state / "update-status.json").write_text(json.dumps({"phase": "downloading", "message": "正在下载 1.6.0，共 38 MB", "progress": 0.42, "at": int(time.time())}))
        with patch("settings_page.update.running", return_value=True):
            html = self.page.render("")
        self.assertIn('<progress max=100 value=42 aria-label="已下载 42%"></progress>', html)
        self.assertIn("<span class=value>42%</span>", html)
        (self.state / "update-status.json").unlink()
        # an old check is made when 更新 opens (the script submits the marked form); a fresh one is not
        (self.state / "update-check.json").write_text(json.dumps({"latest": "1.6.0", "current": "1.6.0", "checked_at": int(time.time()) - 7200}))
        self.assertIn("<form method=post action=/update data-auto>", self.page.render(""))
        (self.state / "update-check.json").write_text(json.dumps({"latest": "1.6.0", "current": "1.6.0", "checked_at": int(time.time())}))
        self.assertNotIn("<form method=post action=/update data-auto>", self.page.render(""))
        self.assertIn('function auto(){if(location.hash!=="#update")return;var f=document.querySelector("form[data-auto]")', ui.SCRIPT)
        self.assertIn('sessionStorage.setItem(k,n)}catch(e){}var b=f.querySelector("button[name=action]");if(b)b.click()}', ui.SCRIPT)
        # a notice about the hotspot leads to OpenWrt's Wi-Fi page instead of saying where it is
        self.status.update(warning="特斯拉不支持信道 44：请将 AutoPlay 热点改为信道 149 或 36，国家代码选 CN。")
        html = self.page.render("")
        self.assertIn('<p class="banner bad" role=status><span><b>特斯拉不支持信道 44</b><span>请将 AutoPlay 热点改为信道 149 或 36，'
                      '国家代码选 CN。</span><a href="http://100.96.0.1/cgi-bin/luci/admin/network/wireless">在 OpenWrt 后台设置</a>'
                      '</span></p>', html)
        self.assertNotIn("「网络 → 无线」", html)
        self.status.update(warning="")
        # pairing says what it is doing, not 「请稍候」
        for phase, words in (("starting", "正在打开配对…"), ("finishing", "正在完成配对…")):
            self.page.pairing.status = lambda phase=phase: {"phase": phase}
            html = self.page.render("")
            self.assertIn(words, html)
            self.assertNotIn("请稍候", html)

    def test_a_phone_being_invited_says_so_in_its_own_row(self):
        """1.6.0: after a pairing (or 接入 CarPlay) the box invites the phone for 90 s; its row says 「正在接入…」 for that
        long, the chain too, and the page refreshes. It said so as a screen of its own until 1.5.3 (for as long as the
        phone did not come), then as a line under the group."""
        import pairing_window
        self.page.pairing.presence = lambda: {}
        self.page.pairing.status = lambda: {"phase": "paired", "at": 1}
        grant = self.state / "receiver/pairing-request.json"
        grant.parent.mkdir(parents=True, exist_ok=True)
        boot = pairing_window.get_platform().boot_id()
        grant.write_text(json.dumps({"phone": "02:00:00:00:00:01", "boot": boot, "expires": time.monotonic() + 60}))
        html = self.page.render("")
        self.assertIn("<nav", html, "the normal page")
        self.assertIn("正在接入…", self.pane(html, "iphone"))
        self.assertIn("<div class=name>小王的 iPhone</div><div class=state>正在接入</div>", html)
        self.assertIn("http-equiv=refresh content=3", html)
        self.assertNotIn("<p class=foot>", html)
        grant.write_text(json.dumps({"phone": "02:00:00:00:00:01", "boot": boot, "expires": time.monotonic() - 1}))
        html = self.page.render("")
        self.assertNotIn("正在接入", html, "the invitation ran out")
        self.assertNotIn("http-equiv=refresh", html)
        grant.write_text(json.dumps({"phone": "02:00:00:00:00:01", "boot": "another boot", "expires": time.monotonic() + 60}))
        self.assertNotIn("正在接入", self.page.render(""), "an invitation from before a restart")
        self.page.pairing.presence = lambda: {"active": "02:00:00:00:00:01"}
        grant.write_text(json.dumps({"phone": "02:00:00:00:00:01", "boot": boot, "expires": time.monotonic() + 60}))
        self.assertIn(">正在使用<", self.page.render(""), "there: in use")

    def test_a_failed_check_is_one_sentence_and_its_details_go_to_the_diagnostics(self):
        import settings_page
        said = {"下载失败：60 秒内没有拿到更新清单（github: timed out）。网络恢复后再试，或在设置里换一个镜像": "无法连接 GitHub 和下载镜像，请稍后再试。",
                "更新清单的签名不对，已忽略（可能是镜像或网络被篡改；mirror: 签名不对）": "更新清单未通过签名验证，已忽略。",
                "检查更新失败：Expecting value": "检查未完成，请稍后再试。"}
        for error, sentence in said.items():
            self.assertEqual(settings_page.check_failure(error), sentence)
        (self.state / "update-check.json").write_text(json.dumps({"error": list(said)[0], "checked_at": 1}))
        html = self.page.render("")
        self.assertIn("无法连接 GitHub 和下载镜像，请稍后再试。", html)
        for gone in ("github: timed out", "换一个镜像"):
            self.assertNotIn(gone, html)
        root = self.state.parent
        with patch("update.latest_manifest", side_effect=update.UpdateError("下载失败（github: timed out）")), \
                patch("update.mirrors", return_value=()):
            update.check(root, openwrt=True)
        lines = (self.state / "diag/diag.jsonl").read_text().splitlines()
        record = json.loads(lines[-1])
        self.assertEqual(record["event"], "update_check")
        self.assertIn("github: timed out", record["error"])

    def test_no_filled_buttons_on_any_screen(self):
        """1.6.0: every action on this page is a row of a list, blue (action) or red (destructive), as the rest of the
        page and the CarPlay page's panel act; the full-width filled buttons are gone with their styles."""
        import settings_ui as ui
        self.assertNotIn(".btn", ui.CSS)
        screens = [self.page.render(""), self.page.render_reset()]
        (self.state / "update-check.json").write_text(json.dumps({"available": True, "online": True, "latest": "1.6.0", "current": "1.6.0", "checked_at": 1}))
        screens.append(self.page.render("ask=install"))
        screens.append(self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01"))
        for phase in ({"phase": "waiting", "found": []}, {"phase": "confirm", "name": "iPhone", "passkey": "123456", "request_id": "r"},
                      {"phase": "pairing", "name": "iPhone"}):
            self.page.pairing.status = lambda phase=phase: phase
            screens.append(self.page.render(""))
        for html in screens:
            self.assertNotRegex(html, r'class="?btn')

    def test_refused_and_missing_pages_are_pages_of_the_box(self):
        """1.6.0: a bare English "forbidden" / "not found" was all a browser got."""
        refused, missing = self.page.render_refused(), self.page.render_missing()
        self.assertIn("<h1>AutoPlay 设置</h1>", refused)
        self.assertIn("请连接 AutoPlay 热点后，从「AutoPlay → 连接 → AutoPlay 设置」打开。", refused)
        self.assertNotIn("class=done", refused)
        self.assertNotIn("Car-5G", refused, "nothing of the box for a browser that may not see it")
        self.assertIn("<b>找不到此页面</b>", missing)
        self.assertIn('<a class="done icon" href="/" aria-label="返回"><svg', missing)

    def test_colours_follow_carplay_or_the_browser(self):
        import settings_ui as ui
        html = self.page.render("night=1")
        self.assertIn("<title>AutoPlay 设置</title>", html, "the query is the browser's business; the page is the same")
        head = html.split("</head>", 1)[0]
        self.assertIn(f"<script>{ui.VISIT}</script>", head, "before anything is drawn")
        for part in ("night=([01])", "from=(panel|page)", 'sessionStorage.setItem("autoplay-visit"', "history.replaceState", "36e5",
                     '"data-theme"', '"data-from"'):
            self.assertIn(part, ui.VISIT)
        # The way back: 返回 shows for a visit that came from the CarPlay page, and leads to its settings panel when
        # the visit began there (the CarPlay page opens the panel at 连接 for this fragment).
        self.assertIn(":root[data-from] .done.back{display:inline-flex}", ui.CSS)
        self.assertIn(".done.back,:root[data-from] .done.fwd{display:none}", ui.CSS)
        self.assertIn('document.querySelector("a.done.back")', ui.SCRIPT)
        self.assertIn('getAttribute("data-from")==="panel")out.href=out.href.split("#")[0]+"#settings=connection"', ui.SCRIPT)
        # Both sets of colours: the handed-over theme wins, the browser's preference decides without one.
        self.assertIn(":root{" + ui.LIGHT, ui.CSS)
        self.assertIn("@media (prefers-color-scheme:dark){:root:not([data-theme=light]){" + ui.DARK + "}}", ui.CSS)
        self.assertIn(":root[data-theme=dark]{" + ui.DARK + "}", ui.CSS)
        self.assertIn("--bg:#000;--cell:#1C1C1E", ui.DARK, "the CarPlay page's own colours")
        self.assertIn('<meta name=color-scheme content="light dark">', head)

    def test_the_panel_and_this_page_share_their_colours(self):
        """The CarPlay page's own screens (the settings panel, the waiting screen) and the box page are twins: the same
        value for every colour they both name, by day and by night. The two style sheets live apart (TypeScript bundle, Python string), so this holds
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
                  "light": values(re.search(r":root\[data-theme=light\] dialog, :root\[data-theme=light\] #overlay \{([^}]*)\}", css).group(1) + ";")}
        shared = ("--bg", "--cell", "--press", "--sep", "--label", "--secondary", "--tint", "--green", "--red", "--orange", "--fill", "--chev")
        for theme in ("dark", "light"):
            for name in shared:
                self.assertEqual(mine[theme][name].replace(" ", ""), theirs[theme][name].replace(" ", ""), f"{name} by {theme}")
        self.assertEqual(mine["dark"]["--btn"], theirs["dark"]["--tint-under-white"])
        self.assertEqual(mine["light"]["--btn"], theirs["light"]["--tint-under-white"])

    def test_the_panel_and_this_page_place_their_title_bars_alike(self):
        """1.5.1: on a wide screen the panel kept "AutoPlay 设置" and 完成 at the window's edges while this page's title and
        返回 stayed with the columns, and on a phone the two bars differed in height and type. The panel follows this
        page now. What places the bar is the same in both sheets: the root size at every width, the bar's height, the
        1440 px the bar's contents keep to (written here as a width, there as half of it on each side), the title's
        size at each step, the button's. scripts/ui-shots.mjs twins measures the result in a browser."""
        import settings_ui as ui
        sheet = Path(__file__).resolve().parents[3] / "receiver/web/src/style.css"
        if not sheet.exists():
            self.skipTest("the CarPlay page's sources are not in this tree")
        theirs, mine = re.sub(r"\s+", "", sheet.read_text()), re.sub(r"\s+", "", ui.CSS)

        def one(pattern, text):
            found = re.search(pattern, text)
            self.assertTrue(found, pattern)
            return found.group(1)

        def phone(text, names):
            rules = dict(part.split(":", 1) for part in one(r"@media\(max-width:480px\)\{:root\{([^}]*)\}", text).strip(";").split(";"))
            return [rules[name] for name in names]
        # one root size down to 480 px, another below, and the touch targets and the bar that go with it
        size = r":root\{[^}]*font-size:(clamp\([^;}]*\))[;}]"
        self.assertEqual(one(size, theirs), one(size, mine))
        self.assertEqual(phone(theirs, ("font-size", "--hit-primary", "--hit-secondary", "--bar")), phone(mine, ("font-size", "--hit", "--hit2", "--bar")))
        self.assertNotIn("@media(max-width:760px){:root", theirs)
        self.assertNotIn("@media(max-width:760px){:root", mine)
        for theirs_name, mine_name in (("--bar", "--bar"), ("--hit-primary", "--hit"), ("--hit-secondary", "--hit2")):
            self.assertEqual(one(rf":root\{{[^}}]*{theirs_name}:([\d.]+rem)", theirs), one(rf":root\{{[^}}]*{mine_name}:([\d.]+rem)", mine), mine_name)
        # the bar: as high, its contents as wide and as far from the edges, at each width
        bar, here = one(r"dialogheader\{([^}]*)\}", theirs), one(r"header>div\{([^}]*)\}", mine)
        self.assertIn("min-height:calc(var(--bar)+1px)", bar)                      # the line under it is inside the panel's box,
        self.assertIn("min-height:var(--bar)", here)                              # under this page's
        self.assertIn("header{position:-webkit-sticky;position:sticky;top:0;z-index:3;background:var(--bg);border-bottom:1pxsolidvar(--sep)}", mine)
        self.assertEqual(one(r"max-width:(\d+)px", here), "1440")
        self.assertEqual(bar.count("calc(50%-720px+var(--space-4))"), 2)
        self.assertIn("max(var(--s4),env(safe-area-inset-right))var(--s2)max(var(--s4),env(safe-area-inset-left))", here)
        self.assertIn("max(var(--space-2),env(safe-area-inset-top))", bar)
        self.assertIn("max(var(--s2),env(safe-area-inset-top))", here)
        self.assertIn("@media(max-width:760px){header>div{padding-left:var(--s3);padding-right:var(--s3)}h1{font-size:1.4rem}", mine)
        self.assertIn("dialogheader{padding-left:var(--space-3);padding-right:var(--space-3);}", theirs)
        # the title and the button (1.6.0, Apple's toolbars and sheets: the button on the leading edge - the panel's
        # close cross, this page's chevron back or 取消 - and the title in the middle)
        self.assertIn("grid-template-columns:1frauto1fr;", bar)
        self.assertIn("grid-template-columns:1frauto1fr;", here)
        self.assertEqual(one(r"--t-title:([\d.]+rem)", theirs), one(r"h1\{[^}]*font-size:([\d.]+rem)", mine))
        self.assertIn("h2{font-size:var(--t-title);line-height:1.3;font-weight:600;", theirs)
        self.assertIn("dialogheaderh2{grid-column:2;grid-row:1;min-width:0;text-align:center;", theirs)
        self.assertIn("h1{grid-column:2;grid-row:1;font-size:1.6rem;line-height:1.3;font-weight:600;letter-spacing:normal;margin:0;min-width:0;text-align:center;", mine)
        self.assertEqual(re.findall(r"h2\{font-size:([\d.]+rem);\}", theirs), ["1.4rem", "1.3rem"])
        self.assertEqual(re.findall(r"h1\{font-size:([\d.]+rem)\}", mine), ["1.4rem", "1.3rem"])
        self.assertIn("button.bar-icon{grid-column:1;grid-row:1;justify-self:start;", theirs)
        self.assertIn("width:var(--hit-secondary);height:var(--hit-secondary);padding:0;border:0;border-radius:50%;background:var(--cell);", theirs)
        self.assertIn(".done{grid-column:1;grid-row:1;justify-self:start;", mine)
        self.assertIn("min-height:var(--hit2);", mine)
        self.assertIn(".done.icon{width:var(--hit2);min-width:0;padding:0;border-radius:50%}", mine)

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

    def test_a_page_that_refreshes_also_reloads_from_a_script(self):
        """1.5.3: the owner had to open the page again to see what 「检查更新」 had found. After a button the address
        ends in #update, and a browser may take the refresh tag to such an address as a scroll, not a reload. A
        script reloads half a second after the tag would have; where the tag works, the page is gone by then."""
        import settings_ui as ui
        html = ui.page("t", "<p>x</p>", 2)
        self.assertIn("<meta http-equiv=refresh content=2><script>setTimeout(function(){location.reload()},2500)</script>", html)
        self.assertIn("setTimeout(function(){location.reload()},3500)", ui.page("t", "<p>x</p>", True))
        self.assertNotIn("location.reload", ui.page("t", "<p>x</p>"))
        with patch("settings_page.update.check", side_effect=lambda root: threading.Event().wait(5)):
            self.page.start_check()
        checking = self.page.render("m=")
        self.assertIn("正在检查更新…", checking)
        self.assertIn("location.reload()},2500)", checking)

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
        with patch("settings_page.update.launch", return_value="已开始升级"):
            self.assertEqual(post("/update", action="install"), (303, "/?m=#update"), "at once (1.6.0), back on 更新")
        self.page.pairing.stop = lambda: None
        self.assertEqual(post("/pair", action="cancel"), (303, "/?m="), "the first category needs no fragment")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/?night=0", headers={"Host": f"127.0.0.1:{port}"})
        reply = connection.getresponse(); html = reply.read().decode(); connection.close()
        self.assertEqual(reply.status, 200)
        self.assertIn("<h1>AutoPlay 设置</h1>", html)


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
