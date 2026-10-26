"""HTML for the box settings page, in the visual language of iOS Settings.

People arrive from a phone or the head unit's browser next to CarPlay, so the page borrows what they already
know: large title, inset grouped lists, Bluetooth-style device rows, system colours that follow light/dark.
The one element of its own is the connection chain (Wi-Fi - box - iPhone) at the top. Self-contained: no web
fonts or external files (the car may be offline).
"""
from html import escape

STYLE = """
:root{--bg:#F2F2F7;--cell:#FFFFFF;--sep:rgba(60,60,67,.18);--label:#000;--secondary:rgba(60,60,67,.6);
--tint:#007AFF;--green:#34C759;--orange:#FF9500;--red:#FF3B30;--fill:rgba(120,120,128,.12);--press:#D1D1D6;
color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#000;--cell:#1C1C1E;--sep:rgba(84,84,88,.6);--label:#FFF;
--secondary:rgba(235,235,245,.6);--tint:#0A84FF;--green:#30D158;--orange:#FF9F0A;--red:#FF453A;
--fill:rgba(120,120,128,.24);--press:#3A3A3C}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--label);
font:17px/1.35 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
-webkit-text-size-adjust:100%}
main{max-width:680px;margin:0 auto;padding:max(12px,env(safe-area-inset-top)) 16px 48px}
h1{font-size:34px;line-height:1.2;font-weight:700;letter-spacing:-.02em;margin:12px 4px 4px}
.sub{color:var(--secondary);font-size:15px;margin:0 4px 8px}
.group-title{color:var(--secondary);font-size:13px;margin:24px 16px 6px}
.gap{height:20px}
.foot,.note{color:var(--secondary);font-size:13px;line-height:1.4;margin:6px 16px 0}
.group{background:var(--cell);border-radius:12px;overflow:hidden}
.cell{display:flex;align-items:center;gap:12px;min-height:46px;padding:10px 16px;position:relative;width:100%;
background:none;border:0;color:inherit;font:inherit;text-align:left;text-decoration:none}
.cell+.cell,.cell+details,details+.cell,details+details,form+form>.cell,.cell+form>.cell,form+.cell{border-top:.5px solid var(--sep)}
.group>form+form,.group>form+details,.group>details+form{border-top:.5px solid var(--sep)}
.cell .main{flex:1;min-width:0}
.cell .main b{font-weight:400;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cell .main span{display:block;color:var(--secondary);font-size:13px}
.cell .value{color:var(--secondary);white-space:nowrap}
.cell.on .value{color:var(--green)}
button.cell,a.cell,label.cell,summary.cell{cursor:pointer}
button.cell:active,a.cell:active,label.cell:active,summary.cell:active{background:var(--press)}
.cell.action{color:var(--tint);justify-content:center}
.cell.destructive{color:var(--red);justify-content:center}
.chev{flex:none;display:block}
.chev::after{content:"";display:block;width:8px;height:8px;border:solid var(--secondary);border-width:0 2px 2px 0;transform:rotate(-45deg);margin-right:4px;flex:none}
details[open]>summary .chev::after{transform:rotate(45deg)}
summary{list-style:none} summary::-webkit-details-marker{display:none}
details>.inner{border-top:.5px solid var(--sep);background:var(--bg)}
details>.inner .cell{background:var(--cell)}
.icon{width:22px;height:22px;flex:none;color:var(--secondary)}
input[type=text],input[type=password]{flex:1;min-width:0;border:0;background:none;color:var(--label);font:inherit;padding:0;outline:none}
input::placeholder{color:var(--secondary)}
.btn{display:block;width:100%;min-height:50px;margin:20px 0 0;padding:14px 16px;border:0;border-radius:12px;background:var(--tint);
color:#fff;font:inherit;font-weight:600;text-align:center;text-decoration:none;cursor:pointer;transition:transform .1s ease-out}
.btn:active{transform:scale(.97)}
.btn.plain{background:var(--fill);color:var(--tint)}
.btn.destructive{background:var(--red)}
.btn+form .btn,form+form .btn.plain{margin-top:10px}
:focus-visible{outline:3px solid var(--tint);outline-offset:2px}
.banner{border-radius:12px;padding:12px 16px;margin:12px 0 0;background:var(--cell);font-size:15px}
.banner.ok{box-shadow:inset 4px 0 var(--green)} .banner.bad{box-shadow:inset 4px 0 var(--red)} .banner.wait{box-shadow:inset 4px 0 var(--orange)}
.chain{display:flex;align-items:flex-start;background:var(--cell);border-radius:12px;padding:18px 12px 14px;margin:16px 0 0}
.node{flex:0 0 30%;min-width:0;text-align:center}
.node .glyph{width:52px;height:52px;margin:0 auto 6px;border-radius:50%;display:grid;place-items:center;background:var(--fill);color:var(--secondary)}
.node .glyph svg{width:28px;height:28px}
.node.on .glyph{background:var(--green);color:#fff}
.node.wait .glyph{background:var(--orange);color:#fff}
.node.bad .glyph{background:var(--red);color:#fff}
.node .name{font-size:13px;font-weight:600;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.node .state{font-size:12px;color:var(--secondary)}
.link{flex:1;height:3px;border-radius:2px;margin-top:25px;background:var(--fill)}
.link.on{background:var(--green)}
.link.wait{background:repeating-linear-gradient(90deg,var(--orange) 0 6px,transparent 6px 12px);background-size:12px 3px;animation:flow .9s linear infinite}
@keyframes flow{to{background-position:12px 0}}
@media (prefers-reduced-motion:reduce){.link.wait{animation:none}.btn{transition:none}}
section+ol.steps{margin-top:10px}
ol.steps{margin:0;padding:12px 16px 12px 36px;background:var(--cell);border-radius:12px} ol.steps li{margin:4px 0}
.code{font:600 48px/1.1 -apple-system,"SF Pro Display",system-ui,sans-serif;letter-spacing:.12em;text-align:center;
font-variant-numeric:tabular-nums;padding:20px 0 6px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px} .pair .btn{margin-top:16px}
.back{display:inline-block;color:var(--tint);text-decoration:none;margin:6px 0 0;padding:10px 4px;font-size:17px;min-height:44px}
.back:active{opacity:.5}
.cell a{color:var(--tint);text-decoration:none}
@media (min-width:960px){main.wide{max-width:1100px;display:grid;grid-template-columns:1fr 1fr;column-gap:28px;align-items:start}
main.wide>.span{grid-column:1/-1}}
"""

