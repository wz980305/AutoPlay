"""HTML for the box page, laid out and drawn as the CarPlay page's "AutoPlay 设置" panel (1.5.0).

People arrive from that panel (连接 → 打开盒子网页) in the Tesla's browser (773x601 or 1256x706 CSS px at DPR 1.53), or
from a phone. So the page is the panel's twin: a title bar with one button (back to the CarPlay picture, where the
panel has 完成), the categories on the left with the chosen one filled in the tint, one column of grouped rows on
the right; under 760 px the categories become a row of buttons above it, as the panel does. Rows are the panel's
(receiver/web/src/style.css): a white glyph on a coloured tile, the label, the value in grey, a chevron; no line of
explanation under a row or a group unless it says what is happening right now. Sizes are the panel's too: one rem is
clamp(20px, 2.78vmin, 24px), rows 3.6rem, tiles 2rem; phones keep iOS's 17 px.

The panel is always dark; this page has both sets of colours and shows the one CarPlay shows: the CarPlay page links
here with ?night=1 or 0 (the day/night it asks the iPhone for), a browser that came another way follows its own
dark/light setting. The one element of its own is the connection chain (Wi-Fi - box - iPhone). Self-contained: no
web fonts or external files (the car may be offline).
"""
import re
from html import escape

# The two sets of colours. Dark is the CarPlay page's (style.css :root); light is iOS's light set of the same roles.
DARK = ("--bg:#000;--cell:#1C1C1E;--press:#3A3A3C;--sep:rgba(84,84,88,.6);--label:#FFF;--secondary:rgba(235,235,245,.72);"
        "--tint:#0A84FF;--btn:#0066D6;--green:#30D158;--orange:#FF9F0A;--red:#FF453A;--fill:rgba(120,120,128,.24);"
        "--chev:rgba(235,235,245,.55);color-scheme:dark")
LIGHT = ("--bg:#F2F2F7;--cell:#FFF;--press:#D1D1D6;--sep:rgba(60,60,67,.24);--label:#000;--secondary:rgba(60,60,67,.7);"
         "--tint:#007AFF;--btn:#007AFF;--green:#34C759;--orange:#FF9500;--red:#FF3B30;--fill:rgba(120,120,128,.14);"
         "--chev:rgba(60,60,67,.45);color-scheme:light")

