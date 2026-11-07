#!/usr/bin/env python3
"""Static site generator for the Amjad Hani website.

Reads everything from content/*.json (edited through /admin) and writes the finished site to dist/.
GitHub Actions runs this on every publish. Python standard library only (Pillow is used for
image compression when it is available).
"""
import html
import json
import os
import re
import shutil
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content'
DIST = ROOT / 'dist'
ICONS = ROOT / 'src' / 'icons'


# ----------------------------------------------------------------------------- loading
def jload(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {} if default is None else default


def load_folder(name):
    items = []
    d = CONTENT / name
    if d.is_dir():
        for f in sorted(d.glob('*.json')):
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('visible') is False:
                continue
            slug = re.sub(r'[^a-z0-9\-]+', '-', f.stem.lower()).strip('-') or f.stem
            data['_slug'] = slug
            items.append(data)
    items.sort(key=lambda x: (x.get('order', 100) if isinstance(x.get('order', 100), (int, float)) else 100, x['_slug']))
    return items


SITE = jload(CONTENT / 'site.json')
CATS = [c for c in jload(CONTENT / 'categories.json').get('items', []) if c.get('visible') is not False]
TEAM = jload(CONTENT / 'team.json')
PHOTOS = jload(CONTENT / 'photos.json')
CRED = jload(CONTENT / 'credibility.json')
CONTACT = jload(CONTENT / 'contact.json')
PROJECTS = load_folder('projects')
SERVICES = load_folder('services')
NEWS = load_folder('news')
NEWS.sort(key=lambda n: (n.get('date') or ''), reverse=True)

SEO = SITE.get('seo', {})
BASE_URL = (SEO.get('url') or '').rstrip('/')
DEFAULT = SEO.get('default_lang', 'en') if SEO.get('default_lang') in ('en', 'ar') else 'en'
PFX = ''  # relative prefix of the page being rendered ('' for home, '../../' for /projects/x/)


# ----------------------------------------------------------------------------- text helpers
def esc(s):
    return html.escape('' if s is None else str(s), quote=False)


def fmt(s):
    return esc(s).replace('\r\n', '\n').replace('\n', '<br>')


def a(s):
    return html.escape('' if s is None else str(s), quote=True)


def P(d, name):
    """Bilingual value from either {name:{en,ar}} or flat name_en / name_ar."""
    if not isinstance(d, dict):
        return {'en': '', 'ar': ''}
    v = d.get(name)
    if isinstance(v, dict):
        return {'en': v.get('en', '') or '', 'ar': v.get('ar', '') or ''}
    if isinstance(v, str) and (name + '_en') not in d:
        return {'en': v, 'ar': v}
    return {'en': d.get(name + '_en', '') or '', 'ar': d.get(name + '_ar', '') or ''}


def T(en, ar):
    return {'en': en, 'ar': ar}


def L(v):
    en, ar = fmt(v.get('en', '')), fmt(v.get('ar', ''))
    return (en or ar), (ar or en)


def plain(v, lang='en'):
    s = (v.get(lang) or v.get('en') or v.get('ar') or '')
    return re.sub(r'\s+', ' ', str(s)).strip()


def bi(v, tag='span', cls='', attrs=''):
    en, ar = L(v)
    if not en:
        return ''
    c = f' class="{cls}"' if cls else ''
    at = f' {attrs}' if attrs else ''
    return f'<{tag}{c}{at} data-en="{a(en)}" data-ar="{a(ar)}">{en if DEFAULT == "en" else ar}</{tag}>'


def paras(v, cls=''):
    """Bilingual long text -> <p> blocks (blank line = new paragraph)."""
    en_raw, ar_raw = v.get('en', '') or '', v.get('ar', '') or ''
    en_parts = [p for p in re.split(r'\n\s*\n', en_raw.strip()) if p.strip()]
    ar_parts = [p for p in re.split(r'\n\s*\n', ar_raw.strip()) if p.strip()]
    n = max(len(en_parts), len(ar_parts))
    out = []
    for i in range(n):
        out.append(bi({'en': en_parts[i] if i < len(en_parts) else '', 'ar': ar_parts[i] if i < len(ar_parts) else ''}, 'p', cls))
    return ''.join(out)


def U(p):
    if not p:
        return ''
    p = str(p)
    if re.match(r'^(https?:)?//|^data:|^mailto:|^tel:|^#', p):
        return p
    return PFX + p.lstrip('/')


def abs_url(p):
    if not p:
        return ''
    if re.match(r'^https?://', p):
        return p
    return (BASE_URL + '/' + str(p).lstrip('/')) if BASE_URL else str(p)


# ----------------------------------------------------------------------------- icons
_icons = {}


def icon(name, cls='ic'):
    key = (name, cls)
    if key not in _icons:
        f = ICONS / f'{name}.svg'
        if not f.exists():
            f = ICONS / 'arrow-top-right.svg'
        svg = re.sub(r'<!--.*?-->', '', f.read_text(encoding='utf-8'), flags=re.S)
        vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
        inner = re.sub(r'^.*?<svg[^>]*>|</svg>\s*$', '', svg, flags=re.S).strip()
        _icons[key] = f'<svg class="{cls}" viewBox="{vb}" fill="currentColor" aria-hidden="true" focusable="false">{inner}</svg>'
    return _icons[key]


# ----------------------------------------------------------------------------- media
def yt_id(url):
    m = re.search(r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/))([\w-]{11})', url or '')
    return m.group(1) if m else ''


def vimeo_id(url):
    m = re.search(r'vimeo\.com/(?:video/)?(\d+)', url or '')
    return m.group(1) if m else ''


def media_kind(m):
    m = m or {}
    k = m.get('kind')
    if k == 'video' and m.get('video'):
        return 'video'
    if k == 'link' and m.get('link'):
        return 'link'
    if k == 'image' and m.get('image'):
        return 'image'
    for kk in ('image', 'video', 'link'):
        if m.get(kk):
            return kk
    return None


def embed_url(link, autoplay=True, background=False):
    y, v = yt_id(link), vimeo_id(link)
    if y:
        if background:
            return f'https://www.youtube-nocookie.com/embed/{y}?autoplay=1&mute=1&controls=0&loop=1&playlist={y}&playsinline=1&modestbranding=1&rel=0'
        return f'https://www.youtube-nocookie.com/embed/{y}?autoplay=1&rel=0'
    if v:
        if background:
            return f'https://player.vimeo.com/video/{v}?background=1&autoplay=1&loop=1&muted=1'
        return f'https://player.vimeo.com/video/{v}?autoplay=1'
    return link


def poster_of(m):
    if m.get('image'):
        return U(m['image'])
    y = yt_id(m.get('link', ''))
    return f'https://i.ytimg.com/vi/{y}/hqdefault.jpg' if y else ''


def render_media(m, cls='', alt='', controls=False, lazy=True):
    kind = media_kind(m)
    c = f' class="{cls}"' if cls else ''
    ld = ' loading="lazy" decoding="async"' if lazy else ''
    if kind == 'image':
        return f'<img{c} src="{a(U(m["image"]))}" alt="{a(alt)}"{ld}>'
    if kind == 'video':
        poster = f' poster="{a(U(m["image"]))}"' if m.get('image') else ''
        if controls:
            return f'<video{c} src="{a(U(m["video"]))}" controls playsinline preload="metadata"{poster}></video>'
        return f'<video{c} src="{a(U(m["video"]))}" muted loop playsinline autoplay preload="metadata"{poster} aria-label="{a(alt)}"></video>'
    if kind == 'link':
        po = poster_of(m)
        bg = f'<img src="{a(po)}" alt="{a(alt)}"{ld}>' if po else ''
        return (f'<button type="button"{c} data-embed="{a(embed_url(m["link"]))}" aria-label="Play video">'
                f'{bg}<span class="play-btn">{icon("play")}</span></button>')
    return ''