ICONS = {
    "box": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
           'stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="7.5" rx="2"/>'
           '<path d="M8.5 7.6a5 5 0 0 1 7 0M10.6 9.4a2 2 0 0 1 2.8 0"/><circle cx="8" cy="14.8" r=".9" fill="currentColor"/></svg>',
    "hotspot": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
               'stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="13" r="1.6" fill="currentColor"/>'
               '<path d="M8.6 16.4a4.8 4.8 0 0 1 0-6.8M15.4 9.6a4.8 4.8 0 0 1 0 6.8M5.8 19.2a8.8 8.8 0 0 1 0-12.4'
               'M18.2 6.8a8.8 8.8 0 0 1 0 12.4"/></svg>',
    "phone": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><rect x="7" y="2.8" width="10" height="18.4" rx="2.6"/>'
             '<path d="M10.8 5.2h2.4"/></svg>',
}


def page(title, body, refresh=False, wide=False):
    """refresh: True reloads every 3 s, a number every that many seconds."""
    meta = f'<meta http-equiv=refresh content={3 if refresh is True else refresh}>' if refresh else ''
    return (f'<!doctype html><html lang=zh-CN><head><meta charset=utf-8>'
            f'<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">{meta}'
            f'<title>{escape(title)}</title><style>{STYLE}</style></head>'
            f'<body><main{" class=wide" if wide else ""}>{body}</main></body></html>')


def chain(hotspot, phone, box=("on", "盒子", "运行中")):
    """hotspot/phone/box: (state, name, caption) with state on/wait/off/bad."""
    def node(kind, value):
        state, name, caption = value
        return (f'<div class="node {state}"><div class=glyph>{ICONS[kind]}</div>'
                f'<div class=name>{escape(name)}</div><div class=state>{escape(caption)}</div></div>')
    return (f'<div class="chain span" role=img aria-label="{escape(hotspot[1])}：{escape(hotspot[2])}；'
            f'{escape(box[1])}：{escape(box[2])}；{escape(phone[1])}：{escape(phone[2])}">'
            f'{node("hotspot", hotspot)}<div class="link {hotspot[0]}"></div>'
            f'{node("box", box)}<div class="link {phone[0]}"></div>{node("phone", phone)}</div>')


def banner(text, kind="ok"):
    return f'<p class="banner {kind} span" role=status>{escape(text)}</p>' if text else ""


def flash(message):
    if not message:
        return ""
    if message.startswith("错误："):
        return banner(message.removeprefix("错误："), "bad")
    return banner(message)


def hidden(nonce, **values):
    fields = {"nonce": nonce, **values}
    return "".join(f'<input type=hidden name={k} value="{escape(v)}">' for k, v in fields.items())


def group(title, cells, foot=""):
    head = f'<p class=group-title>{escape(title)}</p>' if title else '<div class=gap></div>'
    tail = f'<p class=foot>{foot}</p>' if foot else ""
    return f'<section>{head}<div class=group>{cells}</div>{tail}</section>'