STYLE = """
/* Which colours: the theme the CarPlay page handed over (data-theme, set by THEME below) wins; without one the
   browser's own preference decides. */
:root{@LIGHT@;--radius:.75rem;--hit:3.6rem;--hit2:3.2rem;--s1:.5rem;--s2:.75rem;--s3:1rem;--s4:1.5rem;--s5:2rem;--bar:4.75rem;
font-size:clamp(20px,2.78vmin,24px)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){@DARK@}}
:root[data-theme=dark]{@DARK@}
@media (max-width:480px){:root{font-size:17px;--hit:3rem;--hit2:2.7rem;--bar:4.2rem}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--label);
font:1.2rem/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
-webkit-text-size-adjust:100%}
[hidden]{display:none!important}
:focus-visible{outline:3px solid var(--tint);outline-offset:2px}

/* Title bar: the panel's header. It stays while the page scrolls. */
header{position:-webkit-sticky;position:sticky;top:0;z-index:3;background:var(--bg);border-bottom:1px solid var(--sep)}
header>div{display:flex;align-items:center;justify-content:space-between;gap:var(--s3);max-width:1440px;margin:0 auto;min-height:var(--bar);
padding:max(var(--s2),env(safe-area-inset-top)) max(var(--s4),env(safe-area-inset-right)) var(--s2) max(var(--s4),env(safe-area-inset-left))}
h1{font-size:1.6rem;line-height:1.3;font-weight:600;letter-spacing:normal;margin:0;min-width:0}
.done{flex:none;display:inline-flex;align-items:center;justify-content:center;min-height:var(--hit2);min-width:var(--hit);padding:var(--s1) var(--s3);
border-radius:var(--radius);background:var(--cell);color:var(--label);font-weight:600;text-decoration:none;white-space:nowrap}
.done:active{opacity:.5}

/* Alerts: only states the owner can act on, and errors, under the title bar on every category (STATUS-MODEL.md). */
.alerts{max-width:1440px;margin:0 auto;padding:var(--s3) max(var(--s4),env(safe-area-inset-right)) 0 max(var(--s4),env(safe-area-inset-left))}
.banner{display:flex;align-items:flex-start;gap:var(--s2);border-radius:var(--radius);padding:var(--s2) var(--s3);margin:0;background:var(--cell);line-height:1.4}
.banner+.banner{margin-top:var(--s1)}
.banner::before{content:"!";flex:none;width:1.5rem;height:1.5rem;margin-top:.1rem;border-radius:50%;display:grid;place-items:center;
background:var(--orange);color:#fff;font-size:1rem;font-weight:700;line-height:1}
.banner.bad::before{background:var(--red)} .banner.ok::before{content:"\\2713";background:var(--green)}

/* Categories and their pages. The pages are all in the document; the address's fragment picks one (:target), so a
   page that reloads itself (a check for updates) and a redirect after a button stay where they were, without a
   script. The first category's page comes last in the document so that "no fragment" can show it: a page that is the
   target hides it. The list of categories follows the pages for the same reason and is placed by the grid. */
.layout{display:grid;grid-template-columns:11rem minmax(0,1fr);column-gap:var(--s4);align-items:start;max-width:1440px;margin:0 auto;
padding:var(--s3) max(var(--s4),env(safe-area-inset-right)) max(var(--s4),env(safe-area-inset-bottom)) max(var(--s4),env(safe-area-inset-left))}
.nav{grid-column:1;grid-row:1;display:flex;flex-direction:column;gap:var(--s2);padding-top:.25rem;position:-webkit-sticky;position:sticky;top:calc(var(--bar) + var(--s3))}
.nav a{display:flex;align-items:center;justify-content:space-between;gap:var(--s1);min-height:var(--hit);border-radius:var(--radius);padding:var(--s2) var(--s3);
font-weight:500;background:var(--cell);color:var(--label);text-decoration:none}
.nav a:active{background:var(--press)}
.nav i{flex:none;width:.6rem;height:.6rem;border-radius:50%;background:var(--red)}
.pane{grid-column:2;grid-row:1;min-width:0;display:none;scroll-margin-top:100vh}
.pane.first,.pane:target{display:block}
.pane:target~.pane.first{display:none}
.nav a.first{background:var(--tint);color:#fff}
.pane:target~.nav a.first{background:var(--cell);color:var(--label)}
#iphone:target~.nav a.first,#net:target~.nav a[href="#net"],#update:target~.nav a[href="#update"],#more:target~.nav a[href="#more"]{background:var(--tint);color:#fff}
.pane>.group-title:first-child{margin-top:.25rem}
.pane>.chain:first-child{margin-top:.25rem}

/* Inset grouped list, as the panel's. Separators 1 px: .5 px vanished on the light page at DPR 1.53. */
.group{background:var(--cell);border-radius:var(--radius);overflow:hidden}
.group-title{color:var(--secondary);font-size:1rem;font-weight:500;margin:var(--s4) var(--s3) var(--s1)}
.foot{color:var(--secondary);font-size:1rem;line-height:1.45;margin:var(--s1) var(--s3) 0}
.cell{display:flex;align-items:center;gap:var(--s2);width:100%;min-height:var(--hit);padding:var(--s2) var(--s3);position:relative;
background:none;border:0;border-radius:0;color:inherit;font:inherit;text-align:left;text-decoration:none}
/* After .cell, whose border:0 has the same weight: one line between a group's rows, whatever they are (a row, a form
   around a button, a row that unfolds). */
.group>*+*,details>.inner,details>.inner>*+*{border-top:1px solid var(--sep)}
.cell .main{flex:1;min-width:0}
/* A label wraps instead of losing its end (an address has to be read whole); the value beside it is what gives way. */
.cell .main b{font-weight:500;display:block;overflow-wrap:anywhere}
.cell .main span{display:block;color:var(--secondary);font-size:1rem;line-height:1.45;margin-top:.25rem;white-space:normal}
.cell .main span.clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.cell .main a.more{display:inline-block;padding:.2rem 0;font-size:1rem}
.cell.empty .main b{color:var(--secondary);font-weight:400}
/* A row that carries a paragraph (an update's notes): its tile stays with the first line. */
.cell.tall{align-items:flex-start} .cell.tall .tile{margin-top:.1rem}
.cell .value{color:var(--secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;max-width:55%}
.cell.on .value{color:var(--green)}
button.cell,a.cell,label.cell,summary.cell{cursor:pointer}
button.cell:active,a.cell:active,label.cell:active,summary.cell:active{background:var(--press)}
.cell.action{color:var(--tint);justify-content:center;font-weight:500}
.cell.destructive{color:var(--red);justify-content:center;font-weight:500}
.cell a{color:var(--tint);text-decoration:none}
.chev{flex:none;display:block}
.chev::after{content:"";display:block;width:.5rem;height:.5rem;margin-right:.25rem;border:solid var(--chev);border-width:0 2px 2px 0;transform:rotate(-45deg)}
details[open]>summary .chev::after{transform:rotate(45deg)}
summary{list-style:none} summary::-webkit-details-marker{display:none}
.tile{width:2rem;height:2rem;flex:none;border-radius:.45rem;display:grid;place-items:center;color:#fff;background:#8E8E93}
.tile svg{width:1.25rem;height:1.25rem}
.tile.blue{background:var(--tint)} .tile.green{background:var(--green)} .tile.orange{background:var(--orange)}
.tile.red{background:var(--red)} .tile.gray{background:#8E8E93} .tile.indigo{background:#5E5CE6}
.spin{width:1.4rem;height:1.4rem;margin:0 .3rem;flex:none;border-radius:50%;border:3px solid var(--fill);border-top-color:var(--label);animation:spin .9s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.cell[aria-busy=true] .main b{color:var(--secondary)}
/* A field in a row keeps to the right and leaves the line to its label. */
input[type=text],input[type=password]{flex:0 1 8rem;min-width:5rem;border:0;background:none;color:var(--label);font:inherit;padding:0;outline:none;min-height:2rem;text-align:right}
input::placeholder{color:var(--secondary)}

/* The connection chain: three stations on one track. A station's colour is its state; a stretch of track is green
   when what it joins is up, moving dashes while it is being set up. */
.chain{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));position:relative;background:var(--cell);border-radius:var(--radius);padding:var(--s3) 0 var(--s2)}
.node{min-width:0;padding:0 .25rem;text-align:center}
.node .glyph{width:2.8rem;height:2.8rem;margin:0 auto .4rem;border-radius:50%;display:grid;place-items:center;background:var(--fill);color:var(--secondary)}
.node .glyph svg{width:1.6rem;height:1.6rem}
.node.on .glyph{background:var(--green);color:#fff}
.node.wait .glyph{background:var(--orange);color:#fff}
.node.bad .glyph{background:var(--red);color:#fff}
.node .name{font-size:1.1rem;font-weight:500;line-height:1.3;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.node .state{font-size:1rem;color:var(--secondary)}
.link{position:absolute;top:calc(var(--s3) + 1.3rem);height:.2rem;border-radius:.1rem;background:var(--fill)}
.link.a{left:calc(16.667% + 1.9rem);right:calc(50% + 1.9rem)} .link.b{left:calc(50% + 1.9rem);right:calc(16.667% + 1.9rem)}
.link.on{background:var(--green)}
.link.wait{background:repeating-linear-gradient(90deg,var(--orange) 0 .4rem,transparent .4rem .8rem);background-size:.8rem .2rem;animation:flow .9s linear infinite}
@keyframes flow{to{background-position:.8rem 0}}

/* A screen that is one question or one task (adding an iPhone, a confirmation, the reset): a single column. */
.flow{max-width:44rem;margin:0 auto;padding:var(--s3) max(var(--s4),env(safe-area-inset-right)) max(var(--s5),env(safe-area-inset-bottom)) max(var(--s4),env(safe-area-inset-left))}
.flow>.group-title:first-child,.flow>section:first-child>.group-title{margin-top:var(--s2)}
.flow>.banner{margin-bottom:var(--s2)}
.sub{color:var(--secondary);font-size:1rem;margin:var(--s2) var(--s3) 0}
.btn{display:block;width:100%;min-height:var(--hit);margin:var(--s3) 0 0;padding:var(--s2) var(--s3);border:0;border-radius:var(--radius);background:var(--btn);
color:#fff;font:inherit;font-weight:600;line-height:1.3;text-align:center;text-decoration:none;cursor:pointer;transition:transform .1s ease-out}
.btn:active{transform:scale(.97)}
.btn.plain{background:var(--fill);color:var(--tint);font-weight:500}
.btn.destructive{background:var(--red)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:var(--s2)} .pair .btn{display:flex;align-items:center;justify-content:center}
ol.steps{margin:0;padding:var(--s2) var(--s3) var(--s2) 2.6rem;background:var(--cell);border-radius:var(--radius)} ol.steps li{margin:.3rem 0}
.code{font:600 3.2rem/1.1 -apple-system,"SF Pro Display",system-ui,sans-serif;letter-spacing:.15em;text-align:center;
font-variant-numeric:tabular-nums;padding:var(--s3) var(--s3) var(--s2);margin:0}

/* Under 760 px, as the panel: the categories in a row above the page. Phone sizes come last, after the rules they
   override (same specificity, later in the sheet). */
@media (max-width:760px){header>div{padding-left:var(--s3);padding-right:var(--s3)} h1{font-size:1.4rem}
.alerts{padding:var(--s2) var(--s3) 0}
.layout{grid-template-columns:minmax(0,1fr);row-gap:var(--s2);padding:var(--s2) var(--s3) var(--s5)}
.nav{position:static;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--s1);padding:0}
.nav a{min-width:0;min-height:var(--hit2);padding:var(--s1);justify-content:center;font-size:1rem;text-align:center}
.pane{grid-column:1;grid-row:2} .pane>.group-title:first-child{margin-top:var(--s2)} .pane>.chain:first-child{margin-top:0}
.flow{padding:var(--s2) var(--s3) var(--s5)}}
@media (max-width:480px){h1{font-size:1.3rem} .tile{width:1.75rem;height:1.75rem} .tile svg{width:1.1rem;height:1.1rem}
.node{padding:0 .15rem} .node .glyph{width:2.6rem;height:2.6rem} .node .glyph svg{width:1.5rem;height:1.5rem} .node .name{font-size:1rem} .node .state{font-size:.85rem;line-height:1.35}
.link{top:calc(var(--s3) + 1.2rem)} .link.a{left:calc(16.667% + 1.7rem);right:calc(50% + 1.7rem)} .link.b{left:calc(50% + 1.7rem);right:calc(16.667% + 1.7rem)}
.code{font-size:2.6rem}
label.cell{flex-direction:column;align-items:stretch;gap:.5rem} label.cell input{flex:none;text-align:left;padding:.5rem .75rem;border-radius:.5rem;background:var(--fill)}}
/* A window too low to hold the bar and the four categories at once (a phone on its side): nothing stays put, the
   page scrolls as a whole. The Tesla's lowest window is 560 px. */
@media (max-height:479px){header,.nav{position:static}}
@media (prefers-reduced-motion:reduce){.link.wait,.spin{animation:none}.btn{transition:none}}
"""
# What a page carries: the sheet without its comments, which are for whoever reads this file (they were a seventh of
# every page, and a test could "find" a sentence that only a comment said).
CSS = re.sub(r"\n\s*\n+", "\n", re.sub(r"/\*.*?\*/", "", STYLE.replace("@LIGHT@", LIGHT).replace("@DARK@", DARK), flags=re.S))

