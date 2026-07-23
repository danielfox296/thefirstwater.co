# Firstwater — Design System v3 (2026-07-15 · reconciled 2026-07-22)
Ratified calls: ICE BLUE accent (dark grounds; --accent-on-light on paper) · DUOTONE stock interim ·
email capture LIVE — forms POST to events.thefirstwater.co, placeholder era over.
Reconciled 2026-07-22 against the shipped site and the 2026-07-21 personal reframe (audit FW-DES-4):
stale sections updated in place; three calls left [OPEN] for Daniel, marked inline and listed at the
end. All copy law lives in VOICE.md, not here.

## Tokens
--ink: #0A0B0D        (page ground, dark sections; also the <meta theme-color>)
--panel: #12151A      (cards, raised surfaces on dark)
--paper: #F5F7FA      (light sections, near-white)
--text-on-dark: #F5F7FA
--text-on-light: #0A0B0D
--gray: #98A1AB       (secondary text, both grounds)
--accent: #62B6E8     (ice blue — the "one light" as moonlight; links, CTAs, marks on DARK grounds:
                       8.8:1 on ink but 2.09:1 on paper — never text or UI on light)
--accent-on-light: #1F6FA8  (accessible blue: 5.02:1 on paper vs the 4.5:1 AA floor; every accent
                       role converts to it on light grounds — see Light-ground conversion)
--line: rgba(152,161,171,0.18)  (hairlines on dark; light sections use rgba(10,11,13,0.14) locally —
                       deliberate divergence from the calendar's light-ground --line, don't "reconcile")

## Light-ground conversion (RULE, 2026-07-22 — CAL-11 flowed back; fixes FW-DES-2/3)
Ice is the dark-ground identity. On paper every accent role converts; nothing ships ice-on-paper.
- Primary buttons: `.section--light .btn-primary` = ink fill / paper text (18.3:1); hover is an ice
  inset underline (`box-shadow: inset 0 -2px 0 var(--accent)`), never a fill swap. Dark grounds keep
  the ice fill + brightness hover.
- Links: `.section--light a { color: var(--accent-on-light) }` (the 2026-07-19 pass).
- Focus rings: global `:focus-visible` is a 2px ice outline; `.section--light` overrides it to
  --accent-on-light (non-text floor is 3:1; ice on paper is 2.09:1).
- Forms (ink-on-paper by construction): `.form-field` :focus outlines and the `.form-check input`
  accent-color take --accent-on-light.
- Accent text marks on paper convert: `.section--light .seq-n`, `.section--light
  .accordion-trigger::after`, `.section--light .step .step-k`.
CONTRAST FLOORS, written down: body text 4.5:1 · large text 3:1 · non-text UI (rings, marks) 3:1.

## Type
Display: Space Grotesk, two weights in use — 300 (hero + .page-hero H1, .seq-n numerals) and 700
(H2/H3, logo word). Hero clamp(2.6rem, 5.5vw, 4.2rem) single-line H1, no forced breaks (downsized
per Daniel 2026-07-19; was 9vw/7.5rem); interior .page-hero clamp(2.6rem, 6vw, 4.6rem); section H2
clamp(2rem, 4vw, 3.2rem). Weight 500 is loaded in base.html's fonts URL and used nowhere — drop it
or assign it (FW-DES-11).
Body: Inter 400/600 — 1.06rem / 1.7
Eyebrow: Inter 600, 0.75rem, letter-spacing 0.16em, uppercase, gray
RULE: adjacent elements never use adjacent scale steps — contrast is the aesthetic.

## Section contrast rhythm
Home: dark hero → light entity block → dark sound interlude → light "night, plainly" → dark capture
→ light FAQ teaser → dark footer.
Alternation is mandatory; two same-ground sections never touch.
EXEMPT: single-section utility pages (/thanks/, /thanks/inquiry/, 404) run one dark section into the
dark footer by design.

## Signature element (v2, 2026-07-19)
Cymatics: scroll-driven Chladni nodal-line canvas (ported from entuned.co), fixed
behind all content, drawn in ice/paper hairlines on the ink ground. Modes climb as
you scroll; visible through dark/transparent sections (hero edges, home interlude
band, footer, article margins). Line alphas ≤ .16 — it is a ground, not a graphic.
Replaced v1 waveform.svg underlay/divider and the generated-art photo band (removed).
(og.py share cards carry the favicon ripple mark + Space Grotesk type — the v1 waveform is retired
there too; full spec in Share cards below.)