def bg_media(m, alt=''):
    """For full-bleed blocks (about / featured): image -> CSS variable, video/link -> element inside."""
    kind = media_kind(m)
    if kind == 'image':
        return f' style="--img:url(\'{a(U(m["image"]))}\')"', ''
    if kind in ('video', 'link'):
        return '', render_media(m, 'fill', alt, lazy=True) if kind == 'video' else render_media(m, 'fill embed-fill', alt)
    return '', ''


# ----------------------------------------------------------------------------- contact channels
PLATFORMS = {
    'whatsapp': ('whatsapp', 'WhatsApp', 'واتساب'),
    'phone': ('phone', 'Phone', 'هاتف'),
    'email': ('email', 'Email', 'البريد الإلكتروني'),
    'facebook': ('facebook', 'Facebook', 'فيسبوك'),
    'instagram': ('instagram', 'Instagram', 'انستغرام'),
    'linkedin': ('linkedin', 'LinkedIn', 'لينكدإن'),
    'youtube': ('youtube', 'YouTube', 'يوتيوب'),
    'tiktok': ('tiktok', 'TikTok', 'تيك توك'),
    'x': ('x', 'X', 'إكس'),
    'snapchat': ('snapchat', 'Snapchat', 'سناب شات'),
    'telegram': ('telegram', 'Telegram', 'تيليغرام'),
    'map': ('map-marker', 'Location', 'الموقع'),
    'custom': ('arrow-top-right', 'Link', 'رابط'),
}


def channel_href(ch):
    v = (ch.get('value') or '').strip()
    p = ch.get('platform', 'custom')
    if not v:
        return ''
    if re.match(r'^https?://', v) or v.startswith(('mailto:', 'tel:')):
        return v
    if p == 'whatsapp':
        return 'https://wa.me/' + re.sub(r'\D', '', v)
    if p == 'phone':
        return 'tel:' + re.sub(r'[^\d+]', '', v)
    if p == 'email':
        return 'mailto:' + v
    return 'https://' + v


def channels():
    out = []
    for ch in CONTACT.get('channels', []):
        if ch.get('visible') is False or not (ch.get('value') or '').strip():
            continue
        ic, en, ar = PLATFORMS.get(ch.get('platform', 'custom'), PLATFORMS['custom'])
        lab = P(ch, 'label')
        if not (lab['en'] or lab['ar']):
            lab = T(en, ar)
        out.append({'icon': ic, 'label': lab, 'href': channel_href(ch), 'value': ch.get('value', ''), 'platform': ch.get('platform'),
                    'floating': bool(ch.get('floating')), 'footer': ch.get('footer') is not False, 'contact': ch.get('contact') is not False})
    return out


def show_value(c):
    v = c['value']
    if re.match(r'^https?://', v):
        return ''
    return v


# ----------------------------------------------------------------------------- shared chrome
DEFAULT_ORDER = ['hero', 'intro', 'stats', 'team', 'photography', 'projects', 'about', 'expertise', 'featured', 'process',
                 'testimonials', 'partners', 'news', 'faq', 'careers', 'contact']

STATUS = {'completed': T('Completed', 'منجز'), 'in_progress': T('In progress', 'قيد التنفيذ'), 'concept': T('Concept design', 'تصميم مبدئي')}


def nav_items():
    items = SITE.get('nav_items')
    if not items:
        old = SITE.get('nav', {})
        items = [{'label': old.get(k), 'target': '#' + t} for k, t in
                 (('home', 'home'), ('team', 'team'), ('about', 'about'), ('photography', 'photography'), ('careers', 'careers'), ('projects', 'projects'), ('contact', 'contact'))
                 if old.get(k)]
    return [i for i in items if i.get('visible') is not False]


def header():
    links = []
    for it in nav_items():
        t = it.get('target') or '#home'
        href = (PFX + 'index.html' + t if t.startswith('#') and PFX else t) if t.startswith('#') else U(t)
        if t.startswith('#') and PFX:
            href = PFX + t
        links.append(f'<a href="{a(href)}">{bi(P(it, "label"))}</a>')
    cta = SITE.get('header_cta') or {}
    cta_html = ''
    if cta.get('visible', True) and (cta.get('text_en') or cta.get('text_ar') or cta.get('text')):
        tgt = cta.get('target') or '#start'
        href = (PFX + tgt) if tgt.startswith('#') else U(tgt)
        cta_html = f'<a class="nav-cta" href="{a(href)}">{bi(P(cta, "text"))}</a>'
    home = PFX if PFX else '#home'
    brand = SITE.get('brand', {})
    ar_name = brand.get('name_ar') or 'أمجد هاني'
    ar_tag = brand.get('tagline_ar') or 'للهندسة المعمارية والتخطيط'
    return f'''<header class="topbar">
  <a class="brand" href="{a(home)}" aria-label="Home"><img src="{a(PFX)}assets/amjad-hani-logo.png" alt="Amjad Hani Architects &amp; Planners" width="960" height="500"><span class="brand-ar" aria-hidden="true"><span class="brand-ar-square"></span><span class="brand-ar-copy"><strong>{esc(ar_name)}</strong><small>{esc(ar_tag)}</small></span><span class="brand-ar-rule"></span></span></a>
  <nav class="nav" id="nav">{''.join(links)}</nav>
  <div class="tools">{cta_html}<button class="lang" id="lang" type="button">{"AR" if DEFAULT == "en" else "EN"}</button><button class="menu-btn" id="menu" type="button" aria-label="Open menu" aria-expanded="false">☰</button></div>
</header>'''


def footer():
    f = SITE.get('footer', {})
    chs = [c for c in channels() if c['footer']]
    icons = ''.join(
        f'<a href="{a(c["href"])}" {"" if c["href"].startswith(("tel:", "mailto:")) else "target=_blank rel=noopener"} aria-label="{a(plain(c["label"]))}" title="{a(plain(c["label"]))}"><span class="social-icon">{icon(c["icon"])}</span></a>'
        for c in chs)
    priv = ''
    if SITE.get('privacy', {}).get('visible', True) and (SITE.get('privacy', {}).get('body_en') or SITE.get('privacy', {}).get('body_ar')):
        priv = f'<a class="foot-link" href="{a(PFX)}privacy/">{bi(T("Privacy", "الخصوصية"))}</a>'
    return f'''<footer class="footer"><div class="footer-top"><span class="footer-brand">{esc(f.get("brand", "AMJAD HANI · ARCHITECTS & PLANNERS"))}</span><div class="social-links" aria-label="Social">{icons}</div></div><div class="footer-bottom"><span>© <span id="year">{__import__("datetime").date.today().year}</span> {esc(f.get("copyright", "AMJAD HANI"))} {priv}</span>{bi(P(f, "tagline"))}</div></footer>'''


def floating():
    out = []
    for c in channels():
        if c['floating']:
            out.append(f'<a class="float-btn float-{a(c["platform"])}" href="{a(c["href"])}" target="_blank" rel="noopener" aria-label="{a(plain(c["label"]))}">{icon(c["icon"])}</a>')
    return ''.join(out)