# Day or night as CarPlay has it (1.5.0). The CarPlay page links here with ?night=1 or 0: what its 夜间模式 asks the
# iPhone for at that moment. This page takes those colours, keeps them for the visit (the tab's session storage: a
# button's redirect and a page that reloads itself carry no query) and drops the query from the address, so a
# bookmark or a reload does not pin yesterday's answer. After an hour without a new answer, or with none at all (a
# phone that opened the page itself), the browser's own dark/light setting decides, as the style sheet has it. In the
# head, before anything is drawn.
THEME = ('(function(){var d=document.documentElement,n=Date.now(),m=/[?&]night=([01])(?=&|$)/.exec(location.search),v=m&&m[1]+n;'
         'try{if(m){sessionStorage.setItem("autoplay-night",v);history.replaceState(null,"",location.pathname+'
         'location.search.replace(/([?&])night=[01](&|$)/,function(a,b,c){return c?b:""})+location.hash)}'
         'v=sessionStorage.getItem("autoplay-night")}catch(e){}'
         'if(v&&n-v.slice(1)<36e5)d.setAttribute("data-theme",v.charAt(0)==="1"?"dark":"light")})()')

# Two conveniences; the page works without them. A row unfolded (details) near the bottom of a short window would open
# below the fold: scroll it into view, whole when it fits, else from its title (toggle does not bubble, hence the
# capture). And a category is chosen without adding to the browser's history, so "back" leaves the page instead of
# walking through the categories looked at; the chosen one is also marked for a screen reader.
SCRIPT = ('<script>(function(){document.addEventListener("toggle",function(e){var d=e.target;if(!d.open||d.tagName!=="DETAILS")return;'
          'var r=d.getBoundingClientRect();if(r.bottom<=innerHeight)return;'
          'd.scrollIntoView({block:r.height>innerHeight?"start":"end",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"})},true);'
          'var nav=document.querySelector(".nav");if(!nav)return;var links=nav.querySelectorAll("a");'
          'function mark(){var h=location.hash,on=nav.querySelector(\'a[href="\'+h+\'"]\')||links[0];'
          'for(var i=0;i<links.length;i++)links[i].setAttribute("aria-current",links[i]===on?"page":"false")}'
          'nav.addEventListener("click",function(e){var a=e.target.closest?e.target.closest("a"):null;if(!a)return;'
          'e.preventDefault();location.replace(a.getAttribute("href"));scrollTo(0,0);mark()});'
          'addEventListener("hashchange",mark);mark()})()</script>')

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