## Share cards (OG)
scripts/og.py renders 1200x630 PNGs: ink ground, page title in paper, gray sub-line. img/og-default.png
is the sitewide fallback; per-page cards live at img/og/<slug>.png, wired via each config.json
og_image. The sub-line is the ratified footer line verbatim — "Come lie down. Leave moving forward."
(CANONICAL_SUB in og.py; canonical in VOICE.md, which names it the footer + share-card line). Titles
are existing page/session names; cards never get new copy.
Card craft (FW-DES-1, landed 2026-07-22): type is Space Grotesk from the vendored variable TTF
(scripts/assets/fonts/SpaceGrotesk-VF.ttf, SIL OFL) — title weight 500, shrink-to-fit so long session
names stay on one line; sub 400; ice letterspaced eyebrow 600. Motif is the favicon ripple mark
low-right (favicon.svg's ring progression — each ring ~1.9x the last, stroke halved, opacity x0.45 —
continued outward as fading hairlines), drawn at 2x and LANCZOS-downsampled. Helvetica + the v1 sine
waveform are retired.
Regen is manual: `python3 scripts/og.py` from the repo root, commit the PNGs — CI does not run scripts/.

## Favicon + app icons
img/favicon.svg is the mark of record (concentric ripple). PNG fallbacks are rendered from it —
favicon-32.png / favicon-16.png / apple-touch-icon.png (180, ink ground) — and linked from base.html
(FW-DES-9). Regen via qlmanage when the mark changes.

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
[OPEN — Daniel, FW-DES-12] The ink→ice grade undoes the warmth the subjects carry (candle flames
render glacial). Undecided: (1) accept the cold grade as the register and soften this rule's wording,
(2) add a warm-highlight duotone variant for photography while ice keeps UI/marks, or (3) wait for
the post-pilot shot list and re-grade then. The answer binds the calendar's imagery too.