def json_ld():
    name = SITE.get('footer', {}).get('copyright') or 'Amjad Hani'
    same = [c['href'] for c in channels() if c['href'].startswith('http') and c['platform'] not in ('whatsapp', 'map')]
    tel = next((c['value'] for c in channels() if c['platform'] == 'phone'), '')
    d = {'@context': 'https://schema.org', '@type': 'ArchitecturalFirm' if False else 'Organization', 'name': f'{name} Architects & Planners', 'url': BASE_URL or None,
         'logo': abs_url('assets/amjad-hani-logo.png'), 'sameAs': same or None, 'telephone': tel or None}
    d = {k: v for k, v in d.items() if v}
    return f'<script type="application/ld+json">{json.dumps(d, ensure_ascii=False)}</script>'


def page(title, desc, body, canonical='', og_image='', body_class='', extra_head='', noindex=False):
    full_title = title
    og = og_image or SEO.get('og_image', '')
    og_abs = abs_url(og) if og else ''
    can = f'<link rel="canonical" href="{a(BASE_URL + "/" + canonical)}">' if BASE_URL else ''
    robots = '<meta name="robots" content="noindex">' if noindex else ''
    umami = SITE.get('analytics', {}).get('umami_website_id', '')
    analytics = f'<script defer src="https://cloud.umami.is/script.js" data-website-id="{a(umami)}"></script>' if umami else ''
    d = 'rtl' if DEFAULT == 'ar' else 'ltr'
    return f'''<!doctype html>
<html lang="{DEFAULT}" dir="{d}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f7f6f2">
<title>{esc(full_title)}</title>
<meta name="description" content="{a(desc)}">
{robots}{can}
<meta property="og:type" content="website"><meta property="og:title" content="{a(full_title)}"><meta property="og:description" content="{a(desc)}">{f'<meta property="og:image" content="{a(og_abs)}">' if og_abs else ''}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{a(PFX)}assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Arabic:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{a(PFX)}assets/css/style.css">
{json_ld()}{extra_head}
</head>
<body class="{body_class}">
{header()}
<main id="main">
{body}
</main>
{footer()}
{floating()}
<div class="lightbox" id="lightbox" hidden role="dialog" aria-modal="true" aria-label="Gallery"><button class="lb-close" type="button" aria-label="Close">{icon("close")}</button><button class="lb-nav lb-prev" type="button" aria-label="Previous">{icon("chevron-left")}</button><div class="lb-stage"></div><button class="lb-nav lb-next" type="button" aria-label="Next">{icon("chevron-right")}</button><div class="lb-cap"></div></div>
<script>window.__DEFAULT_LANG="{DEFAULT}";</script>
<script src="{a(PFX)}assets/js/app.js"></script>
{analytics}
</body>
</html>
'''


# ----------------------------------------------------------------------------- home sections
def heading(key, kicker=True, cls='section-heading', tag='h2'):
    s = SITE.get(key, {})
    k = bi(P(s, 'kicker'), 'div', 'kicker') if kicker else ''
    return k + bi(P(s, 'title'), tag, cls)


def sec_hero():
    h = SITE.get('hero', {})
    slides = [s for s in h.get('slides', []) if s.get('visible') is not False]
    if not slides:
        slides = [{'media': {'kind': 'image', 'image': h.get('image', '')}, 'eyebrow': h.get('eyebrow'), 'title': h.get('title'), 'subtitle': h.get('subtitle')}]
    n = len(slides)
    out = []
    for i, s in enumerate(slides):
        m = s.get('media') or {}
        kind = media_kind(m)
        cls = 'hero-slide' + (' is-active' if i == 0 else '')
        if kind == 'video':
            cls += ' has-video'
            poster = f' poster="{a(U(m["image"]))}"' if m.get('image') else ''
            media = f'<video class="hero-video" src="{a(U(m["video"]))}" muted playsinline preload="{"auto" if i == 0 else "none"}"{poster} {"loop" if n == 1 else ""}></video>'
        elif kind == 'link':
            cls += ' has-video'
            media = f'<iframe class="hero-embed" data-src="{a(embed_url(m["link"], background=True))}" title="video" allow="autoplay; encrypted-media" tabindex="-1" aria-hidden="true"></iframe>'
        else:
            img = U(m.get('image', ''))
            media = f'<div class="hero-media"{(" style=" + chr(34) + "--img:url(" + chr(39) + a(img) + chr(39) + ")" + chr(34)) if img else ""} role="img" aria-label="{a(plain(P(s, "title")))}"></div>'
        title_tag = 'h1' if i == 0 else 'div'
        t_cls = '' if i == 0 else 'h1'
        btn = ''
        bt = P(s, 'button')
        if bt['en'] or bt['ar']:
            tg = s.get('button_link') or '#projects'
            href = (PFX + tg) if tg.startswith('#') else U(tg)
            btn = f'<a class="hero-cta" href="{a(href)}">{bi(bt)}</a>'
        out.append(f'<div class="{cls}" data-kind="{kind or "image"}">{media}<div class="hero-content">{bi(P(s, "eyebrow"), "div", "eyebrow")}{bi(P(s, "title"), title_tag, t_cls)}{bi(P(s, "subtitle"), "p", "hero-sub")}{btn}</div></div>')
    nav = ''
    if n > 1:
        dots = ''.join(f'<button type="button" class="s-dot{" is-active" if i == 0 else ""}" data-i="{i}" aria-label="Slide {i + 1}"></button>' for i in range(n))
        nav = f'<div class="hero-nav"><div class="s-dots">{dots}</div><button type="button" class="s-arrow s-prev" aria-label="Previous">{icon("chevron-left")}</button><button type="button" class="s-arrow s-next" aria-label="Next">{icon("chevron-right")}</button></div>'
    note = bi(P(h, 'play_note'), 'span', 'play-note')
    interval = h.get('interval') or 6
    return f'''<section class="hero" id="home" data-interval="{a(interval)}"><div class="hero-slides">{"".join(out)}</div><div class="hero-bottom">{bi(P(h, "scroll"), "span", "scroll-mark")}{note}{nav}</div></section>'''


def sec_intro():
    s = SITE.get('intro', {})
    return f'''<section class="section intro" id="intro"><div>{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2")}</div><div class="intro-copy">{bi(P(s, "text"), "p")}<a class="text-link" href="#about">{bi(P(s, "link_text"))}<span>↗</span></a></div></section>'''


def sec_stats():
    items = CRED.get('stats', [])
    if not items:
        return ''
    cells = ''
    for it in items:
        if it.get('visible') is False:
            continue
        v = it.get('value', 0)
        cells += f'<div class="stat"><div class="stat-num"><span data-count="{a(v)}">{esc(v)}</span><span class="stat-suf">{esc(it.get("suffix", ""))}</span></div>{bi(P(it, "label"), "div", "stat-label")}</div>'
    return f'<section class="stats" id="stats">{cells}</section>' if cells else ''