# "Wi-Fi" broke at its hyphen ("Wi-" / "Fi") in narrow windows (1.4.1): in the page's text, never in attribute values
# (form fields keep what they hold), it gets a non-breaking hyphen.
_TEXT = re.compile(r">([^<]+)<")


def keep_words(html):
    return _TEXT.sub(lambda m: ">" + m.group(1).replace("Wi-Fi", "Wi‑Fi") + "<", html)


def url(address):
    """An address breaks before its port, not mid-number, when it has to wrap."""
    return re.sub(r"(:\d+/?)$", r"<wbr>\1", escape(address))


def page(title, body, refresh=False, done=None):
    """The title bar and what is under it. refresh: True reloads every 3 s, a number every that many seconds;
    done: (label, address) of the bar's one button."""
    body = keep_words(body)
    meta = f'<meta http-equiv=refresh content={3 if refresh is True else refresh}>' if refresh else ''
    button = f'<a class=done href="{escape(done[1])}">{escape(done[0])}</a>' if done else ''
    return (f'<!doctype html><html lang=zh-CN><head><meta charset=utf-8>'
            f'<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name=color-scheme content="light dark">{meta}'
            f'<title>{escape(title)}</title><script>{THEME}</script><style>{CSS}</style></head>'
            f'<body><header><div><h1>{escape(title)}</h1>{button}</div></header>{body}{SCRIPT}</body></html>')


