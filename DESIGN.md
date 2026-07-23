# Firstwater — Design System v1 (2026-07-15)
Ratified calls: ICE BLUE accent · DUOTONE stock interim · email = placeholder until Daniel sets up provider.

## Tokens
--ink: #0A0B0D        (page ground, dark sections)
--panel: #12151A      (cards, raised surfaces on dark)
--paper: #F5F7FA      (light sections, near-white)
--text-on-dark: #F5F7FA
--text-on-light: #0A0B0D
--gray: #98A1AB       (secondary text, both grounds)
--accent: #62B6E8     (ice blue — the "one light" as moonlight; links, CTAs, waveform)
--line: rgba(152,161,171,0.18)

## Type
Display: Space Grotesk 500/700 — hero clamp(2.6rem, 5.5vw, 4.2rem) single-line H1, no forced breaks (downsized per Daniel 2026-07-19; was 9vw/7.5rem), section H2 clamp(2rem,4vw,3.2rem)
Body: Inter 400/600 — 1.06rem / 1.7
Eyebrow: Inter 600, 0.75rem, letter-spacing 0.16em, uppercase, gray
RULE: adjacent elements never use adjacent scale steps — contrast is the aesthetic.

## Section contrast rhythm
dark hero → light section → dark photo band → light FAQ → dark footer.
Alternation is mandatory; two same-ground sections never touch.

## Signature element (v2, 2026-07-19)
Cymatics: scroll-driven Chladni nodal-line canvas (ported from entuned.co), fixed
behind all content, drawn in ice/paper hairlines on the ink ground. Modes climb as
you scroll; visible through dark/transparent sections (hero edges, home interlude
band, footer, article margins). Line alphas ≤ .16 — it is a ground, not a graphic.
Replaced v1 waveform.svg underlay/divider and the generated-art photo band (removed).
(og.py share cards carry the favicon ripple mark + Space Grotesk type — the v1 waveform is retired there too.)

## Photography
Interim: Unsplash stock, duotone-processed to ink/ice (scripts/duotone.py).
Source photo IDs recorded in img/hero/SOURCES.md.
Every page carries a hero image: full-bleed .hero-media + directional ink scrim
(readability left, image reads right); session pages carry an in-article hero
figure via content.yaml hero: block. Hero background imgs are decorative
(alt="" aria-hidden); in-article figures carry real alt text.
Art direction: dark rooms, mats on floors, speaker/gong macro, single practical light.
WARMTH RULE (Daniel, 2026-07-19): imagery must read warm, beautiful, held — the venue
reality is warm yoga studios. Never institutional, abandoned, or eerie: no empty metal
beds, no bare rooms with harsh glare, no vacant seating. Soft fabric, plants, wood,
candles, human presence survive the duotone; emptiness turns sinister under it.
Post-pilot shot list replaces stock: wide room in session, gong detail, hands on mats, the light.
Conventions: img/hero/*.jpg 1600px, ≤500KB, WebP preferred.

## IA + naming (down the middle)
Nav: Sessions · About · FAQ · Blog · [Get tickets]
URLs: directory style — /sessions/healing-from-breakups/ · /about/ · /faq/ · /blog/
Renames: Journal → Blog everywhere. CTA verbs: "Get tickets", "Join the list".
Redirect stubs: journal.html → /blog/ ; sessions/breakups.html → /sessions/healing-from-breakups/

## SEO / GEO
- JSON-LD: sitewide LocalBusiness (service-area Denver) replacing inherited B2B org schema;
  FAQPage inline on /faq/; Event schema on session pages ONCE a real date exists (not before);
  Article + Person on blog posts (renderer already emits article basics).
- Canonical entity block verbatim on home + about (name slot pending).
- Answer-shaped first paragraphs on every page. Pronunciation FAQ waits for the name.
- OG images 1200x630 generated (scripts/og.py) so shares never render blank.
- robots.txt: allow all incl. GPTBot/PerplexityBot/ClaudeBot (ratified lean-yes). Sitemap line.
- SITE_URL placeholder until domain; set it + CNAME the day the name lands.

## Page architecture (user-centric)
HOME: hero(hook + next-date slot + Get tickets) → duotone photo band → "The night" 3 steps →
testimonial slots (post-pilot) → FAQ teaser (3 Qs) → Join-the-list placeholder.
SESSION PAGE: hook lede → the night → logistics card → FAQ accordion → sticky mobile CTA.
ABOUT: founder story (Version B adapted, name-neutral) + entity block + training line.
FAQ: 7 answer-shaped Qs, FAQPage schema.
BLOG: listing grid, posts via content.yaml pipeline (unchanged).

## Build order
P1 tokens/layout rewrite → P2 imagery + waveform + OG → P3 schema + FAQ/About →
P4 pretty URLs + redirects + Blog rename. Email capture: placeholder block, provider TBD.

## AI design-tell audit (researched 2026-07-15)
Root cause per Anthropic's frontend-aesthetics cookbook: distributional
convergence — unprompted models emit the statistical average ("AI slop").
Tells found in OUR v1 → fixes applied:
1. Three identical cards in a row (steps grid) → asymmetric staggered
   sequence, oversized thin numerals, hairline rules, no card boxes
2. Reflexive glassmorphism (header backdrop-blur) → solid ink + hairline
3. Uniform border-radius everywhere → radius 0, sharp editorial edges
4. Copy-paste motion (fade-up on everything) → motion in the hero only
5. Timid weight contrast → weight extremes (display 300 vs 700), 3x+ size jumps
6. Zero asymmetry / flat section rhythm → staggered offsets, varied padding
Already avoided: purple-indigo gradient, centered hero, emoji bullets,
icon-in-rounded-square, shadcn defaults, four-col footer, "Get Started" copy.
Kept by Daniel's order: Space Grotesk/Inter, ink/ice palette (Inter is a tell
only as a solo system; locked under a distinct display face it stays).

## Copy laws
MOVED: all copy voice law now lives in VOICE.md (single source of truth).
Historical note below retained for context; VOICE.md wins on any conflict.

### (superseded by VOICE.md)
- CONCEPTUAL AGENCY BAN: abstractions never take verbs. "Sound arrives,"
  "the mind argues," "the room works on you," "your body knows" — all dead.
  The reader and the facilitator are the only agents. Sound may act ONLY as
  literal physics (pressure in a chest). "Your body / your mind" as characters
  is the deepest wellness-copy tell; people feel, drop, come back, put down.
- No em dashes in site copy (writing-voice law, applies here too).
- No apology, no defensive disclosure: "not therapy" never appears in site
  copy. Waiver + resource card are door objects, not marketing.