def sec_team():
    s = SITE.get('team', {})
    g = TEAM.get('group', {})
    members = [m for m in TEAM.get('members', []) if m.get('visible') is not False]
    group = ''
    if media_kind(g.get('media')):
        cap = bi(P(g, 'caption'), 'figcaption')
        group = f'<figure class="team-group">{render_media(g.get("media"), "", plain(P(g, "caption")) or "Team", controls=media_kind(g.get("media")) == "video")}{cap}</figure>'
    cards, dialogs = '', ''
    for i, m in enumerate(members):
        mid = f'member-{i + 1}'
        name, role = P(m, 'name'), P(m, 'role')
        ph = m.get('photo')
        photo_media = ph if isinstance(ph, dict) else ({'kind': 'image', 'image': ph} if ph else {})
        if media_kind(photo_media):
            inner = render_media(photo_media, '', plain(name))
            big = render_media(photo_media, '', plain(name), controls=False)
        else:
            ini = (plain(name) or '?')[:1]
            inner = big = f'<span class="initial">{esc(ini)}</span>'
        cards += f'<button type="button" class="team-card" data-member="{mid}" aria-haspopup="dialog"><div class="team-photo">{inner}</div>{bi(name, "div", "team-name")}{bi(role, "div", "team-role")}</button>'
        edu, bio = P(m, 'education'), P(m, 'bio')
        links = ''
        if m.get('linkedin'):
            links += f'<a href="{a(m["linkedin"])}" target="_blank" rel="noopener" aria-label="LinkedIn">{icon("linkedin")}</a>'
        if m.get('email'):
            links += f'<a href="mailto:{a(m["email"])}" aria-label="Email">{icon("email")}</a>'
        dialogs += f'''<dialog class="modal" id="{mid}" aria-label="{a(plain(name))}"><button type="button" class="modal-close" data-close aria-label="Close">{icon("close")}</button><div class="modal-body"><div class="modal-photo">{big}</div><div class="modal-info">{bi(name, "h3")}{bi(role, "div", "team-role")}{(bi(T("Education", "التعليم"), "h4") + bi(edu, "p")) if (edu["en"] or edu["ar"]) else ""}{(bi(T("About", "نبذة"), "h4") + paras(bio)) if (bio["en"] or bio["ar"]) else ""}{f'<div class="modal-links">{links}</div>' if links else ""}</div></div></dialog>'''
    note = bi(P(s, 'empty_note'), 'div', 'placeholder-note') if not members and not group else ''
    return f'''<section class="section team-section" id="team">{bi(P(s, "kicker"), "div", "kicker")}<div class="team-intro">{bi(P(s, "title"), "h2", "section-heading")}{bi(P(s, "text"), "p")}</div>{group}<div class="team-grid">{cards}</div>{note}{dialogs}</section>'''


def sec_photography():
    s = SITE.get('photography', {})
    figs = ''
    items = [p for p in PHOTOS.get('photos', []) if p.get('visible') is not False]
    for p in items:
        m = p.get('media') or ({'kind': 'image', 'image': p.get('image')} if p.get('image') else {})
        k = media_kind(m)
        if not k:
            continue
        alt = p.get('alt') or ''
        if k == 'image':
            figs += f'<figure class="ph"><button type="button" class="lb-item" data-lb="{a(U(m["image"]))}" data-group="photos" data-cap="{a(alt)}">{render_media(m, "", alt)}</button></figure>'
        else:
            figs += f'<figure class="ph">{render_media(m, "", alt)}</figure>'
    return f'''<section class="section photography-section" id="photography"><div class="section-head"><div>{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}</div>{bi(P(s, "text"), "p", "photo-intro")}</div><div class="photo-grid">{figs}</div>{bi(P(s, "note"), "p", "placeholder-note")}</section>'''


def cat_label(c):
    return P(c, 'name')


def project_slides(pr):
    ms = []
    if media_kind(pr.get('cover')):
        ms.append(pr['cover'])
    for g in pr.get('gallery', []):
        gm = g.get('media') if isinstance(g, dict) and 'media' in g else g
        if media_kind(gm) in ('image', 'video'):
            ms.append(gm)
    return ms[:5]


def slider(ms, alt, link=None, cls='pslider'):
    if not ms:
        return f'<div class="{cls} empty"></div>'
    slides = ''.join(f'<div class="pslide{" is-active" if i == 0 else ""}">{render_media(m, "", alt, lazy=i > 0)}</div>' for i, m in enumerate(ms))
    ctl = ''
    if len(ms) > 1:
        dots = ''.join(f'<button type="button" class="s-dot{" is-active" if i == 0 else ""}" data-i="{i}" aria-label="Slide {i + 1}"></button>' for i in range(len(ms)))
        ctl = f'<button type="button" class="s-arrow s-prev" aria-label="Previous">{icon("chevron-left")}</button><button type="button" class="s-arrow s-next" aria-label="Next">{icon("chevron-right")}</button><div class="s-dots">{dots}</div>'
    lk = f'<a class="card-link" href="{a(link)}" aria-label="{a(alt)}"></a>' if link else ''
    return f'<div class="{cls}" data-slider data-interval="4">{slides}{lk}{ctl}</div>'


def sec_projects():
    s = SITE.get('projects', {})
    cat_by_id = {c.get('id'): c for c in CATS}
    counts = {c.get('id'): 0 for c in CATS}
    for pr in PROJECTS:
        for cid in pr.get('categories', []):
            if cid in counts:
                counts[cid] += 1
    cards = ''
    all_total = len(PROJECTS)
    if CATS:
        cards = f'<button type="button" class="cat-card cat-all" data-cat="all"><span class="cat-name">{bi(T("All projects", "كل المشاريع"))}</span><span class="cat-count">{all_total}</span></button>'
        for c in CATS:
            m = c.get('media') or {}
            k = media_kind(m)
            img = render_media(m, '', plain(cat_label(c))) if k in ('image', 'video') else ''
            cards += f'<button type="button" class="cat-card" data-cat="{a(c.get("id"))}">{img}<span class="cat-name">{bi(cat_label(c))}</span><span class="cat-count">{counts.get(c.get("id"), 0)}</span></button>'
    tabs = ''
    if CATS:
        tabs = '<div class="proj-tabs" hidden>' + f'<button type="button" data-cat="all">{bi(T("All", "الكل"))}</button>' + ''.join(
            f'<button type="button" data-cat="{a(c.get("id"))}">{bi(cat_label(c))}</button>' for c in CATS) + '</div>'
    has_featured = any(p.get('featured') for p in PROJECTS)
    grid = ''
    for i, pr in enumerate(PROJECTS):
        cids = [x for x in pr.get('categories', []) if x in cat_by_id]
        types = P(pr, 'type')
        if not (types['en'] or types['ar']) and cids:
            types = {'en': ' · '.join(plain(cat_label(cat_by_id[x]), 'en') for x in cids), 'ar': ' · '.join(plain(cat_label(cat_by_id[x]), 'ar') for x in cids)}
        link = f'{PFX}projects/{pr["_slug"]}/'
        feat = ' data-featured="1"' if (pr.get('featured') or not has_featured and i < 4) else ''
        title = P(pr, 'title')
        grid += f'<article class="project-card{" alt" if i % 2 else ""}" data-cats="{a(" ".join(cids))}"{feat}><div class="project-image">{slider(project_slides(pr), plain(title), link)}</div><div class="project-meta"><div>{bi(title, "a", "project-title", f"href={chr(34)}{a(link)}{chr(34)}")}{bi(types, "div", "project-type")}</div><span>↗</span></div></article>'
    return f'''<section class="section projects" id="projects"><div class="section-head"><div>{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}</div><button type="button" class="text-link" data-cat="all">{bi(P(s, "link_text"))}<span>↗</span></button></div><div class="cat-grid">{cards}</div>{tabs}<div class="project-grid" data-view="featured">{grid}</div>{bi(P(s, "note"), "p", "small-note")}</section>'''


def sec_about():
    s = SITE.get('about', {})
    st, inner = bg_media(s.get('media') or {'kind': 'image', 'image': s.get('image', '')}, plain(P(s, 'title')))
    return f'''<section class="about-band" id="about"><div class="about-image"{st} role="img" aria-label="{a(plain(P(s, "title")))}">{inner}</div><div class="about-copy">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2")}{bi(P(s, "text"), "p")}<a class="text-link" href="#contact">{bi(P(s, "link_text"))}<span>↗</span></a></div></section>'''