def alerts(banners):
    return f'<div class=alerts>{banners}</div>' if banners else ''


def flow(content):
    """A screen that is one task: adding an iPhone, a confirmation, the reset."""
    return f'<main class=flow>{content}</main>'


# The categories, in the order shown. The first is the page a visit starts on.
PANES = (("iphone", "iPhone"), ("net", "网络"), ("update", "更新"), ("more", "高级"))


def layout(panes, marked=()):
    """panes: {id: html}; marked: the ids whose category carries a red dot (an update to install)."""
    first = PANES[0][0]
    pages = "".join(f'<section class="pane{" first" if key == first else ""}" id={key} aria-label="{label}">{panes.get(key, "")}</section>'
                    for key, label in PANES[1:] + PANES[:1])
    links = "".join(f'<a href="#{key}"{" class=first" if key == first else ""}>{label}{"<i></i>" if key in marked else ""}</a>'
                    for key, label in PANES)
    return f'<div class=layout>{pages}<nav class=nav aria-label="分类">{links}</nav></div>'


def chain(hotspot, phone, box=("on", "盒子", "运行中")):
    """hotspot/phone/box: (state, name, caption) with state on/wait/off/bad."""
    def node(kind, value):
        state, name, caption = value
        # A name is not broken at its hyphen ("AutoPlay-" / "5G" in a narrow window): between words, or not at all.
        return (f'<div class="node {state}"><div class=glyph>{ICONS[kind]}</div>'
                f'<div class=name>{escape(name).replace("-", chr(0x2011))}</div><div class=state>{escape(caption)}</div></div>')
    return (f'<div class=chain role=img aria-label="{escape(hotspot[1])}：{escape(hotspot[2])}；'
            f'{escape(box[1])}：{escape(box[2])}；{escape(phone[1])}：{escape(phone[2])}">'
            f'{node("hotspot", hotspot)}{node("box", box)}{node("phone", phone)}'
            f'<div class="link a {hotspot[0]}"></div><div class="link b {phone[0]}"></div></div>')


