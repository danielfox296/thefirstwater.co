# Vendored fonts (local-only)

`SpaceGrotesk-VF.ttf` — Space Grotesk variable font, © 2020 The Space
Grotesk Project Authors (https://github.com/floriankarsten/space-grotesk),
licensed under the SIL Open Font License 1.1
(https://openfontlicense.org). File taken from Google Fonts
(https://github.com/google/fonts/tree/main/ofl/spacegrotesk) — the same
file the soundbathcalendar repo vendors under `scripts/assets/fonts/`.

Used by `scripts/og.py` to set the share-card type. The deploy workflow
excludes `scripts/`, so the font is never served — it exists only so the
committed OG PNGs can be regenerated locally.