def sec_expertise():
    s = SITE.get('expertise', {})
    items = ''
    for i, sv in enumerate(SERVICES):
        link = f'{PFX}services/{sv["_slug"]}/'
        items += f'<a class="expertise-item" href="{a(link)}"><span class="expertise-num">{i + 1:02d}</span>{bi(P(sv, "title"), "h3")}{bi(P(sv, "summary"), "p")}</a>'
    return f'''<section class="section expertise" id="expertise">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}<div class="expertise-grid">{items}</div>{bi(P(s, "note"), "p", "small-note")}</section>'''


def sec_featured():
    s = SITE.get('featured', {})
    st, inner = bg_media(s.get('media') or {'kind': 'image', 'image': s.get('image', '')}, plain(P(s, 'title')))
    return f'''<section class="section featured" id="featured">{bi(P(s, "kicker"), "div", "kicker")}<div class="featured-image"{st}>{inner}{bi(P(s, "label"), "div", "featured-label")}</div><div class="featured-caption">{bi(P(s, "title"), "h3")}{bi(P(s, "text"), "p")}</div></section>'''


def sec_process():
    items = [x for x in CRED.get('process', []) if x.get('visible') is not False]
    if not items:
        return ''
    s = SITE.get('process', {})
    steps = ''.join(f'<li><span class="expertise-num">{i + 1:02d}</span>{bi(P(x, "title"), "h3")}{bi(P(x, "text"), "p")}</li>' for i, x in enumerate(items))
    return f'<section class="section process" id="process">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}<ol class="process-list">{steps}</ol></section>'


def sec_testimonials():
    items = [x for x in CRED.get('testimonials', []) if x.get('visible') is not False]
    if not items:
        return ''
    s = SITE.get('testimonials', {})
    q = ''.join(f'<blockquote class="quote">{bi(P(x, "quote"), "p")}<footer>{bi(P(x, "author"), "strong")}{bi(P(x, "role"), "span")}</footer></blockquote>' for x in items)
    return f'<section class="section testimonials" id="testimonials">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}<div class="quote-grid">{q}</div></section>'


def sec_partners():
    clients = [x for x in CRED.get('clients', []) if x.get('visible') is not False]
    awards = [x for x in CRED.get('awards', []) if x.get('visible') is not False]
    if not clients and not awards:
        return ''
    s = SITE.get('partners', {})
    cl = ''
    if clients:
        cl = '<div class="client-row">' + ''.join(
            (f'<div class="client">{render_media({"kind": "image", "image": x["logo"]}, "", x.get("name", ""))}</div>' if x.get('logo') else f'<div class="client client-text">{esc(x.get("name", ""))}</div>')
            for x in clients) + '</div>'
    aw = ''
    if awards:
        aw = '<ul class="award-list">' + ''.join(
            f'<li><span class="award-year">{esc(x.get("year", ""))}</span><div>{bi(P(x, "title"), "strong")}{bi(P(x, "org"), "span")}</div></li>' for x in awards) + '</ul>'
    return f'<section class="section partners" id="partners">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}{cl}{aw}</section>'


def news_card(n):
    link = f'{PFX}news/{n["_slug"]}/'
    m = n.get('cover') or {}
    img = render_media(m, '', plain(P(n, 'title'))) if media_kind(m) in ('image', 'video') else ''
    return f'<a class="news-card" href="{a(link)}"><div class="news-img">{img}</div><div class="news-date">{esc(n.get("date", ""))}</div>{bi(P(n, "title"), "h3")}{bi(P(n, "summary"), "p")}</a>'


def sec_news():
    if not NEWS:
        return ''
    s = SITE.get('news', {})
    cnt = int(s.get('count') or 3)
    cards = ''.join(news_card(n) for n in NEWS[:cnt])
    return f'<section class="section news" id="news"><div class="section-head"><div>{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}</div><a class="text-link" href="{a(PFX)}news/">{bi(P(s, "link_text") if (P(s, "link_text")["en"]) else T("All news", "كل الأخبار"))}<span>↗</span></a></div><div class="news-grid">{cards}</div></section>'


def sec_faq():
    items = [x for x in CRED.get('faq', []) if x.get('visible') is not False]
    if not items:
        return ''
    s = SITE.get('faq', {})
    det = ''.join(f'<details>{bi(P(x, "q"), "summary")}{bi(P(x, "a"), "p")}</details>' for x in items)
    ld = {'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [
        {'@type': 'Question', 'name': plain(P(x, 'q'), DEFAULT), 'acceptedAnswer': {'@type': 'Answer', 'text': plain(P(x, 'a'), DEFAULT)}} for x in items]}
    return f'<section class="section faq" id="faq">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2", "section-heading")}<div class="faq-list">{det}</div><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></section>'


def sec_careers():
    s = SITE.get('careers', {})
    apply = s.get('apply_link') or ''
    if not apply:
        em = next((c for c in channels() if c['platform'] == 'email'), None)
        apply = em['href'] if em else '#start'
    href = (PFX + apply) if apply.startswith('#') else apply
    return f'''<section class="section careers-section" id="careers">{bi(P(s, "kicker"), "div", "kicker")}<div class="careers-layout"><div>{bi(P(s, "title"), "h2", "section-heading")}{bi(P(s, "text"), "p")}</div><a class="text-link" href="{a(href)}">{bi(P(s, "link_text"))}<span>↗</span></a></div>{bi(P(s, "note"), "p", "placeholder-note")}</section>'''


FIELD_LABELS = {
    'name': T('Full name', 'الاسم الكامل'), 'phone': T('Phone number', 'رقم الجوال'), 'email': T('Email', 'البريد الإلكتروني'),
    'project_name': T('Project name', 'اسم المشروع'), 'project_type': T('Project type', 'نوع المشروع'), 'location': T('Project location', 'موقع المشروع'),
    'budget': T('Approximate budget', 'الميزانية التقريبية'), 'contact_method': T('Preferred contact method', 'وسيلة التواصل المفضلة'),
    'description': T('Project description', 'وصف المشروع'),
}


