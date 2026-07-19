"""Generate 1200x630 OG images: the sitewide default plus one card per page.

Design: ink ground, ice waveform line, page title as headline, canonical
line as the sub. Titles are the existing page/session names — no new copy.
Run from the repo root: python3 scripts/og.py
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
INK = (10, 11, 13)
ICE = (98, 182, 232)
PAPER = (245, 247, 250)
GRAY = (152, 161, 171)
CANONICAL_SUB = 'A dark room. One light. Sound you feel before you hear.'


def _fonts(title_size):
    try:
        f_title = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', title_size)
        f_sub = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 30)
        f_eyebrow = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 24)
    except Exception:
        f_title = f_sub = f_eyebrow = ImageFont.load_default()
    return f_title, f_sub, f_eyebrow


def _wave(draw):
    pts = [(x, 430 + 60 * math.sin(x / 70) * math.exp(-((x - 700) / 420) ** 2))
           for x in range(0, W, 4)]
    draw.line(pts, fill=ICE, width=3)


def card(path, title, eyebrow=None, title_size=76):
    img = Image.new('RGB', (W, H), INK)
    d = ImageDraw.Draw(img)
    _wave(d)
    f_title, f_sub, f_eyebrow = _fonts(title_size)
    y = 180
    if eyebrow:
        d.text((80, 140), eyebrow, font=f_eyebrow, fill=GRAY)
        y = 196
    d.text((80, y), title, font=f_title, fill=PAPER)
    d.text((80, y + title_size + 34), CANONICAL_SUB, font=f_sub, fill=GRAY)
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