## IA + naming (down the middle)
Nav (shipped): Sessions · About · FAQ · Blog · Corporate · [Hear first → /contact/#hear-first].
Footer adds Contact and the Eventbrite tickets link.
[OPEN — Daniel, FW-DES-4] Corporate's placement: top-level header item (shipped today) or
footer-only. The corporate channel itself is a decided keep; only its nav placement is open.
URLs: directory style — /sessions/healing-from-breakups/ · /about/ · /faq/ · /blog/ · /corporate/ · /contact/
Renames: Journal → Blog everywhere. CTA verbs (2026-07-21 reframe): "Hear first" (capture), "See the
sessions", "Send" (contact), "What happens" (ghost). Retired: "Get tickets", "Join the list" —
tickets live on Eventbrite (footer link; logistics card once a date exists).
Redirect stubs: journal.html → /blog/ ; sessions/breakups.html → /sessions/healing-from-breakups/ ;
/calendar/ and /calendar/event/* → soundbathcalendar.com (noindex, per-page canonicals).
Utility pages: /thanks/ is for actual list joins only ("You're on the list"); /thanks/inquiry/
receipts a plain note ("It's with me"); 404.html "Nothing here". All noindex,follow; the capture
service picks which thanks page you land on.

## Forms + capture
The hear-first capture (contact/#hear-first) POSTs to events.thefirstwater.co/subscribe; the contact
form to /inquiries. maxlength mirrors the service's caps (name 200 · email 320 · message 5000);
base.html carries a progressive double-submit guard with bfcache restore; the contact select leads
with a neutral "A note" option so casual notes aren't misfiled as bookings. (FW-UX-3/4/10.)

## Accessibility floor (shipped, checkable)
- 44px tap targets: .nav-cta, .mobile-menu-toggle.
- :focus-visible rings sitewide, ground-aware (see Light-ground conversion).
- Hero motion gated on the .js class — content stays visible with JS off; prefers-reduced-motion
  gets a static cymatics draw, no hero drift, no smooth scroll.
- Decorative imagery alt="" aria-hidden; in-article figures carry real alt.
- aria-expanded on menu + accordions · aria-current on active nav · aria-busy/disabled during submit.

## SEO / GEO
- JSON-LD: sitewide LocalBusiness (service-area Denver); WebSite on the homepage; FAQPage inline on
  /faq/ (hand-authored in the page section); Event schema on session pages ONCE a real date exists
  (not before). Blog posts: Article + author, plus build.py auto-extracts FAQPage from
  question-shaped H2s, HowTo from clearly procedural posts, VideoObject when a video embeds.
- Canonical entity block verbatim on home + about (text lives in VOICE.md).
- Answer-shaped first paragraphs on every page.
- OG images 1200x630 generated (see Share cards) so shares never render blank.
- robots.txt: allow all incl. GPTBot/PerplexityBot/ClaudeBot (ratified lean-yes) + Sitemap line;
  llms.txt page index at the root.
- Sitemap: per-page <lastmod> derived from git (last commit touching the page's sources; blog YAML
  last_updated/date wins when present); changefreq/priority dropped — crawlers ignore them (FW-CODE-1).
- IndexNow: changed-only pings after each deploy, diffed against a pre-deploy snapshot of the live
  sitemap (scripts/indexnow.py; key file at the site root; never fails the deploy).
- SITE_URL = https://thefirstwater.co; CNAME committed. Name + domain landed — placeholder era over.

## Page architecture (user-centric)
HOME (shipped): dark hero (hero-date slot "first dates being set" · H1 "Sound sessions in Denver." ·
first-person Daniel sub · See the sessions + What happens) → entity block → sound interlude → "The
night, plainly" .seq ×3 → hear-first capture block → cymatics band → FAQ teaser (3 Qs → /faq/).
Testimonial slots return post-pilot. The v1 duotone photo band and the join-the-list placeholder
are gone — capture is a real form (see Forms + capture).
SESSION PAGE: hook lede → the night → logistics card + one-click checkout, feed-driven
(sessions_feed.render_sessions_block emits them only when the cache holds a real date;
js/sessions.js upgrades live) → FAQ accordion.
[OPEN — Daniel, FW-DES-5] Sticky mobile CTA: spec'd 2026-07-15, never built. Build it before the
first on-sale date or strike it from this line — don't leave it ambiguous.
ABOUT: founder story + entity block + training line. The old "name-neutral" note is dead: the site
speaks as Daniel, also known as Firstwater (VOICE.md naming law).
FAQ: answer-shaped Qs (10 at reconciliation), FAQPage schema inline.
BLOG: listing grid with a real empty state; posts via the content.yaml pipeline.

## Build + deploy
v1's P1–P4 build order shipped in full (tokens/layout → imagery + OG → schema → pretty URLs).
Deploys are CI builds: GitHub Actions on push to main, plus repository_dispatch "sessions-updated"
from the events service so new dates rebuild the static site without a code push. Full-history
checkout (git lastmod needs it) → build.py → rsync minus scripts/ + build.py → IndexNow. Built
output tracked in the repo is an artifact of local builds; the CI rebuild is the deploy truth.
Generated assets CI does NOT rebuild (OG cards, favicon PNGs, duotone heroes) are produced locally
and committed.

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
MOVED: all copy voice law lives in VOICE.md (single source of truth, reconciled 2026-07-22 with the
2026-07-21 personal reframe). Design-relevant pointers — pointers, not duplicates:
- The site speaks as Daniel, also known as Firstwater (naming law; "D. Fox" is retired).
- A session is never a "room" (vocabulary law) — applies to alt text, aria labels, and card copy too.
- Canonical lines and the killed-lines list live there; the mystery-tagline family ("A dark room…",
  "…feel before you hear…") is dead everywhere, share cards included.
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

## OPEN — Daniel's calls (2026-07-22)
1. Sticky mobile session-page CTA (FW-DES-5): build before the first on-sale date, or strike the
   line from Page architecture. It has never existed in code.
2. Corporate nav placement (FW-DES-4): keep the top-level header item, or move to footer-only. The
   channel is a decided keep; placement is the only open part.
3. Imagery warmth (FW-DES-12): glacial ink→ice grade as the register, a warm-highlight duotone
   variant for photography (ice stays for UI/marks), or re-grade at the post-pilot shot list. The
   answer binds the calendar's imagery too.