def sec_contact():
    s = SITE.get('contact', {})
    f = CONTACT.get('form', {})
    chs = [c for c in channels() if c['contact']]
    rows = ''
    for c in chs:
        val = show_value(c)
        ext = '' if c['href'].startswith(('tel:', 'mailto:')) else ' target="_blank" rel="noopener"'
        rows += f'<li><a href="{a(c["href"])}"{ext}><span class="social-icon">{icon(c["icon"])}</span><span class="ch-text">{bi(c["label"], "span", "ch-label")}{f"<span class=ch-val dir=ltr>{esc(val)}</span>" if val else ""}</span></a></li>'
    info = ''
    addr, hours = P(CONTACT, 'address'), P(CONTACT, 'hours')
    if addr['en'] or addr['ar']:
        murl = CONTACT.get('map_url')
        mp = f'<a class="map-link" href="{a(murl)}" target="_blank" rel="noopener">{bi(T("Open map", "افتح الخريطة"))}</a>' if murl else ''
        info += f'<div class="info-row">{icon("map-marker")}<div>{bi(addr, "span")}{mp}</div></div>'
    if hours['en'] or hours['ar']:
        info += f'<div class="info-row">{icon("clock-outline")}<div>{bi(hours, "span")}</div></div>'
    note = ''
    if not chs:
        note = bi(P(s, 'note'), 'span', 'contact-note')

    # form
    lbl = {k: P(f.get('labels', {}), k) if f.get('labels', {}).get(k) or f.get('labels', {}).get(k + '_en') else FIELD_LABELS[k] for k in FIELD_LABELS}
    opts = ''.join(f'<option value="{a(plain(P(c, "name")))}">{bi(cat_label(c), "span")}</option>' for c in CATS)
    # <option> can't hold spans; build plain options with data-en/data-ar on the option itself
    opts = ''.join(f'<option value="{a(plain(cat_label(c)))}" data-en="{a(plain(cat_label(c), "en"))}" data-ar="{a(plain(cat_label(c), "ar"))}">{esc(plain(cat_label(c), DEFAULT))}</option>' for c in CATS)
    budgets = ''.join(f'<option value="{a(plain(P(b, "label")))}" data-en="{a(plain(P(b, "label"), "en"))}" data-ar="{a(plain(P(b, "label"), "ar"))}">{esc(plain(P(b, "label"), DEFAULT))}</option>' for b in f.get('budgets', []))
    cm = [('Phone call', 'اتصال هاتفي'), ('WhatsApp', 'واتساب'), ('Email', 'بريد إلكتروني')]
    cms = ''.join(f'<option value="{e}" data-en="{e}" data-ar="{r}">{e if DEFAULT == "en" else r}</option>' for e, r in cm)
    sel_ph = lambda: f'<option value="" data-en="—" data-ar="—">—</option>'

    def field(name, tag='input', typ='text', req=False, extra=''):
        lab = bi(lbl[name], 'span', 'f-label')
        star = '<i class="req" aria-hidden="true">*</i>' if req else ''
        r = ' required' if req else ''
        if tag == 'input':
            ctl = f'<input name="{name}" type="{typ}"{r} {extra}>'
        elif tag == 'textarea':
            ctl = f'<textarea name="{name}" rows="5"{r}></textarea>'
        else:
            ctl = f'<select name="{name}">{extra}</select>'
        return f'<label class="field field-{name}">{lab}{star}{ctl}</label>'

    privacy = ''
    if SITE.get('privacy', {}).get('body_en') or SITE.get('privacy', {}).get('body_ar'):
        privacy = f'<label class="consent"><input type="checkbox" name="consent" required><span>{bi(P(f, "consent") if (P(f, "consent")["en"]) else T("I agree to the processing of my data to contact me about my request.", "أوافق على استخدام بياناتي للتواصل معي بخصوص طلبي."))} <a href="{a(PFX)}privacy/" target="_blank">{bi(T("Privacy", "الخصوصية"))}</a></span></label>'
    msg = {k: P(f, k) for k in ('success', 'error')}
    form = f'''<form class="start-form" id="start" novalidate data-key="{a(f.get("web3forms_key", ""))}" data-subject="{a(f.get("subject") or "New project request")}"
  data-ok-en="{a(L(msg["success"])[0] or "Thank you! We received your request and will contact you soon.")}" data-ok-ar="{a(L(msg["success"])[1] or "شكراً لك! وصلنا طلبك وسنتواصل معك قريباً.")}"
  data-err-en="{a(L(msg["error"])[0] or "Something went wrong. Please try again or contact us directly.")}" data-err-ar="{a(L(msg["error"])[1] or "حدث خطأ. حاول مرة أخرى أو تواصل معنا مباشرة.")}"
  data-inv-en="Please fill in all required fields correctly." data-inv-ar="يرجى تعبئة الحقول المطلوبة بشكل صحيح.">
  {bi(P(f, "title") if P(f, "title")["en"] else T("Start your project with us", "ابدأ مشروعك معنا"), "h3")}{bi(P(f, "intro"), "p", "form-intro")}
  <input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
  <div class="fields">{field("name", req=True, extra='autocomplete="name"')}{field("phone", typ="tel", req=True, extra='autocomplete="tel" inputmode="tel"')}{field("email", typ="email", req=True, extra='autocomplete="email"')}{field("project_name", req=True)}
  {field("project_type", "select", extra=sel_ph() + opts) if CATS else ""}{field("location")}{field("budget", "select", extra=sel_ph() + budgets) if budgets else ""}{field("contact_method", "select", extra=sel_ph() + cms)}
  {field("description", "textarea", req=True)}</div>{privacy}
  <button class="btn" type="submit">{bi(P(f, "button") if P(f, "button")["en"] else T("Send request", "إرسال الطلب"))}</button><p class="form-msg" role="status" aria-live="polite" hidden></p>
</form>'''
    return f'''<section class="contact" id="contact">{bi(P(s, "kicker"), "div", "kicker")}{bi(P(s, "title"), "h2")}<div class="contact-grid"><div class="contact-info">{bi(P(s, "text"), "p", "contact-text")}<div class="info-rows">{info}</div><ul class="ch-list">{rows}</ul>{note}</div>{form}</div></section>'''


SECTIONS = {
    'hero': sec_hero, 'intro': sec_intro, 'stats': sec_stats, 'team': sec_team, 'photography': sec_photography, 'projects': sec_projects,
    'about': sec_about, 'expertise': sec_expertise, 'featured': sec_featured, 'process': sec_process, 'testimonials': sec_testimonials,
    'partners': sec_partners, 'news': sec_news, 'faq': sec_faq, 'careers': sec_careers, 'contact': sec_contact,
}


def home_sections():
    conf = SITE.get('sections') or []
    order, seen = [], set()
    for c in conf:
        i = c.get('id')
        if i in SECTIONS and i not in seen:
            seen.add(i)
            if c.get('visible') is not False:
                order.append(i)
    for i in DEFAULT_ORDER:
        if i not in seen:
            order.append(i)
    return order


# ----------------------------------------------------------------------------- inner pages
def cta_block():
    f = CONTACT.get('form', {})
    return f'''<section class="cta-band"><div>{bi(T("Have a project in mind?", "هل لديك مشروع في بالك؟"), "h2")}</div><a class="btn btn-light" href="{a(PFX)}#start">{bi(T("Start your project with us", "ابدأ مشروعك معنا"))}</a></section>'''


def gallery_block(items, group='g'):
    out = ''
    for g in items:
        m = g.get('media') if isinstance(g, dict) and 'media' in g else g
        k = media_kind(m)
        cap = P(g, 'caption') if isinstance(g, dict) else {'en': '', 'ar': ''}
        capt = plain(cap)
        if k == 'image':
            out += f'<figure class="g-item"><button type="button" class="lb-item" data-lb="{a(U(m["image"]))}" data-group="{group}" data-cap="{a(capt)}">{render_media(m, "", capt)}</button></figure>'
        elif k in ('video', 'link'):
            out += f'<figure class="g-item g-video">{render_media(m, "", capt, controls=(k == "video"))}</figure>'
    return f'<div class="gallery">{out}</div>' if out else ''


def file_ext(p):
    return os.path.splitext(str(p).split('?')[0])[1].lower().lstrip('.')


def drawings_block(items):
    cards = ''
    for d in items:
        f = d.get('file')
        if not f:
            continue
        ext = file_ext(f)
        title = P(d, 'title')
        href = U(f)
        dl = f'<a class="btn-sm" href="{a(href)}" download>{icon("download")}{bi(T("Download", "تحميل"))}</a>'
        if ext in ('png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'):
            cards += f'<div class="draw-card"><button type="button" class="lb-item draw-thumb" data-lb="{a(href)}" data-group="drawings" data-cap="{a(plain(title))}"><img src="{a(href)}" alt="{a(plain(title))}" loading="lazy"></button><div class="draw-info">{bi(title, "strong")}<div class="draw-actions">{dl}</div></div></div>'
        else:
            view = f'<a class="btn-sm" href="{a(href)}" target="_blank" rel="noopener">{icon("file-pdf-box")}{bi(T("View", "عرض"))}</a>' if ext == 'pdf' else ''
            cards += f'<div class="draw-card"><div class="draw-file">{icon("file-pdf-box" if ext == "pdf" else "ruler-square")}<span>{esc(ext.upper() or "FILE")}</span></div><div class="draw-info">{bi(title, "strong")}<div class="draw-actions">{view}{dl}</div></div></div>'
    return f'<div class="draw-grid">{cards}</div>' if cards else ''


