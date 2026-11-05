"""HTML for the box settings page, in the visual language of iOS Settings at the CarPlay page's type size.

People arrive from the Tesla's browser (773x601 or 1256x706 CSS px at DPR 1.53) or from a phone, so the page
borrows what they already know: large title, inset grouped lists, Bluetooth-style device rows, system colours
that follow light/dark. Since 1.2.0 its type and touch sizes are the CarPlay page's (0.1.2): one rem is
clamp(20px, 2.78vmin, 24px), labels 1.2rem, hints 1rem, targets >= 3.2rem; phones keep iOS's 17 px. The one
element of its own is the connection chain (Wi-Fi - box - iPhone) at the top. Self-contained: no web fonts or
external files (the car may be offline).
"""
import re
from html import escape

STYLE = """
/* Tokens shared with the CarPlay page (receiver/web/src/style.css, 0.1.2): one rem = clamp(20px, 2.78vmin, 24px), so
   labels are 24 px at 1256x706 CSS (the Tesla's borderless window), 28.8 px at 1920x1200; touch targets >= 3.2rem
   (64 px); phones (<= 480 px) fall back to 17 px like iOS Settings. Separators 1 px: .5 px vanished at DPR 1.53. */
:root{--bg:#F2F2F7;--cell:#FFFFFF;--sep:rgba(60,60,67,.22);--label:#000;--secondary:rgba(60,60,67,.65);
--tint:#007AFF;--green:#34C759;--orange:#FF9500;--red:#FF3B30;--fill:rgba(120,120,128,.12);--press:#D1D1D6;
--radius:1rem;--hit:3.2rem;--pad-x:1.2rem;color-scheme:light dark;font-size:clamp(20px,2.78vmin,24px)}
@media (prefers-color-scheme:dark){:root{--bg:#000;--cell:#1C1C1E;--sep:rgba(84,84,88,.65);--label:#FFF;
--secondary:rgba(235,235,245,.65);--tint:#0A84FF;--green:#30D158;--orange:#FF9F0A;--red:#FF453A;
--fill:rgba(120,120,128,.24);--press:#3A3A3C}}
@media (max-width:480px){:root{font-size:17px;--radius:12px;--hit:46px;--pad-x:16px}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--label);
font:1rem/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
-webkit-text-size-adjust:100%}
main{max-width:56rem;margin:0 auto;padding:max(.6rem,env(safe-area-inset-top)) max(16px,1rem) 3rem}
h1{font-size:1.6rem;line-height:1.2;font-weight:700;letter-spacing:normal;margin:.6rem .2rem .4rem}
.sub{color:var(--secondary);font-size:1rem;margin:0 .2rem .4rem}
.group-title{color:var(--secondary);font-size:1rem;font-weight:500;margin:1.4rem var(--pad-x) .35rem}
.gap{height:1.2rem}
.foot,.note{color:var(--secondary);font-size:1rem;line-height:1.45;margin:.4rem var(--pad-x) 0}
.group{background:var(--cell);border-radius:var(--radius);overflow:hidden}
.cell{display:flex;align-items:center;gap:.8rem;min-height:var(--hit);padding:.7rem var(--pad-x);position:relative;width:100%;
background:none;border:0;color:inherit;font:inherit;font-size:1.2rem;line-height:1.3;text-align:left;text-decoration:none}
.cell+.cell,.cell+details,details+.cell,details+details,form+form>.cell,.cell+form>.cell,form+.cell{border-top:1px solid var(--sep)}
/* form+form draws its line on the cell inside: a line on the form as well doubled it (1.4.1, the two update buttons). */
.group>form+details,.group>details+form{border-top:1px solid var(--sep)}
.cell .main{flex:1;min-width:0}
/* Labels wrap instead of losing their end (1.4.1): at phone width the Wi-Fi row and the addresses were cut short with
   an ellipsis; an address has to be read whole. The value beside a label is what gives way. */
.cell .main b{font-weight:500;display:block;overflow-wrap:anywhere}
.cell .main span{display:block;color:var(--secondary);font-size:1rem;line-height:1.45;margin-top:.2rem;white-space:normal}
.cell .main span.clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.cell .main a.more{display:inline-block;padding:.2rem 0;font-size:1rem}
.cell .value{color:var(--secondary);font-size:1.1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:45%}
.cell.on .value{color:var(--green)}
button.cell,a.cell,label.cell,summary.cell{cursor:pointer}
button.cell:active,a.cell:active,label.cell:active,summary.cell:active{background:var(--press)}
.cell.action{color:var(--tint);justify-content:center;font-weight:600}
.cell.destructive{color:var(--red);justify-content:center;font-weight:600}
.chev{flex:none;display:block}
.chev::after{content:"";display:block;width:.6rem;height:.6rem;border:solid var(--secondary);border-width:0 .15rem .15rem 0;transform:rotate(-45deg);margin-right:.2rem;flex:none}
details[open]>summary .chev::after{transform:rotate(45deg)}
summary{list-style:none} summary::-webkit-details-marker{display:none}
details>.inner{border-top:1px solid var(--sep);background:var(--bg)}
details>.inner .cell{background:var(--cell)}
.icon{width:1.3rem;height:1.3rem;flex:none;color:var(--secondary)}
input[type=text],input[type=password]{flex:1;min-width:0;border:0;background:none;color:var(--label);font:inherit;font-size:1.1rem;padding:0;outline:none;min-height:2rem}
input::placeholder{color:var(--secondary)}
.btn{display:block;width:100%;min-height:var(--hit);margin:1rem 0 0;padding:.8rem var(--pad-x);border:0;border-radius:var(--radius);background:var(--tint);
color:#fff;font:inherit;font-size:1.2rem;font-weight:600;line-height:1.3;text-align:center;text-decoration:none;cursor:pointer;transition:transform .1s ease-out}
.btn:active{transform:scale(.97)}
.btn.plain{background:var(--fill);color:var(--tint)}
.btn.destructive{background:var(--red)}
.btn+form .btn,form+form .btn.plain{margin-top:.6rem}
:focus-visible{outline:3px solid var(--tint);outline-offset:2px}
/* Alerts (1.4.1): only states the owner can act on, as an inset card with a round symbol like an iOS alert row;
   what an action did is said where it happened (the group's footer), not here. */
.banner{display:flex;align-items:flex-start;gap:.8rem;border-radius:var(--radius);padding:.8rem var(--pad-x);margin:.6rem 0 0;
background:var(--cell);font-size:1.1rem;line-height:1.4}
.banner::before{content:"!";flex:none;width:1.5rem;height:1.5rem;margin-top:.05rem;border-radius:50%;display:grid;place-items:center;
background:var(--orange);color:#fff;font-size:1rem;font-weight:700;line-height:1}
.banner.bad::before{background:var(--red)} .banner.ok::before{content:"✓";background:var(--green)}
/* Row icons as in iOS Settings and the CarPlay page's settings panel (receiver/web/src/style.css). */
.tile{width:1.6rem;height:1.6rem;flex:none;border-radius:.4rem;display:grid;place-items:center;color:#fff;background:#8E8E93}
.tile svg{width:1.05rem;height:1.05rem}
.tile.blue{background:var(--tint)} .tile.green{background:var(--green)} .tile.orange{background:var(--orange)}
.tile.red{background:var(--red)} .tile.gray{background:#8E8E93} .tile.indigo{background:#5E5CE6}
.spin{width:1.2rem;height:1.2rem;flex:none;border-radius:50%;border:.16rem solid var(--secondary);border-right-color:transparent;
animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.cell[aria-busy=true] .main b{color:var(--secondary)}
.chain{display:flex;align-items:flex-start;background:var(--cell);border-radius:var(--radius);padding:1rem .6rem .8rem;margin:.8rem 0 0}
.node{flex:0 0 30%;min-width:0;text-align:center}
.node .glyph{width:3.2rem;height:3.2rem;margin:0 auto .4rem;border-radius:50%;display:grid;place-items:center;background:var(--fill);color:var(--secondary)}
.node .glyph svg{width:1.8rem;height:1.8rem}
.node.on .glyph{background:var(--green);color:#fff}
.node.wait .glyph{background:var(--orange);color:#fff}
.node.bad .glyph{background:var(--red);color:#fff}
.node .name{font-size:1.1rem;font-weight:600;line-height:1.3;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.node .state{font-size:1rem;color:var(--secondary)}
.link{flex:1;height:.2rem;border-radius:.1rem;margin-top:1.5rem;background:var(--fill)}
.link.on{background:var(--green)}
.link.wait{background:repeating-linear-gradient(90deg,var(--orange) 0 .4rem,transparent .4rem .8rem);background-size:.8rem .2rem;animation:flow .9s linear infinite}
@keyframes flow{to{background-position:.8rem 0}}
@media (prefers-reduced-motion:reduce){.link.wait,.spin{animation:none}.btn{transition:none}}
section+ol.steps{margin-top:.6rem}
ol.steps{margin:0;padding:.8rem var(--pad-x) .8rem 2.4rem;background:var(--cell);border-radius:var(--radius);font-size:1.1rem} ol.steps li{margin:.3rem 0}
.code{font:600 3.2rem/1.1 -apple-system,"SF Pro Display",system-ui,sans-serif;letter-spacing:.15em;text-align:center;
font-variant-numeric:tabular-nums;padding:.8rem var(--pad-x) .6rem;margin:0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:.6rem} .pair .btn{margin-top:.8rem;display:flex;align-items:center;justify-content:center}
.back{display:inline-flex;align-items:center;color:var(--tint);text-decoration:none;margin:.3rem 0 0;padding:.5rem .2rem;font-size:1.1rem;min-height:var(--hit)}
.back:active{opacity:.5}
.cell a{color:var(--tint);text-decoration:none}
/* Phone sizes for the chain and values come last: placed with the 17 px root above, the rules they override (same
   specificity, later in the sheet) won, so a six-character box state wrapped its last character (1.4.1). */
@media (max-width:480px){.cell .value{max-width:40%} .node .glyph{width:2.6rem;height:2.6rem} .node .glyph svg{width:1.5rem;height:1.5rem}
.node .name{font-size:1rem} .node .state{font-size:.85rem;line-height:1.35} .link{margin-top:1.2rem}}
/* Two columns only where both fit at this type size: the Tesla's borderless window (1256 CSS px) and wider. */
/* Capped at 64rem (1536 px at 1920 wide) so the rows stay rows on a desktop monitor instead of two runways. */
@media (min-width:1100px){main.wide{max-width:64rem;display:grid;grid-template-columns:1fr 1fr;column-gap:1.6rem;align-items:start}
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


# A row unfolded (details) near the bottom of a short window would open below the fold: scroll it into view, whole when
# it fits, else from its title. Progressive: the page works without it. toggle does not bubble, hence the capture.
UNFOLD = ('<script>document.addEventListener("toggle",function(e){var d=e.target;if(!d.open||d.tagName!=="DETAILS")return;'
          'var r=d.getBoundingClientRect();if(r.bottom<=innerHeight)return;'
          'd.scrollIntoView({block:r.height>innerHeight?"start":"end",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"})},true)</script>')


# "Wi-Fi" broke at its hyphen ("Wi-" / "Fi") in narrow windows (1.4.1): in the page's text, never in attribute values
# (form fields keep what they hold), it gets a non-breaking hyphen.
_TEXT = re.compile(r">([^<]+)<")


def keep_words(html):
    return _TEXT.sub(lambda m: ">" + m.group(1).replace("Wi-Fi", "Wi\u2011Fi") + "<", html)


def url(address):
    """An address breaks before its port, not mid-number, when it has to wrap."""
    return re.sub(r"(:\d+/?)$", r"<wbr>\1", escape(address))


def page(title, body, refresh=False, wide=False):
    """refresh: True reloads every 3 s, a number every that many seconds."""
    body = keep_words(body)
    meta = f'<meta http-equiv=refresh content={3 if refresh is True else refresh}>' if refresh else ''
    return (f'<!doctype html><html lang=zh-CN><head><meta charset=utf-8>'
            f'<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">{meta}'
            f'<title>{escape(title)}</title><style>{STYLE}</style></head>'
            f'<body><main{" class=wide" if wide else ""}>{body}</main>{UNFOLD}</body></html>')


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


# Row icons (1.4.1): white strokes on a coloured rounded tile.
TILES = {
    "screen": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16.5V20"/>',
    "wifi": '<path d="M2.8 9.2a13.5 13.5 0 0 1 18.4 0M5.8 12.4a9.2 9.2 0 0 1 12.4 0M8.8 15.6a4.8 4.8 0 0 1 6.4 0"/>'
            '<circle cx="12" cy="18.8" r="1.1" fill="currentColor" stroke="none"/>',
    "settings": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "phone": '<rect x="7" y="2.8" width="10" height="18.4" rx="2.6"/><path d="M10.8 5.2h2.4"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.9 5.2 3.9 8.5s-1.3 6.1-3.9 8.5'
             'c-2.6-2.4-3.9-5.2-3.9-8.5S9.4 5.9 12 3.5z"/>',
    "box": '<rect x="4" y="11" width="16" height="7.5" rx="2"/><path d="M8.5 7.6a5 5 0 0 1 7 0M10.6 9.4a2 2 0 0 1 2.8 0"/>',
    "download": '<path d="M12 4v10.5M7.5 10 12 14.5 16.5 10M5 19.5h14"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 6.5v7M12 17.3v.2"/>',
    "doc": '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M9.5 12h6M9.5 15.5h6"/>',
}


def tile(color, name):
    return (f'<span class="tile {color}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{TILES[name]}</svg></span>')


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
        return f'<div class=cell>{tile("gray", "phone")}<span class=main><span>还没有添加 iPhone</span></span></div>'
    html = ""
    for phone, name in devices.items():
        state = "正在使用" if phone == active else "上次使用" if phone == last else "未连接"
        summary = (f'<summary class="cell{" on" if phone == active else ""}">{tile("green" if phone == active else "gray", "phone")}'
                   f'<span class=main><b>{escape(name)}</b>'
                   f'<span>蓝牙 …{escape(phone[-5:])}</span></span><span class=value>{state}</span><span class=chev></span></summary>')
        actions = ""
        if phone == active:
            actions = '<div class=cell><span class=main><span>正在使用。它断开后，才能接入别的 iPhone 或删除它。</span></span></div>'
        else:
            form = f'<form method=post action=/pair>{hidden(nonce, phone=phone)}'
            if idle:
                actions += form + '<button class="cell action" name=action value=use>接入 CarPlay</button></form>'
            # No confirm() here: the question is the next screen (settings_page.confirm_screen).
            actions += form + '<button class="cell destructive" name=action value=remove>删除此 iPhone…</button></form>'
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
        # The code and its two buttons first, within one Tesla window (773x601 CSS px); the explanation under them.
        return (f'<p class=group-title>配对码</p><div class=group><p class=code>{escape(pair.get("passkey", ""))}</p></div>'
                f'<form method=post action=/pair>{hidden(nonce, request_id=pair.get("request_id", ""))}<div class=pair>'
                '<button class="btn plain" name=action value=no>不一致</button>'
                '<button class=btn name=action value=yes>一致</button></div></form>'
                f'<p class=foot style="text-align:center">和「{escape(pair.get("name", ""))}」上的数字一致时，'
                '在 iPhone 上点「配对」，这里点「一致」。</p>', True)
    if phase == "waiting":
        found = "".join(
            f'<form method=post action=/pair>{hidden(nonce, phone=f["address"])}'
            f'<button class=cell name=action value=pick>{ICONS["phone"].replace("<svg ", "<svg class=icon ", 1)}'
            f'<span class=main><b>{escape(f["name"])}</b><span>蓝牙 …{escape(f["address"][-5:])}</span></span>'
            '<span class=value>配对</span><span class=chev></span></button></form>'
            for f in pair.get("found", []))
        found = found or '<div class=cell><span class=main><span>正在寻找附近的 iPhone…</span></span></div>'
        error = banner(pair["error"], "bad") if pair.get("error") else ""
        # The list to tap first, the three steps under it: in the Tesla's windowed browser the list sat below the fold.
        return (f'{error}{group("附近的 iPhone", found)}{cancel}'
                '<p class=group-title>怎么做</p><ol class=steps>'
                '<li>在 iPhone 上打开「设置 → 蓝牙」，<b>停在这一页</b>。</li>'
                '<li>在上面的列表里点它的名字。</li><li>核对两边的六位数字。</li></ol>', True)
    if phase == "pairing":
        return (group("添加 iPhone", f'<div class=cell><span class=main><b>正在连接「{escape(pair.get("name", ""))}」</b>'
                      '<span>请留意 iPhone 上的配对请求。</span></span></div>') + cancel, True)
    if phase in ("starting", "finishing"):
        return group("添加 iPhone", '<div class=cell><span class=main><span>请稍候…</span></span></div>'), True
    return None, False


def other_screen(address):
    """Where to operate pairing: the head unit or another device, since the iPhone must stay on its Bluetooth page
    (settings_onboarding_audit S5)."""
    if not address:
        return ""
    return (f'<p class=group-title>在车机或另一台设备上操作</p><div class=group><p class=code style="font-size:1.6rem;letter-spacing:0;overflow-wrap:anywhere">'
            f'{url(address)}</p><p class=foot style="margin:0 var(--pad-x) 1rem;text-align:center">'
            '添加时 iPhone 要停在「设置 → 蓝牙」，所以请在车机或另一台设备上打开这个地址。</p></div>')