def phone_rows(devices, active, last, nonce, idle):
    """Bluetooth-style 'My devices': tap a phone to connect it or remove it from the box."""
    if not devices:
        return '<div class=cell><span class=main><span>还没有添加 iPhone</span></span></div>'
    html = ""
    for phone, name in devices.items():
        state = "正在使用" if phone == active else "上次使用" if phone == last else "未连接"
        summary = (f'<summary class="cell{" on" if phone == active else ""}"><span class=main><b>{escape(name)}</b>'
                   f'<span>蓝牙 …{escape(phone[-5:])}</span></span><span class=value>{state}</span><span class=chev></span></summary>')
        actions = ""
        if phone == active:
            actions = '<div class=cell><span class=main><span>正在使用 CarPlay。对方断开 Wi-Fi 后，才能接入其他 iPhone 或删除它。</span></span></div>'
        else:
            form = f'<form method=post action=/pair>{hidden(nonce, phone=phone)}'
            if idle:
                actions += form + '<button class="cell action" name=action value=use>接入 CarPlay</button></form>'
            actions += (form + f'<button class="cell destructive" name=action value=remove '
                        f'onclick="return confirm(\'从盒子上删除「{escape(name)}」？以后要用需要重新配对。\')">删除此 iPhone</button></form>')
        html += f'<details>{summary}<div class=inner>{actions}</div></details>'
    return html


def pairing_panel(pair, nonce, address=""):
    """The add-phone flow as its own screen. Returns (html, refresh), or (None, False) when idle.

    iOS shows an incoming pairing request only while Settings > Bluetooth is open, so the iPhone stays
    there and this page is operated on another screen, normally the head unit's browser.
    """
    phase = pair.get("phase", "closed")
    cancel = (f'<form method=post action=/pair>{hidden(nonce)}'
              '<button class="btn plain" name=action value=cancel>取消</button></form>')
    if phase == "confirm":
        return (f'<p class=group-title>配对码</p><div class=group><p class=code>{escape(pair.get("passkey", ""))}</p>'
                f'<p class=foot style="margin:0 16px 16px;text-align:center">「{escape(pair.get("name", ""))}」的蓝牙页面会弹出同样的数字。'
                '两边一致时，手机上点「配对」，这里点「一致」。</p></div>'
                f'<form method=post action=/pair>{hidden(nonce, request_id=pair.get("request_id", ""))}<div class=pair>'
                '<button class="btn plain" name=action value=no>不一致</button>'
                '<button class=btn name=action value=yes>一致</button></div></form>', True)
    if phase == "waiting":
        found = "".join(
            f'<form method=post action=/pair>{hidden(nonce, phone=f["address"])}'
            f'<button class=cell name=action value=pick>{ICONS["phone"].replace("<svg ", "<svg class=icon ", 1)}'
            f'<span class=main><b>{escape(f["name"])}</b><span>蓝牙 …{escape(f["address"][-5:])}</span></span>'
            '<span class=value>配对</span><span class=chev></span></button></form>'
            for f in pair.get("found", []))
        found = found or '<div class=cell><span class=main><span>正在寻找附近的 iPhone…</span></span></div>'
        error = banner(pair["error"], "bad") if pair.get("error") else ""
        return ('<p class=group-title>添加 iPhone</p><ol class=steps>'
                '<li>在要添加的 iPhone 上打开「设置 → 蓝牙」，<b>一直停在这一页</b>，配对请求只会在那里弹出。</li>'
                '<li>在这一页点它的名字。</li><li>手机弹出配对请求后，核对两边的六位数字。</li></ol>'
                f'{error}{group("附近的 iPhone", found)}{cancel}', True)
    if phase == "pairing":
        return (group("添加 iPhone", f'<div class=cell><span class=main><b>正在连接「{escape(pair.get("name", ""))}」</b>'
                      '<span>请看 iPhone 蓝牙页面上的配对请求。</span></span></div>') + cancel, True)
    if phase in ("starting", "finishing"):
        return group("添加 iPhone", '<div class=cell><span class=main><span>请稍候…</span></span></div>'), True
    return None, False


def other_screen(address):
    """Where to operate pairing: the head unit or another device, since the iPhone must stay on its Bluetooth page
    (settings_onboarding_audit S5)."""
    if not address:
        return ""
    return (f'<p class=group-title>在车机或另一台设备上操作</p><div class=group><p class=code style="font-size:28px;letter-spacing:0">'
            f'{escape(address)}</p><p class=foot style="margin:0 16px 16px;text-align:center">'
            '添加 iPhone 时，那部 iPhone 要一直停在「设置 → 蓝牙」，所以请在车机浏览器或另一台手机输入上面的地址，在那里完成这一步。</p></div>')