def project_page(pr, idx):
    global PFX
    PFX = '../../'
    title, summary = P(pr, 'title'), P(pr, 'summary')
    cats = {c.get('id'): c for c in CATS}
    cat_links = ' · '.join(f'<a href="{PFX}#projects">{bi(cat_label(cats[x]))}</a>' for x in pr.get('categories', []) if x in cats)
    st = STATUS.get(pr.get('status'))
    badge = f'<span class="badge">{bi(st)}</span>' if st else ''
    cover = pr.get('cover') or {}
    ck = media_kind(cover)
    cover_html = ''
    if ck:
        cover_html = f'<div class="proj-cover">{render_media(cover, "", plain(title), controls=False, lazy=False)}</div>'

    facts = []

    def fact(lab, val_html):
        if val_html:
            facts.append(f'<div class="fact"><span class="fact-k">{bi(lab)}</span><span class="fact-v">{val_html}</span></div>')
    fact(T('Status', 'الحالة'), bi(st) if st else '')
    fact(T('Year', 'السنة'), esc(pr.get('year', '')) if pr.get('year') else '')
    fact(T('Area', 'المساحة'), esc(pr.get('area', '')) if pr.get('area') else '')
    loc = P(pr, 'location')
    if loc['en'] or loc['ar']:
        lh = bi(loc)
        if pr.get('map_url'):
            lh += f' <a class="map-link" href="{a(pr["map_url"])}" target="_blank" rel="noopener">{bi(T("Map", "الخريطة"))}</a>'
        fact(T('Location', 'الموقع'), lh)
    cl = P(pr, 'client')
    fact(T('Client', 'العميل'), bi(cl) if (cl['en'] or cl['ar']) else '')
    fact(T('Category', 'القسم'), cat_links)
    desc = P(pr, 'description')
    body = ''
    if desc['en'] or desc['ar'] or facts:
        body = f'<section class="proj-body"><div class="prose">{paras(desc)}</div><aside class="facts">{"".join(facts)}</aside></section>'
    map_block = ''
    if pr.get('show_map') and pr.get('map_query'):
        q = urllib.parse.quote(pr['map_query'])
        map_block = f'<section class="proj-block"><div class="map-embed"><iframe src="https://www.google.com/maps?q={q}&amp;output=embed" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="Map"></iframe></div></section>'
    gal = gallery_block(pr.get('gallery', []), 'gallery')
    gal = f'<section class="proj-block"><h2 class="block-title">{bi(T("Gallery", "معرض الصور"))}</h2>{gal}</section>' if gal else ''
    stages = ''
    sl = [s for s in pr.get('stages', []) if s.get('visible') is not False]
    if sl:
        li = ''
        for i, s in enumerate(sl):
            im = s.get('media') or ({'kind': 'image', 'image': s.get('image')} if s.get('image') else {})
            img = render_media(im, '', plain(P(s, 'title'))) if media_kind(im) in ('image', 'video') else ''
            li += f'<li><span class="expertise-num">{i + 1:02d}</span>{bi(P(s, "title"), "h3")}{bi(P(s, "text"), "p")}{f"<div class=stage-img>{img}</div>" if img else ""}</li>'
        stages = f'<section class="proj-block"><h2 class="block-title">{bi(T("Project stages", "مراحل المشروع"))}</h2><ol class="stages">{li}</ol></section>'
    ba = ''
    bl = [b for b in pr.get('before_after', []) if b.get('before') and b.get('after')]
    if bl:
        items = ''.join(
            f'<figure class="ba-wrap"><div class="ba" data-ba style="--pos:50%"><img src="{a(U(b["before"]))}" alt="Before" loading="lazy"><div class="ba-after"><img src="{a(U(b["after"]))}" alt="After" loading="lazy"></div><span class="ba-tag ba-tag-b">{bi(T("Before", "قبل"))}</span><span class="ba-tag ba-tag-a">{bi(T("After", "بعد"))}</span><div class="ba-handle"></div><input class="ba-range" type="range" min="0" max="100" value="50" aria-label="Before / After"></div>{bi(P(b, "caption"), "figcaption")}</figure>'
            for b in bl)
        ba = f'<section class="proj-block"><h2 class="block-title">{bi(T("Before & After", "قبل وبعد"))}</h2><div class="ba-grid">{items}</div></section>'
    dr = drawings_block(pr.get('drawings', []))
    dr = f'<section class="proj-block"><h2 class="block-title">{bi(T("Drawings & plans", "المخططات والرسومات"))}</h2>{dr}</section>' if dr else ''
    tm = pr.get('testimonial') or {}
    tq = P(tm, 'quote')
    test = ''
    if tq['en'] or tq['ar']:
        test = f'<section class="proj-block"><blockquote class="quote quote-lg">{bi(tq, "p")}<footer>{bi(P(tm, "author"), "strong")}{bi(P(tm, "role"), "span")}</footer></blockquote></section>'
    extra = ''
    for e in pr.get('extra', []):
        if e.get('visible') is False:
            continue
        files = ''.join(f'<a class="btn-sm" href="{a(U(x.get("file")))}" download>{icon("download")}{bi(P(x, "label") if P(x, "label")["en"] else T("Download", "تحميل"))}</a>' for x in e.get('files', []) if x.get('file'))
        extra += f'<section class="proj-block"><h2 class="block-title">{bi(P(e, "title"))}</h2><div class="prose">{paras(P(e, "text"))}</div>{gallery_block(e.get("media", []), "extra")}{f"<div class=draw-actions>{files}</div>" if files else ""}</section>'
    prev_n = ''
    if len(PROJECTS) > 1:
        pv, nx = PROJECTS[(idx - 1) % len(PROJECTS)], PROJECTS[(idx + 1) % len(PROJECTS)]
        prev_n = f'<nav class="pn"><a href="../{a(pv["_slug"])}/"><span class="pn-k">{bi(T("Previous project", "المشروع السابق"))}</span>{bi(P(pv, "title"), "span", "pn-t")}</a><a class="pn-next" href="../{a(nx["_slug"])}/"><span class="pn-k">{bi(T("Next project", "المشروع التالي"))}</span>{bi(P(nx, "title"), "span", "pn-t")}</a></nav>'
    head = f'<section class="proj-head"><div class="crumbs"><a href="{PFX}#projects">{bi(T("Projects", "المشاريع"))}</a>{" / " + cat_links if cat_links else ""}</div>{bi(title, "h1")}{bi(summary, "p", "lede")}{badge}</section>'
    seo_t = P(pr, 'seo_title') if (pr.get('seo_title') or pr.get('seo_title_en')) else title
    seo_d = P(pr, 'seo_description') if (pr.get('seo_description') or pr.get('seo_description_en')) else (summary if (summary['en'] or summary['ar']) else desc)
    og = cover.get('image') if ck == 'image' else (cover.get('image') or '')
    html_ = page(f'{plain(seo_t, DEFAULT)} — {SITE.get("footer", {}).get("copyright", "Amjad Hani")}', plain(seo_d, DEFAULT)[:160],
                 head + cover_html + body + map_block + gal + stages + ba + dr + test + extra + cta_block() + prev_n,
                 canonical=f'projects/{pr["_slug"]}/', og_image=og, body_class='inner')
    PFX = ''
    return html_


