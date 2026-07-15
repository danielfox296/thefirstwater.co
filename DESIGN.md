# Sound Sessions — Design System v1 (2026-07-15)
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
Display: Space Grotesk 500/700 — hero clamp(3.5rem, 9vw, 7.5rem), section H2 clamp(2rem,4vw,3.2rem)
Body: Inter 400/600 — 1.06rem / 1.7
Eyebrow: Inter 600, 0.75rem, letter-spacing 0.16em, uppercase, gray
RULE: adjacent elements never use adjacent scale steps — contrast is the aesthetic.

## Section contrast rhythm
dark hero → light section → dark photo band → light FAQ → dark footer.
Alternation is mandatory; two same-ground sections never touch.

## Signature element
The rendered waveform of the 60-minute arc: thin ice-blue line (img/waveform.svg),
hero underlay + section divider. It is the product's fingerprint; keep it subtle (opacity ≤ .5).

## Photography
Interim: free-license stock, duotone-processed to ink/ice (scripts/duotone.py).
Art direction: dark rooms, mats on floors, speaker/gong macro, single practical light.
Post-pilot shot list replaces stock: wide room in session, gong detail, hands on mats, the light.
Conventions: img/hero/*.jpg 1600px, ≤500KB, WebP preferred, alt text mandatory.

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