# Row icons: white strokes on a coloured rounded tile, as the panel's rows.
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
    "heat": '<path d="M10 5a2 2 0 0 1 4 0v8.4a4.2 4.2 0 1 1-4 0z"/><path d="M12 10v6"/>',
    "lock": '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "reset": '<path d="M5 12a7 7 0 1 0 2.2-5.1"/><path d="M4.5 4.5v4h4"/>',
}


def tile(color, name):
    return (f'<span class="tile {color}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{TILES[name]}</svg></span>')


def banner(text, kind="ok"):
    return f'<p class="banner {kind}" role=status>{escape(text)}</p>' if text else ""


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
    head = f'<p class=group-title>{escape(title)}</p>' if title else ''
    tail = f'<p class=foot>{foot}</p>' if foot else ""
    return f'<section>{head}<div class=group>{cells}</div>{tail}</section>'


def same_names(names):
    """The names more than one device carries: those rows also show the end of the Bluetooth address."""
    names = list(names)
    return {name for name in names if names.count(name) > 1}


def device_name(name, address, twins):
    line = f'<span>蓝牙 …{escape(address[-5:])}</span>' if name in twins else ''
    return f'<span class=main><b>{escape(name)}</b>{line}</span>'


def phone_rows(devices, active, last, nonce, idle):
    """Bluetooth-style "My devices": a row per iPhone with its state; one that is not in use unfolds to connect it or
    remove it. The one in use is a plain row: nothing can be done to it until it disconnects."""
    if not devices:
        return f'<div class="cell empty">{tile("gray", "phone")}<span class=main><b>还没有添加 iPhone</b></span></div>'
    twins = same_names(devices.values())
    html = ""
    for phone, name in devices.items():
        if phone == active:
            html += (f'<div class="cell on">{tile("green", "phone")}{device_name(name, phone, twins)}'
                     '<span class=value>正在使用</span></div>')
            continue
        summary = (f'<summary class=cell>{tile("gray", "phone")}{device_name(name, phone, twins)}'
                   f'<span class=value>{"上次使用" if phone == last else "未连接"}</span><span class=chev></span></summary>')
        form = f'<form method=post action=/pair>{hidden(nonce, phone=phone)}'
        actions = form + '<button class="cell action" name=action value=use>接入 CarPlay</button></form>' if idle else ''
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
        twins = same_names(f["name"] for f in pair.get("found", []))
        found = "".join(
            f'<form method=post action=/pair>{hidden(nonce, phone=f["address"])}'
            f'<button class=cell name=action value=pick>{tile("gray", "phone")}{device_name(f["name"], f["address"], twins)}'
            '<span class=chev></span></button></form>'
            for f in pair.get("found", []))
        found = found or '<div class="cell empty" aria-busy=true><span class=spin></span><span class=main><b>正在寻找附近的 iPhone…</b></span></div>'
        error = banner(pair["error"], "bad") if pair.get("error") else ""
        # The list to tap first, the three steps under it: in the Tesla's windowed browser the list sat below the fold.
        return (f'{error}{group("附近的 iPhone", found)}{cancel}'
                '<p class=group-title>怎么做</p><ol class=steps>'
                '<li>在 iPhone 上打开「设置 → 蓝牙」，<b>停在这一页</b>。</li>'
                '<li>在上面的列表里点它的名字。</li><li>核对两边的六位数字。</li></ol>', True)
    if phase == "pairing":
        return (group("添加 iPhone", f'<div class=cell aria-busy=true><span class=spin></span><span class=main><b>正在连接「{escape(pair.get("name", ""))}」</b>'
                      '<span>请留意 iPhone 上的配对请求。</span></span></div>') + cancel, True)
    if phase in ("starting", "finishing"):
        return group("添加 iPhone", '<div class="cell empty" aria-busy=true><span class=spin></span><span class=main><b>请稍候…</b></span></div>'), True
    return None, False


def other_screen(address):
    """Where to operate pairing: the head unit or another device, since the iPhone must stay on its Bluetooth page
    (settings_onboarding_audit S5). Shown until the first iPhone is added: the group's title says what to do, the
    row is the address to open there."""
    if not address:
        return ""
    return group("添加时 iPhone 要停在蓝牙页，请在车机或另一台设备上打开",
                 f'<div class=cell>{tile("gray", "screen")}<span class=main><b>{url(address)}</b></span></div>')