def article_page(kind, item, idx, lst):
    global PFX
    PFX = '../../'
    title, summary, body = P(item, 'title'), P(item, 'summary'), P(item, 'body')
    cover = item.get('cover') or {}
    cover_html = f'<div class="proj-cover">{render_media(cover, "", plain(title), lazy=False)}</div>' if media_kind(cover) else ''
    date = f'<div class="news-date">{esc(item.get("date", ""))}</div>' if kind == 'news' else ''
    back_lab = T('News', 'الأخبار') if kind == 'news' else T('Services', 'الخدمات')
    back = f'{PFX}news/' if kind == 'news' else f'{PFX}#expertise'
    gal = gallery_block(item.get('gallery', []), kind)
    nav = ''
    if len(lst) > 1:
        pv, nx = lst[(idx - 1) % len(lst)], lst[(idx + 1) % len(lst)]
        nav = f'<nav class="pn"><a href="../{a(pv["_slug"])}/"><span class="pn-k">{bi(T("Previous", "السابق"))}</span>{bi(P(pv, "title"), "span", "pn-t")}</a><a class="pn-next" href="../{a(nx["_slug"])}/"><span class="pn-k">{bi(T("Next", "التالي"))}</span>{bi(P(nx, "title"), "span", "pn-t")}</a></nav>'
    head = f'<section class="proj-head"><div class="crumbs"><a href="{a(back)}">{bi(back_lab)}</a></div>{date}{bi(title, "h1")}{bi(summary, "p", "lede")}</section>'
    prose = f'<section class="proj-body single"><div class="prose">{paras(body)}</div></section>' if (body['en'] or body['ar']) else ''
    og = cover.get('image', '') if media_kind(cover) == 'image' else ''
    html_ = page(f'{plain(title, DEFAULT)} — {SITE.get("footer", {}).get("copyright", "Amjad Hani")}', plain(summary if (summary["en"] or summary["ar"]) else body, DEFAULT)[:160],
                 head + cover_html + prose + (f'<section class="proj-block">{gal}</section>' if gal else '') + cta_block() + nav,
                 canonical=f'{"news" if kind == "news" else "services"}/{item["_slug"]}/', og_image=og, body_class='inner')
    PFX = ''
    return html_


def news_index():
    global PFX
    PFX = '../'
    s = SITE.get('news', {})
    cards = ''.join(news_card(n) for n in NEWS)
    body = f'<section class="proj-head"><div class="crumbs"><a href="{PFX}">{bi(T("Home", "الرئيسية"))}</a></div>{bi(P(s, "title") if P(s, "title")["en"] else T("News", "الأخبار"), "h1")}</section><section class="section news"><div class="news-grid">{cards}</div></section>'
    out = page(f'News — {SITE.get("footer", {}).get("copyright", "Amjad Hani")}', plain(P(s, 'title')) or 'News', body, canonical='news/', body_class='inner')
    PFX = ''
    return out


def privacy_page():
    global PFX
    PFX = '../'
    p = SITE.get('privacy', {})
    body = f'<section class="proj-head"><div class="crumbs"><a href="{PFX}">{bi(T("Home", "الرئيسية"))}</a></div>{bi(P(p, "title") if P(p, "title")["en"] else T("Privacy", "الخصوصية"), "h1")}</section><section class="proj-body single"><div class="prose">{paras(P(p, "body"))}</div></section>'
    out = page(f'Privacy — {SITE.get("footer", {}).get("copyright", "Amjad Hani")}', 'Privacy', body, canonical='privacy/', body_class='inner')
    PFX = ''
    return out


def not_found():
    path = urllib.parse.urlparse(BASE_URL).path.rstrip('/') + '/' if BASE_URL else '/'
    body = f'''<section class="nf"><div class="nf-code">404</div>{bi(T("This page could not be found.", "لم يتم العثور على هذه الصفحة."), "h1")}<a class="text-link" href="{a(path)}">{bi(T("Back to home", "العودة للرئيسية"))}<span>↗</span></a></section>'''
    h = page('404 — Amjad Hani', 'Page not found', body, body_class='inner', noindex=True)
    # 404 is served from any depth: make every relative URL absolute to the site base path
    h = h.replace('<head>', f'<head><base href="{a(path)}">', 1)
    return h


# ----------------------------------------------------------------------------- build
def write(path, text):
    p = DIST / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def optimize_copy(src_dir, dst_dir):
    try:
        from PIL import Image
    except Exception:
        Image = None
    saved = 0
    for f in src_dir.rglob('*'):
        if f.is_dir() or f.name == '.gitkeep':
            continue
        out = dst_dir / f.relative_to(src_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        ext = f.suffix.lower()
        if Image and ext in ('.jpg', '.jpeg', '.png', '.webp') and f.stat().st_size > 400_000:
            try:
                im = Image.open(f)
                if max(im.size) > 2200:
                    im.thumbnail((2200, 2200))
                    if ext in ('.jpg', '.jpeg'):
                        im.convert('RGB').save(out, quality=84, optimize=True)
                    elif ext == '.webp':
                        im.save(out, quality=84)
                    else:
                        im.save(out, optimize=True)
                    saved += f.stat().st_size - out.stat().st_size
                    continue
            except Exception:
                pass
        shutil.copy2(f, out)
    return saved


def main():
    global PFX
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    saved = optimize_copy(ROOT / 'assets', DIST / 'assets')
    (DIST / 'assets' / 'css').mkdir(parents=True, exist_ok=True)
    (DIST / 'assets' / 'js').mkdir(parents=True, exist_ok=True)
    css = ''.join((ROOT / 'src' / n).read_text(encoding='utf-8') + '\n' for n in ('style.base.css', 'style.extra.css'))
    (DIST / 'assets' / 'css' / 'style.css').write_text(css, encoding='utf-8')
    shutil.copy2(ROOT / 'src' / 'app.js', DIST / 'assets' / 'js' / 'app.js')
    shutil.copy2(ROOT / 'src' / 'favicon.svg', DIST / 'assets' / 'favicon.svg')
    if (ROOT / 'admin').is_dir():
        shutil.copytree(ROOT / 'admin', DIST / 'admin')

    # home
    PFX = ''
    body = ''.join(SECTIONS[i]() for i in home_sections())
    seo = SEO
    title = seo.get('title') or 'Amjad Hani — Architects & Planners'
    write('index.html', page(title, seo.get('description', ''), body, canonical='', body_class='home'))
    urls = ['']
    for i, pr in enumerate(PROJECTS):
        write(f'projects/{pr["_slug"]}/index.html', project_page(pr, i))
        urls.append(f'projects/{pr["_slug"]}/')
    for i, sv in enumerate(SERVICES):
        write(f'services/{sv["_slug"]}/index.html', article_page('service', sv, i, SERVICES))
        urls.append(f'services/{sv["_slug"]}/')
    for i, n in enumerate(NEWS):
        write(f'news/{n["_slug"]}/index.html', article_page('news', n, i, NEWS))
        urls.append(f'news/{n["_slug"]}/')
    if NEWS:
        write('news/index.html', news_index())
        urls.append('news/')
    pv = SITE.get('privacy', {})
    if pv.get('body_en') or pv.get('body_ar'):
        write('privacy/index.html', privacy_page())
        urls.append('privacy/')
    write('404.html', not_found())
    if BASE_URL:
        sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(
            f'  <url><loc>{html.escape(BASE_URL + "/" + u)}</loc></url>\n' for u in urls) + '</urlset>\n'
        write('sitemap.xml', sm)
    write('robots.txt', 'User-agent: *\nAllow: /\nDisallow: /admin/\n' + (f'Sitemap: {BASE_URL}/sitemap.xml\n' if BASE_URL else ''))
    print(f'Built {len(urls)} pages -> {DIST}  (images saved: {saved // 1024} KB)')


if __name__ == '__main__':
    main()
