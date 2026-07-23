"""Generate 1200x630 OG images: the sitewide default plus one card per page.

Design: ink ground, the ripple mark low-right (img/favicon.svg traced —
concentric ice circles; each ring ~1.9x the last with stroke halving and
opacity decaying x0.45, continued outward as fading hairlines), page title
in Space Grotesk, canonical line as the sub. Titles are the existing
page/session names — no new copy.

LOCAL-only: needs Pillow + the vendored SpaceGrotesk-VF.ttf in
scripts/assets/fonts/ (SIL OFL 1.1 — see the README there). The PNGs are
committed and CI never regenerates them. Run from the repo root:

    python3 scripts/og.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
SS = 2  # supersample: draw at 2x, LANCZOS down — crisp ring strokes + type
INK = (10, 11, 13)
ICE = (98, 182, 232)
PAPER = (245, 247, 250)
GRAY = (152, 161, 171)
CANONICAL_SUB = 'Come lie down. Leave moving forward.'

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'assets', 'fonts', 'SpaceGrotesk-VF.ttf')


def _font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size * SS)
    f.set_variation_by_axes([weight])
    return f


def _ice(alpha):
    """Ice pre-blended onto the ink ground (uniform ground — no RGBA pass)."""
    return tuple(round(i + alpha * (c - i)) for i, c in zip(INK, ICE))


def _ripple(draw, cx, cy):
    """The favicon mark, scaled up and continued outward.

    favicon.svg is two concentric circles (r 5.5 -> 10.5, stroke 2 -> 1,
    opacity 1 -> 0.45 on a 32 box): each ring ~1.9x the last, stroke halved,
    opacity x0.45. The first two rings here are that mark; the rest continue
    the progression as hairline whispers running off the card.
    """
    rings = [
        (54, 5.0, 1.00),
        (103, 2.5, 0.45),
        (197, 1.5, 0.20),
        (376, 1.5, 0.10),
        (718, 1.5, 0.05),
    ]
    for r, stroke, alpha in rings:
        box = [(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS]
        draw.ellipse(box, outline=_ice(alpha), width=round(stroke * SS))


def _eyebrow(draw, x, y, text, font, tracking=4):
    """Letterspaced eyebrow (PIL has no tracking of its own)."""
    x *= SS
    for ch in text:
        draw.text((x, y * SS), ch, font=font, fill=ICE)
        x += draw.textlength(ch, font=font) + tracking * SS
    return x


def card(path, title, eyebrow=None, title_size=76):
    img = Image.new('RGB', (W * SS, H * SS), INK)
    d = ImageDraw.Draw(img)
    _ripple(d, 932, 470)

    # Shrink-to-fit: long session titles stay on one line inside the margin.
    size = title_size
    f_title = _font(size, 500)
    while d.textlength(title, font=f_title) > (W - 160) * SS and size > 40:
        size -= 4
        f_title = _font(size, 500)
    f_sub = _font(30, 400)

    y = 214
    if eyebrow:
        _eyebrow(d, 80, 150, eyebrow, _font(24, 600))
        y = 202
    d.text((80 * SS, y * SS), title, font=f_title, fill=PAPER)
    d.text((80 * SS, (y + size + 40) * SS), CANONICAL_SUB, font=f_sub,
           fill=GRAY)

    img = img.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    img.save(path, optimize=True)
    print(f'  ok {path}')


# Sitewide default (homepage + fallback)
card('img/og-default.png', 'FIRSTWATER')

# Per-page cards. Keys are image slugs; values are the page display titles.
PAGES = {
    'about': 'About',
    'faq': 'FAQ',
    'contact': 'Contact',
    'corporate': 'Corporate & groups',
    'sessions': 'Sessions',
    'blog': 'Blog',
    'sessions-healing-from-breakups': 'Healing from Breakups',
    'sessions-sunday-downshift': 'Sunday Downshift',
    'sessions-grief': 'Grief',
    'sessions-new-to-denver': 'New to Denver',
    'sessions-couples': 'Couples Reconnection',
    'sessions-quiet-new-years': "Quiet New Year's",
    'sessions-laid-off': 'Laid Off',
    'sessions-singles': 'Singles',
    'sessions-sleep': 'Sleep Descent',
}

for slug, title in PAGES.items():
    card(f'img/og/{slug}.png', title, eyebrow='FIRSTWATER')

print('og done')
