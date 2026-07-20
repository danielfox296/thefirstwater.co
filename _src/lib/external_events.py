"""External sound-events feed loader + calendar renderer for build.py.

The Front Range calendar (/calendar/) lists sound events run by other
operators alongside Firstwater's own dated sessions. At build time we:
  1. fetch the calendar feed (env CALENDAR_FEED_URL, default: the events
     service /feeds/calendar.json, which serves APPROVED events only),
  2. validate its shape and write it to data/external-events.json
     (committed, deterministic formatting) so every future build has a
     known-good copy,
  3. on ANY fetch/parse/validation failure: warn and fall back to the
     committed data/external-events.json, then to an empty feed. A broken
     feed never breaks the build.

INTERIM (Week 1) note: /feeds/calendar.json does not exist yet. Until the
service ships it, the fetch fails on every build and we fall back to the
committed data/external-events.json — which the pull agent writes as a PR
and Daniel reviews. That committed file is BOTH the interim source of truth
AND the eventual cache: once the service serves the feed, a successful HTTP
fetch overwrites it (same discipline as sessions_feed + data/sessions-cache.json).
Set CALENDAR_FEED_FILE=/abs/path to build against a local fixture without
ever touching the committed file.

Stdlib only — no new dependencies. Date/time formatting and the Firstwater
Event builder are reused from sessions_feed so the two feeds never drift.

FEED CONTRACT (GET {CALENDAR_FEED_URL}), shape:
{ "generated_at": "<ISO>", "events": [ {
    "name","operator","starts_at","venue","address",
    "city": "Denver|Boulder|Fort Collins|Colorado Springs",
    "neighborhood": <str|null>,
    "price","ticket_url","source_url","tags":[...],
    "confidence": <0..1>, "dedup_key","status","note","rejection_note",
    # v2 (all optional; "" when unknown):
    "image_url",       # listing image / flyer (og:image). http(s) only, scrubbed.
    "facilitator",     # the PERSON leading the session (distinct from operator).
    "operator_url",    # the operator's OWN page. http(s) only, scrubbed.
    "venue_url",       # the venue's OWN page, when distinct. http(s) only, scrubbed.
    "description" } ] }# factual, original 1-2 sentence description of the event.
Timestamps ISO-8601 with offset (America/Denver local). Only status="approved"
events are ever rendered; candidate/rejected never leave the service and are
filtered here too as a belt-and-braces guard.

NOTE vs DESCRIPTION: `note` is Daniel's editorial one-liner (his opinion, his
voice, verbatim only, usually empty) — the moat. `description` is a NEUTRAL
FACTUAL sentence stating what the event IS, never whether it's good. When
`description` is empty the build synthesizes a deterministic TEMPLATE
description from the structured fields (see template_description) so no row or
permalink is ever thin. Precedence for any descriptive text: `note` is the
editorial line (rendered distinctly), description-or-template is the factual
line (always rendered).
"""

import html
import json
import os
import re
import unicodedata
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from _src.lib import sessions_feed
from _src.lib.sessions_feed import DENVER, parse_iso

DEFAULT_FEED_URL = 'https://events.thefirstwater.co/feeds/calendar.json'
CACHE_REL_PATH = os.path.join('data', 'external-events.json')
FETCH_TIMEOUT_S = 10

# Canonical section keys, in the fixed render order (geography → time).
CITIES = ('Denver', 'Boulder', 'Fort Collins', 'Colorado Springs')
# Anchor ids for the in-page jump nav (must match sections/01-content.html).
CITY_ANCHOR = {
    'Denver': 'denver',
    'Boulder': 'boulder',
    'Fort Collins': 'fort-collins',
    'Colorado Springs': 'colorado-springs',
}
# Query-language H2 per area ("sound baths", the attendee word — never
# "sound healing", which splits intent on a transactional surface).
CITY_H2 = {
    'Denver': 'Sound baths in Denver this week',
    'Boulder': 'Sound baths in Boulder this week',
    'Fort Collins': 'Sound baths in Fort Collins this week',
    'Colorado Springs': 'Sound baths in Colorado Springs this week',
}

# Nearby suburbs fold into the nearest canonical section (spec mapping). Only
# used when a row's city is not already canonical, or to place a Firstwater
# session from its free-text venue address.
_SUBURB_TO_CITY = {
    'lakewood': 'Denver', 'arvada': 'Denver', 'aurora': 'Denver',
    'centennial': 'Denver', 'englewood': 'Denver', 'littleton': 'Denver',
    'wheat ridge': 'Denver', 'golden': 'Denver', 'thornton': 'Denver',
    'westminster': 'Denver', 'commerce city': 'Denver', 'broomfield': 'Denver',
    'highlands ranch': 'Denver', 'parker': 'Denver', 'castle rock': 'Denver',
    'lone tree': 'Denver', 'brighton': 'Denver', 'northglenn': 'Denver',
    'longmont': 'Boulder', 'louisville': 'Boulder', 'lafayette': 'Boulder',
    'superior': 'Boulder', 'nederland': 'Boulder', 'erie': 'Boulder',
    'loveland': 'Fort Collins', 'windsor': 'Fort Collins',
    'greeley': 'Fort Collins', 'wellington': 'Fort Collins',
    'berthoud': 'Fort Collins', 'timnath': 'Fort Collins',
    'manitou springs': 'Colorado Springs', 'monument': 'Colorado Springs',
    'fountain': 'Colorado Springs', 'woodland park': 'Colorado Springs',
}

# Statuses that render. Anything else (candidate/rejected/unknown) is dropped.
RENDER_STATUS = 'approved'


# ---------------------------------------------------------------------------
# Normalization / dedup key (contract algorithm — also used by the pull agent
# and the seed generator, kept here as the single source of truth)
# ---------------------------------------------------------------------------

def normalize(s):
    """lowercase, strip accents/diacritics, drop non-alphanumeric-non-space
    chars, collapse whitespace to single spaces, trim.

    Whitespace is collapsed to a single space BEFORE the non-alnum strip so that
    a scrape artifact — a tab/newline/exotic-space wedged between two words —
    becomes a separator, not a glue: "Full Moon\nSound" -> "full moon sound",
    never "full moonsound". This keeps the dedup_key byte-identical to the
    authoritative service impl (TS `[^a-z0-9\\s]`), which is the whole point of
    the shared key. (Python `\\s` matches the whitespace a real listing produces;
    a zero-width U+FEFF between words is the one theoretical residual and does not
    occur in listing data.)"""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def make_dedup_key(name, date_yyyy_mm_dd, venue):
    """normalize(name) + '|' + YYYY-MM-DD (America/Denver) + '|' + normalize(venue)."""
    return f'{normalize(name)}|{date_yyyy_mm_dd}|{normalize(venue)}'


def map_city(text):
    """Fold a free-text city/address to one canonical section key.

    Exact canonical match wins; then a known-suburb substring; else Denver
    (the metro that anchors the calendar). Only used for non-canonical input.
    """
    if not text:
        return 'Denver'
    t = text.strip().lower()
    for c in CITIES:
        if c.lower() in t:
            return c
    for suburb, city in _SUBURB_TO_CITY.items():
        if suburb in t:
            return city
    return 'Denver'


# ---------------------------------------------------------------------------
# Loading (mirrors sessions_feed.load_feed precedence + graceful fallback)
# ---------------------------------------------------------------------------

def empty_feed():
    return {'generated_at': None, 'events': []}


def validate_feed(feed):
    """Shape-check a parsed feed. Raises ValueError on any problem.

    Load-bearing fields only: each event needs a non-empty string name, a
    parseable offset-aware starts_at, a string status, and a string city.
    Everything else has a safe render-time default.
    """
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('events'), list):
        raise ValueError('feed.events is not a list')
    for i, e in enumerate(feed['events']):
        where = f'events[{i}]'
        if not isinstance(e, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('name', 'starts_at', 'status', 'city'):
            if not isinstance(e.get(key), str) or not e[key]:
                raise ValueError(f'{where}.{key} missing or not a string')
        parse_iso(e['starts_at'])
    return feed


def _write_cache(cache_path, feed):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(feed, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def _load_cache(cache_path, log):
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return validate_feed(json.load(f))
    except Exception as exc:  # missing or corrupt cache: build must still succeed
        log(f'  ⚠ external-events cache unusable ({exc.__class__.__name__}: {exc}) — building with no external events')
        return empty_feed()


def load_feed(repo_root, log=print):
    """Return the external-events feed dict, never raising.

    Order of precedence:
      CALENDAR_FEED_FILE (local fixture, committed file untouched)
      > CALENDAR_FEED_URL fetch (http(s) success refreshes the committed file)
      > committed data/external-events.json
      > empty feed.
    """
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('CALENDAR_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ calendar feed from fixture {fixture} ({len(feed["events"])} event(s); committed file untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ CALENDAR_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed data/external-events.json')
            return _load_cache(cache_path, log)

    url = os.environ.get('CALENDAR_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ calendar feed unavailable at {url} ({exc.__class__.__name__}) — using committed data/external-events.json')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ calendar feed fetched ({len(feed["events"])} event(s)) — committed file refreshed')
    else:
        log(f'  ✓ calendar feed from {url} ({len(feed["events"])} event(s); committed file untouched)')
    return feed


# ---------------------------------------------------------------------------
# Time helpers (America/Denver) — thin wrappers over sessions_feed idioms so
# both feeds format dates identically.
# ---------------------------------------------------------------------------

def _denver(ts):
    return sessions_feed._denver(ts)


def _day(n):
    return sessions_feed._day(n)


def fmt_row_date(ts):
    """Compact dated-row label: 'Fri, Jul 24'."""
    d = _denver(ts)
    return f'{d.strftime("%a")}, {d.strftime("%b")} {_day(d.strftime("%d"))}'


def fmt_time(ts):
    return sessions_feed.fmt_time(ts)


def fmt_stamp_date(now):
    """'Last updated' stamp date in America/Denver: 'July 19, 2026'."""
    d = now.astimezone(DENVER)
    return f'{d.strftime("%B")} {_day(d.strftime("%d"))}, {d.year}'


def stamp_date_iso(now):
    """The same stamp date as an ISO date (America/Denver): '2026-07-19'.
    Used for schema.org dateModified so it matches the visible stamp."""
    return now.astimezone(DENVER).date().isoformat()


def _now_utc(now):
    return now or datetime.now(timezone.utc)


def current_now():
    """Shared build-time 'now' (UTC-aware) so the weekend window, past-event
    drop, and 'Last updated' stamp all agree within one build."""
    return datetime.now(timezone.utc)


def weekend_window(now=None):
    """(start, end) datetimes bounding the relevant weekend in America/Denver.

    Mon–Thu -> the upcoming Fri 00:00 through Sun 23:59.
    Fri/Sat/Sun -> the weekend in progress (its own Fri 00:00 through Sun 23:59).
    """
    local = _now_utc(now).astimezone(DENVER)
    # weekday(): Mon=0 .. Fri=4, Sat=5, Sun=6. days_to_fri is 0 or negative on
    # Fri/Sat/Sun (this weekend's Friday), positive Mon–Thu (upcoming Friday).
    days_to_fri = 4 - local.weekday()
    fri = (local + timedelta(days=days_to_fri)).date()
    sun = fri + timedelta(days=2)
    start = datetime(fri.year, fri.month, fri.day, 0, 0, 0, tzinfo=DENVER)
    end = datetime(sun.year, sun.month, sun.day, 23, 59, 59, tzinfo=DENVER)
    return start, end


# ---------------------------------------------------------------------------
# Row model — one normalized dict per rendered event, external or Firstwater.
# ---------------------------------------------------------------------------

def _external_row(e):
    city = e.get('city') if e.get('city') in CITIES else map_city(e.get('city') or e.get('address') or '')
    return {
        'kind': 'external',
        'name': e.get('name', ''),
        'operator': e.get('operator', ''),
        'starts_at': e['starts_at'],
        'city': city,
        'venue': e.get('venue', ''),
        'neighborhood': e.get('neighborhood') or None,
        'address': e.get('address', ''),
        'price': e.get('price', ''),
        'note': e.get('note', '') or '',
        'ticket_url': e.get('ticket_url', '') or e.get('source_url', ''),
        'source_url': e.get('source_url', ''),
        'tags': e.get('tags', []) or [],
        'dedup_key': e.get('dedup_key', ''),
        # v2 fields — the three URLs are scheme-scrubbed exactly like ticket_url
        # (attacker-influenced third-party listing data on a public page).
        'image_url': _safe_ext_url(e.get('image_url', '')),
        'facilitator': (e.get('facilitator', '') or '').strip(),
        'operator_url': _safe_ext_url(e.get('operator_url', '')),
        'venue_url': _safe_ext_url(e.get('venue_url', '')),
        'description': (e.get('description', '') or '').strip(),
        '_ext': e,
        '_sess': None,
        '_event_title': None,
    }


# Nicer display names for the known Firstwater session slugs; any other slug
# falls back to a title-cased form of the slug itself.
_SESSION_TITLES = {
    'healing-from-breakups': 'Healing from Breakups',
    'sunday-downshift': 'Sunday Downshift',
    'grief': 'Grief',
    'new-to-denver': 'New to Denver',
    'couples': 'Couples Reconnection',
    'quiet-new-years': "Quiet New Year's",
    'laid-off': 'Laid Off',
    'singles': 'Singles',
    'sleep': 'Sleep Descent',
}


def _session_title(slug):
    return _SESSION_TITLES.get(slug) or slug.replace('-', ' ').title()


def _session_price(s):
    """Cheapest-tier price string for a Firstwater row, or ''."""
    tiers = s.get('tiers') or []
    cents = None
    for t in tiers:
        if t.get('mode') == 'sliding':
            amt = t.get('min_amount') or t.get('suggested_amount') or t.get('amount')
            prefix = 'from '
        else:
            amt = t.get('amount')
            prefix = 'from ' if len(tiers) > 1 else ''
        if amt is None:
            continue
        if cents is None or amt < cents:
            cents = amt
            best_prefix = prefix
    if cents is None:
        return ''
    money = sessions_feed.fmt_money(cents)
    return f'{best_prefix}{money}' if money else ''


def _firstwater_row(s):
    slug = s.get('event_slug', '')
    venue = (s.get('venue') or {}).get('name', '') or ''
    address = (s.get('venue') or {}).get('address', '') or ''
    title = _session_title(slug)
    return {
        'kind': 'firstwater',
        'name': title,
        'operator': 'Firstwater',
        'starts_at': s['starts_at'],
        'city': map_city(address or venue),
        'venue': venue,
        'neighborhood': None,
        'address': address,
        'price': _session_price(s),
        'note': '',
        'ticket_url': f'sessions/{slug}/',   # internal; nav_prefix applied at render
        'source_url': '',
        'tags': [],
        'dedup_key': f'firstwater|{slug}|{_denver(s["starts_at"]).strftime("%Y-%m-%d")}',
        # v2 fields — Firstwater rows carry no listing image (their distinction is
        # treatment, not a flyer) and link to their own rich session page; the
        # factual line still renders from the template. facilitator/urls stay
        # empty here (the session page is authoritative for its own detail).
        'image_url': '',
        'facilitator': '',
        'operator_url': '',
        'venue_url': '',
        'description': '',
        '_ext': None,
        '_sess': s,
        '_event_title': title,
    }


def build_rows(cal_feed, sessions_feed_data, now=None):
    """Normalized, future, de-duplicated rows for the calendar.

    External: status='approved' AND starts in the future.
    Firstwater: sessions_feed DISPLAY_STATUSES AND future.
    Rejected/candidate external events and past events never appear.
    """
    now = _now_utc(now)
    rows = []

    for e in (cal_feed or {}).get('events', []):
        if e.get('status') != RENDER_STATUS:
            continue
        try:
            if parse_iso(e['starts_at']) <= now:
                continue
        except (KeyError, ValueError):
            continue
        rows.append(_external_row(e))

    for s in (sessions_feed_data or {}).get('sessions', []):
        if s.get('status') not in sessions_feed.DISPLAY_STATUSES:
            continue
        try:
            if parse_iso(s['starts_at']) <= now:
                continue
        except (KeyError, ValueError):
            continue
        rows.append(_firstwater_row(s))

    # Defensive de-dup within the external feed (server already dedups; this
    # guards a hand-edited feed): first occurrence by dedup_key, then by
    # ticket_url, wins.
    #
    # Cross-feed guard: external and Firstwater rows use structurally disjoint
    # dedup_keys (content-based vs 'firstwater|slug|date') and disjoint
    # ticket_urls (Eventbrite vs internal session path), so the two guards above
    # never catch the SAME real event surfacing in both feeds — e.g. a Firstwater
    # session an operator also cross-posts to Eventbrite. Firstwater is
    # authoritative for its own sessions, so drop any external row whose canonical
    # normalize(name)+date+normalize(venue) matches a Firstwater row. Best-effort:
    # a scraped listing whose title/venue text differs from the session's curated
    # title/venue won't match — source-level exclusion in the pull agent is the
    # primary guard; this only catches the clean, identical cross-post.
    def _content_key(r):
        day = _denver(r['starts_at']).strftime('%Y-%m-%d')
        return make_dedup_key(r['name'], day, r['venue'])

    firstwater_content = {
        _content_key(r) for r in rows if r['kind'] == 'firstwater'
    }

    seen_keys, seen_urls, deduped = set(), set(), []
    for r in rows:
        k = r.get('dedup_key') or ''
        u = r.get('ticket_url') or ''
        if k and k in seen_keys:
            continue
        if u and r['kind'] == 'external' and u in seen_urls:
            continue
        if r['kind'] == 'external' and _content_key(r) in firstwater_content:
            continue
        if k:
            seen_keys.add(k)
        if u and r['kind'] == 'external':
            seen_urls.add(u)
        deduped.append(r)

    deduped.sort(key=lambda r: parse_iso(r['starts_at']))
    return deduped


def group_by_city(rows):
    """OrderedDict city -> rows (chronological), fixed CITIES order, all keys present."""
    groups = OrderedDict((c, []) for c in CITIES)
    for r in rows:
        groups.get(r['city'], groups['Denver']).append(r)
    for c in groups:
        groups[c].sort(key=lambda r: parse_iso(r['starts_at']))
    return groups


def weekend_rows(rows, now=None):
    """Rows whose start falls inside the relevant weekend window, chronological."""
    start, end = weekend_window(now)
    out = [r for r in rows if start <= parse_iso(r['starts_at']).astimezone(DENVER) <= end]
    out.sort(key=lambda r: parse_iso(r['starts_at']))
    return out


def week_rows(rows, now=None):
    """Rows starting within the next seven days — the 'this week' answer window
    used by the machine-extractable summary sentence."""
    now = _now_utc(now)
    end = now + timedelta(days=7)
    out = [r for r in rows if now < parse_iso(r['starts_at']) <= end]
    out.sort(key=lambda r: parse_iso(r['starts_at']))
    return out


# ---------------------------------------------------------------------------
# Factual description (field-or-template), editorial note, alt text, slugs.
# The template is the deterministic FALLBACK used when a row carries no authored
# `description`: a clean, factual sentence built from the structured fields so
# every row and permalink renders non-thin. It never evaluates the event (no
# praise, no woo) — that is `note`'s job, and `note` is Daniel's verbatim alone.
# ---------------------------------------------------------------------------

# Tag -> lead noun phrase, most specific first. Theme modifiers (e.g.
# "moon-themed") are intentionally skipped: the lead states the FORMAT.
_LEAD_PHRASES = (
    ('gong', 'A gong bath'),
    ('breathwork+sound', 'A breathwork and sound session'),
    ('guided-meditation', 'A guided meditation with sound'),
    ('meditation+sound', 'A guided meditation with sound'),
    ('sound-forward yoga', 'A sound-forward yoga session'),
    ('yoga+sound', 'A sound-forward yoga session'),
    ('singing-bowl', 'A singing-bowl session'),
    ('sound healing', 'A sound healing session'),
    ('sound bath', 'A sound bath'),
)


def _lead_phrase(tags):
    tset = {str(t).lower() for t in (tags or [])}
    for tag, phrase in _LEAD_PHRASES:
        if tag in tset:
            return phrase
    return 'A sound session'


def _price_phrase(price):
    """A factual price sentence, or '' when the price is unknown. Mirrors the
    JSON-LD price reading (accurate or absent) so the sentence never guesses."""
    kind = _parse_price(price)
    if kind[0] == 'free':
        return 'Free to attend.'
    if kind[0] == 'fixed':
        return f'Tickets are ${_fmt_price_num(kind[1])}.'
    if kind[0] == 'range':
        return f'Tickets ${_fmt_price_num(kind[1])}–${_fmt_price_num(kind[2])}.'
    if price and _DONATION_RE.search(price):
        return 'Offered by donation.'
    return ''


def template_description(row):
    """Deterministic factual sentence for a row from its structured fields.

    Shape: "{lead}{ led by F}{ at V}{ in P}, {Weekday} at {time}. {price}."
    Clean and natural, never robotic, never editorial. Always non-empty (the
    lead and day/time always resolve), so it is a safe fallback for an empty
    authored `description`.
    """
    clause = [_lead_phrase(row.get('tags'))]
    facilitator = (row.get('facilitator') or '').strip()
    if facilitator:
        clause.append(f'led by {facilitator}')
    venue = (row.get('venue') or '').strip()
    if venue:
        clause.append(f'at {venue}')
    place = row.get('neighborhood') if row.get('city') == 'Denver' else row.get('city')
    if place and normalize(place) not in normalize(venue):
        clause.append(f'in {place}')
    d = _denver(row['starts_at'])
    when = f'{d.strftime("%A")} at {fmt_time(row["starts_at"])}'
    sentence = f'{" ".join(clause)}, {when}.'
    price = _price_phrase(row.get('price', ''))
    return f'{sentence} {price}' if price else sentence


def factual_description(row):
    """The factual line: the authored `description` when present, else the
    deterministic template. Always non-empty."""
    return (row.get('description') or '').strip() or template_description(row)


def editorial_note(row):
    """Daniel's verbatim one-liner, or '' — never synthesized. External rows
    only (a Firstwater row speaks on its own session page)."""
    if row.get('kind') == 'external':
        return (row.get('note') or '').strip()
    return ''


def alt_text(row):
    """Factual ALT/caption text: '{name} — {operator} at {venue}, {place}'.
    Degrades cleanly when operator/venue/place are missing (functional locator
    string, not body copy; the em dash follows the spec's mandated shape)."""
    name = (row.get('name') or '').strip()
    op = (row.get('operator') or '').strip()
    venue = (row.get('venue') or '').strip()
    place = row.get('neighborhood') if row.get('city') == 'Denver' else row.get('city')
    place = (place or row.get('city') or '').strip()
    loc = op
    # An operator running its own room (operator == venue) shows the name once.
    if venue and normalize(venue) != normalize(op):
        loc = f'{loc} at {venue}' if loc else venue
    if place:
        loc = f'{loc}, {place}' if loc else place
    return f'{name} — {loc}' if loc else name


# dedup_key is already normalized (lowercase alnum + spaces + '|'); collapse
# every run of non-alnum to one hyphen for a stable, URL-safe permalink slug.
_SLUG_STRIP_RE = re.compile(r'[^a-z0-9]+')


def event_slug(row):
    """Stable URL-safe slug from the dedup_key. Deterministic across builds."""
    return _SLUG_STRIP_RE.sub('-', (row.get('dedup_key') or '').lower()).strip('-')


def event_permalink_path(row):
    """Site-relative permalink path for an external event page (trailing slash)."""
    return f'calendar/event/{event_slug(row)}/'


def event_permalink_url(row, site_url):
    return f'{site_url}/{event_permalink_path(row)}'


def _price_span(rows):
    """(low_label, high_num) across rows' readable prices, or ('', None).
    Free counts as 0; unreadable/donation prices are skipped."""
    lo = hi = None
    for r in rows:
        kind = _parse_price(r.get('price', ''))
        nums = []
        if kind[0] == 'free':
            nums = [0.0]
        elif kind[0] == 'fixed':
            nums = [kind[1]]
        elif kind[0] == 'range':
            nums = [kind[1], kind[2]]
        for n in nums:
            lo = n if lo is None else min(lo, n)
            hi = n if hi is None else max(hi, n)
    if hi is None:
        return ('', None)
    lo_label = 'free' if lo == 0 else f'${_fmt_price_num(lo)}'
    return (lo_label, hi)


def build_summary_sentence(rows, now=None):
    """Machine-extractable answer-first sentence for the top of /calendar/.

    Counts sessions starting in the next seven days, per city, with a price
    span. Rebuilt every build so it always matches the live list.
    """
    wk = week_rows(rows, now)
    n = len(wk)
    if n == 0:
        return ('No sessions are on the Front Range calendar for the next seven '
                'days yet; the weeks ahead are listed below.')
    counts = OrderedDict((c, 0) for c in CITIES)
    for r in wk:
        counts[r['city']] = counts.get(r['city'], 0) + 1
    parts = [f'{cnt} in {c}' for c, cnt in counts.items() if cnt]
    if len(parts) > 1:
        breakdown = ', '.join(parts[:-1]) + ', and ' + parts[-1]
    else:
        breakdown = parts[0]
    noun = 'session' if n == 1 else 'sessions'
    sent = f'This week on the Front Range: {n} sound {noun}, {breakdown}'
    lo_label, hi = _price_span(wk)
    if hi is not None:
        sent += f', priced {lo_label} to ${_fmt_price_num(hi)}'
    return sent + '.'


# Register-passable PLACEHOLDER FAQ (flagged for Daniel). Factual, no praise,
# no woo — the GEO/AIO citation surface. Answers double as FAQPage JSON-LD.
CALENDAR_FAQ = (
    {
        'q': 'What is a sound bath?',
        'a': ('A sound bath is a session where you lie down, usually on a mat, '
              'while a facilitator plays instruments such as gongs, singing '
              'bowls, and chimes. Most run 45 to 75 minutes, and you stay '
              'clothed and still the whole time. This calendar also covers close '
              'relatives like gong baths, breathwork with sound, and guided '
              'meditations played on live instruments.'),
    },
    {
        'q': 'How much do sound baths cost on the Front Range?',
        'a': ('Most sessions in Denver, Boulder, Fort Collins, and Colorado '
              'Springs run between $20 and $55. Some are offered by donation or '
              'free. Each listing shows its own price, and the ticket link goes '
              'straight to the operator.'),
    },
    {
        'q': 'What should I bring to a sound bath?',
        'a': ('Wear clothes you can lie down in. Many rooms provide mats, '
              'bolsters, and blankets, though your own blanket, a pillow, and '
              'water are never wrong. When in doubt, the operator’s listing '
              'says what the room supplies.'),
    },
)


def render_faq_html():
    """Always-visible FAQ block (better for AI extraction than a collapsed
    accordion). The FAQPage JSON-LD is built from the same CALENDAR_FAQ source."""
    out = ['<section class="cal-faq" id="faq">',
           '  <h2 class="cal-area__h2">Common questions</h2>']
    for item in CALENDAR_FAQ:
        out.append('  <div class="cal-faq__item">')
        out.append(f'    <h3 class="cal-faq__q">{_esc(item["q"])}</h3>')
        out.append(f'    <p class="cal-faq__a">{_esc(item["a"])}</p>')
        out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# HTML rendering (light ground; reuses design tokens via calendar/style.css)
# ---------------------------------------------------------------------------

def _esc(v):
    return html.escape(str(v), quote=True)


# External ticket/source URLs come from third-party listings a pull scraped, so
# they are attacker-influenced. They are rendered as hrefs on this PUBLIC page and
# emitted into the Event JSON-LD — allow only http(s) so a javascript:/data:
# scheme can neither execute in a visitor's browser nor poison structured data.
# Browsers ignore ASCII control chars inside a scheme ("java\tscript:"), so those
# are stripped from the probe before the check. Unsafe -> '' (no link, no url).
_SAFE_URL_PROBE_RE = re.compile(r'[\x00-\x20]')


def _safe_ext_url(v):
    # Scheme guard ONLY — never a URL normalizer. Return the input verbatim
    # (stripped) for http(s); do NOT re-parse/re-serialize (e.g. urlsplit ->
    # urlunsplit dropping the query, or origin+path). Signed image CDN URLs
    # (img.evbuc.com / imgix) 403 without their `?...&s=<signature>` query, so
    # dropping the query silently breaks the image. Mirrors safeHttpUrl in
    # service/src/lib/externalEvents.ts (2026-07-19 regression).
    if not v:
        return ''
    s = str(v).strip()
    probe = _SAFE_URL_PROBE_RE.sub('', s).lower()
    return s if probe.startswith(('http://', 'https://')) else ''


# Register-passable PLACEHOLDER empty-state line (per-city). Flagged for Daniel.
EMPTY_STATE = 'No rooms on the calendar in {city} this week.'


def _place_label(row, in_strip):
    """The 'venue + neighborhood/city' locator per row anatomy.

    Denver rows show a neighborhood when known; other cities show the city.
    In the cross-area weekend strip, Denver rows also carry the city so the
    reader knows where the room is.
    """
    if row['city'] == 'Denver':
        if in_strip:
            return f'Denver, {row["neighborhood"]}' if row['neighborhood'] else 'Denver'
        return row['neighborhood'] or None
    return row['city']


def _facil_venue_link(row):
    """The 'their own page' link beside the ticket link: the operator's own site
    when known, else the venue's. URLs are already scheme-scrubbed at row build.
    Returns (url, label) or (None, None)."""
    if row.get('operator_url'):
        return row['operator_url'], (row.get('operator') or 'Operator')
    if row.get('venue_url'):
        return row['venue_url'], (row.get('venue') or 'Venue')
    return None, None


def _render_row(row, in_strip=False, nav_prefix=''):
    is_fw = row['kind'] == 'firstwater'
    cls = 'cal-row cal-row--firstwater' if is_fw else 'cal-row'
    parts = [f'<article class="{cls}">']
    parts.append('  <div class="cal-row__when">')
    parts.append(f'    <span class="cal-row__date">{_esc(fmt_row_date(row["starts_at"]))}</span>')
    parts.append(f'    <span class="cal-row__time">{_esc(fmt_time(row["starts_at"]))}</span>')
    parts.append('  </div>')
    parts.append('  <div class="cal-row__body">')

    # Event image — one consistent frame (fixed ratio, object-fit cover, lazy)
    # so heterogeneous operator flyers sit coherently. The frame is Firstwater's,
    # the content is the operator's (RA-style). External rows only, and only when
    # the listing carried a scheme-safe image; no image -> no frame (clean row).
    img = row.get('image_url')
    if img and not is_fw:
        parts.append('    <div class="cal-row__media">')
        parts.append(
            f'      <img src="{_esc(img)}" alt="{_esc(alt_text(row))}" '
            f'loading="lazy" decoding="async">'
        )
        parts.append('    </div>')

    parts.append('    <div class="cal-row__text">')

    # Firstwater's own rows: distinct treatment + a subtle "our room" marker.
    if is_fw:
        parts.append('      <span class="cal-row__tag">Firstwater</span>')
        parts.append('      <span class="cal-row__ours">Our room</span>')

    # Name links to the event's page: external -> its calendar permalink (our
    # rich, indexable surface + the internal link that puts it in the crawl
    # graph); Firstwater -> its own session page.
    slug = event_slug(row)
    if is_fw:
        name_href = f'{nav_prefix}{row["ticket_url"]}'
    else:
        name_href = f'{nav_prefix}{event_permalink_path(row)}' if slug else ''
    if name_href:
        parts.append(
            f'      <h3 class="cal-row__name">'
            f'<a href="{_esc(name_href)}">{_esc(row["name"])}</a></h3>'
        )
    else:
        parts.append(f'      <h3 class="cal-row__name">{_esc(row["name"])}</h3>')

    # Facts line: operator · venue + neighborhood/city · price. Firstwater rows
    # carry the tag instead of the operator name. When an operator runs its own
    # room (operator == venue) the name is shown once, not doubled.
    meta = []
    if not is_fw and row['operator']:
        meta.append(row['operator'])
    if row['venue'] and normalize(row['venue']) != normalize(row['operator'] if not is_fw else ''):
        meta.append(row['venue'])
    place = _place_label(row, in_strip)
    if place:
        meta.append(place)
    if row['price']:
        meta.append(row['price'])
    if meta:
        parts.append(f'      <p class="cal-row__meta">{_esc(" · ".join(meta))}</p>')

    # Factual line (authored description, else deterministic template) — always
    # present, so no row is thin; states what the event IS, never whether it's good.
    parts.append(f'      <p class="cal-row__desc">{_esc(factual_description(row))}</p>')

    # Daniel's one-line editorial note — the moat. External rows only, and only
    # when he has written one; a bare row (factual line only) is the honest default.
    note = editorial_note(row)
    if note:
        parts.append(f'      <p class="cal-row__note">{_esc(note)}</p>')

    # CTA row: ticket link (external -> their link, new tab; Firstwater -> its
    # session page) plus the operator/venue 'own page' link when known. External
    # ticket/site URLs are scheme-checked before becoming hrefs; unsafe -> no link.
    cta = []
    if is_fw:
        cta.append(
            f'<a href="{_esc(nav_prefix + row["ticket_url"])}">Get tickets</a>'
        )
    else:
        safe = _safe_ext_url(row['ticket_url'])
        if safe:
            cta.append(
                f'<a href="{_esc(safe)}" target="_blank" rel="noopener">Tickets</a>'
            )
        link_url, link_label = _facil_venue_link(row)
        if link_url:
            cta.append(
                f'<a class="cal-row__link" href="{_esc(link_url)}" '
                f'target="_blank" rel="noopener">{_esc(link_label)}</a>'
            )
    if cta:
        parts.append('      <p class="cal-row__cta">' + ' '.join(cta) + '</p>')

    parts.append('    </div>')  # .cal-row__text
    parts.append('  </div>')    # .cal-row__body
    parts.append('</article>')
    return '\n'.join(parts)


def _render_rows(rows, in_strip, nav_prefix, empty_text):
    if not rows:
        return f'<p class="cal-empty">{_esc(empty_text)}</p>'
    inner = '\n'.join(_render_row(r, in_strip=in_strip, nav_prefix=nav_prefix) for r in rows)
    return f'<div class="cal-rows">\n{inner}\n</div>'


def render_calendar_body(rows, nav_prefix='', now=None):
    """The dynamic middle of /calendar/: this-weekend strip + four area sections.

    Static scaffolding (hero, jump nav, email capture, submission line) lives
    in the section file; this returns everything that depends on the feed.
    """
    groups = group_by_city(rows)
    wk = weekend_rows(rows, now)

    out = []

    # This-weekend strip — cuts across all areas.
    out.append('<div class="cal-weekend" id="this-weekend">')
    out.append('  <span class="eyebrow">This weekend</span>')
    out.append('  <h2 class="cal-weekend__h2">Sound baths this weekend on the Front Range</h2>')
    out.append('  ' + _render_rows(
        wk, in_strip=True, nav_prefix=nav_prefix,
        empty_text='Nothing on the calendar this weekend. The week ahead is below.',
    ))
    out.append('</div>')

    # Area sections, fixed order, chronological within.
    for city in CITIES:
        anchor = CITY_ANCHOR[city]
        out.append(f'<div class="cal-area" id="{anchor}">')
        out.append(f'  <h2 class="cal-area__h2">{_esc(CITY_H2[city])}</h2>')
        out.append('  ' + _render_rows(
            groups[city], in_strip=False, nav_prefix=nav_prefix,
            empty_text=EMPTY_STATE.format(city=city),
        ))
        out.append('</div>')

    # FAQ — a GEO/AIO citation surface (FAQPage JSON-LD emitted by build.py).
    out.append(render_faq_html())

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Event JSON-LD (ItemList of Events — accurate or absent, never padded)
# ---------------------------------------------------------------------------

_PRICE_NUM_RE = re.compile(r'\d+(?:\.\d+)?')
# "free" as a standalone word — NOT the "free" buried in "freewill".
_FREE_RE = re.compile(r'\bfree\b', re.I)
# Pay-what-you-can / donation intent. When any of these appear, a bare "free"
# does NOT mean $0 ("Freewill donation", "free-will offering", "free, sliding
# scale"): the true price is unknown, so emit no price rather than a false 0
# (spec: "accurate or absent, never padded").
_DONATION_RE = re.compile(r'donat|offering|free[- ]will|sliding|suggested|pay[- ]?what', re.I)


def _parse_price(price):
    """('fixed', n) | ('free',) | ('range', lo, hi) | (None,)."""
    if not price:
        return (None,)
    nums = [float(x) for x in _PRICE_NUM_RE.findall(price)]
    if not nums:
        is_free = bool(_FREE_RE.search(price)) and not _DONATION_RE.search(price)
        return ('free',) if is_free else (None,)
    if len(nums) == 1:
        return ('fixed', nums[0])
    return ('range', min(nums), max(nums))


def _fmt_price_num(n):
    return str(int(n)) if n == int(n) else f'{n:.2f}'


def _external_offer(row):
    """Offer/AggregateOffer for an external row, or None. Ticket url only when
    known; price only when it can be read accurately from the price string.
    Free events carry isAccessibleForFree:true (spec §6)."""
    kind = _parse_price(row['price'])
    url = _safe_ext_url(row['ticket_url']) or None
    if kind[0] == 'fixed':
        offer = {'@type': 'Offer', 'price': _fmt_price_num(kind[1]), 'priceCurrency': 'USD'}
    elif kind[0] == 'free':
        offer = {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD',
                 'isAccessibleForFree': True}
    elif kind[0] == 'range':
        offer = {'@type': 'AggregateOffer',
                 'lowPrice': _fmt_price_num(kind[1]),
                 'highPrice': _fmt_price_num(kind[2]),
                 'priceCurrency': 'USD'}
    elif url:
        offer = {'@type': 'Offer'}   # price unknown (e.g. "Donation") — never guessed
    else:
        return None
    if url:
        offer['url'] = url
    return offer


def _external_event(row, site_url):
    """schema.org Event (no @context) for one external row: only fields we know.

    url = the event's PERMALINK (its /calendar/event/<slug>/ page); offers.url
    stays the operator's ticket link. description = Daniel's note if present,
    else the factual description/template (accurate, never padded). performer =
    the named facilitator; organizer = the operator; image = the listing image.
    """
    place = {'@type': 'Place'}
    if row['venue']:
        place['name'] = row['venue']
    addr = {'@type': 'PostalAddress', 'addressLocality': row['city'],
            'addressRegion': 'CO', 'addressCountry': 'US'}
    if row['address']:
        addr['streetAddress'] = row['address']
    place['address'] = addr

    ev = {
        '@type': 'Event',
        'name': row['name'],
        'startDate': _denver(row['starts_at']).isoformat(),
        'eventStatus': 'https://schema.org/EventScheduled',
        'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
        'location': place,
    }
    desc = editorial_note(row) or factual_description(row)
    if desc:
        ev['description'] = desc
    if row.get('facilitator'):
        ev['performer'] = {'@type': 'Person', 'name': row['facilitator']}
    if row['operator']:
        ev['organizer'] = {'@type': 'Organization', 'name': row['operator']}
        if row.get('operator_url'):
            ev['organizer']['url'] = row['operator_url']
    if row.get('image_url'):
        ev['image'] = {'@type': 'ImageObject', 'url': row['image_url'],
                       'caption': alt_text(row)}
    offer = _external_offer(row)
    if offer:
        ev['offers'] = offer
    slug = event_slug(row)
    if slug:
        ev['url'] = event_permalink_url(row, site_url)
    return ev


def event_jsonld(row, site_url):
    """Standalone Event (with @context) for an external event's permalink page."""
    return {'@context': 'https://schema.org', **_external_event(row, site_url)}


def _firstwater_event(row, site_url):
    """Reuse sessions_feed's Event builder so Firstwater rows carry the same
    accurate Event markup as their session pages; url points at the session page
    (its canonical home), and @context is stripped for ItemList nesting."""
    slug = (row.get('_sess') or {}).get('event_slug', '')
    session_url = f'{site_url}/sessions/{slug}/' if slug else site_url
    ev = sessions_feed.event_schema(
        row['_sess'], row['_event_title'], session_url, site_url,
    )
    ev.pop('@context', None)
    return ev


def calendar_itemlist(rows, page_url, site_url):
    """One ItemList wrapping an Event per rendered row, or None when empty.

    Rows are already future + approved + de-duplicated + city/chronologically
    ordered by build_rows/group_by_city; the caller passes that same ordering.
    """
    ordered = []
    for city in CITIES:
        ordered.extend(r for r in rows if r['city'] == city)
    ordered.sort(key=lambda r: (CITIES.index(r['city']), parse_iso(r['starts_at'])))
    if not ordered:
        return None

    items = []
    for i, row in enumerate(ordered, start=1):
        ev = (_firstwater_event(row, site_url)
              if row['kind'] == 'firstwater' else _external_event(row, site_url))
        items.append({'@type': 'ListItem', 'position': i, 'item': ev})

    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Front Range sound baths this week',
        'itemListElement': items,
    }


def collectionpage_schema(page_url, site_url, description, date_modified):
    """CollectionPage schema for /calendar/ with a speakable summary selector.
    dateModified matches the visible 'Last updated' stamp."""
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': 'Sound baths on the Front Range — this week',
        'url': page_url,
        'description': description,
        'dateModified': date_modified,
        'isPartOf': {'@type': 'WebSite', 'name': 'Firstwater', 'url': site_url},
        'speakable': {'@type': 'SpeakableSpecification',
                      'cssSelector': ['#cal-summary']},
    }


def faqpage_schema():
    """FAQPage schema built from the same CALENDAR_FAQ the page renders."""
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': item['q'],
             'acceptedAnswer': {'@type': 'Answer', 'text': item['a']}}
            for item in CALENDAR_FAQ
        ],
    }


# ---------------------------------------------------------------------------
# Per-event permalink page (/calendar/event/<slug>/) — the body HTML. Page
# assembly (base layout, <head>, schema) is build.py's job; this returns the
# <main> content only, consonant with the section-file pipeline.
# ---------------------------------------------------------------------------

# Inline style for event pages (they have no _src/pages dir, so no style.css is
# injected). Design tokens come from the sitewide styles.css every page loads.
EVENT_PAGE_STYLE = """<style>
    .cal-event { }
    .cal-event__crumbs { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin: 0 0 2rem; }
    .cal-event__crumbs a { color: var(--accent-on-light); text-decoration: none; }
    .cal-event__crumbs a:hover { text-decoration: underline; }
    .cal-past-banner { background: rgba(10,11,13,0.05); border-left: 3px solid var(--gray); padding: 0.9rem 1.2rem; margin: 0 0 2rem; font-size: 0.95rem; }
    .cal-past-banner a { color: var(--accent-on-light); }
    .cal-event__h1 { font-size: clamp(2rem, 4vw, 3rem); margin: 0.4rem 0 1.4rem; }
    .cal-event__desc { font-size: 1.15rem; line-height: 1.6; max-width: 42rem; color: rgba(10,11,13,0.78); margin: 0 0 1rem; }
    .cal-event__note { font: 500 1.2rem var(--font-display); color: var(--ink); max-width: 40rem; line-height: 1.4; margin: 0 0 1.6rem; }
    .cal-event__figure { margin: 2rem 0; max-width: 640px; }
    .cal-event__figure img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; background: rgba(10,11,13,0.06); }
    .cal-event__figure figcaption { font-size: 0.82rem; color: rgba(10,11,13,0.55); margin-top: 0.6rem; }
    .cal-event__facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.6rem 1.6rem; margin: 2rem 0; max-width: 40rem; }
    .cal-event__facts dt { font: 600 0.72rem var(--font-body); letter-spacing: 0.13em; text-transform: uppercase; color: var(--gray); align-self: baseline; }
    .cal-event__facts dd { margin: 0; color: var(--ink); }
    .cal-event__cta { display: flex; flex-wrap: wrap; gap: 1rem 1.6rem; align-items: center; margin: 2rem 0; }
    .cal-event__link { color: var(--accent-on-light); font: 600 0.9rem var(--font-body); text-decoration: none; }
    .cal-event__link:hover { text-decoration: underline; }
    .cal-event__back { margin: 2.4rem 0 0; padding-top: 2rem; border-top: 1px solid rgba(10,11,13,0.14); }
    .cal-event__back a { color: var(--accent-on-light); text-decoration: none; }
    .cal-event__back a:hover { text-decoration: underline; }
    @media (max-width: 640px) { .cal-event__facts { grid-template-columns: 1fr; gap: 0.2rem; } .cal-event__facts dd { margin-bottom: 0.8rem; } }
  </style>"""


def render_event_page(row, nav_prefix, site_url, now=None):
    """The <main> content for one external event's permalink page."""
    now = _now_utc(now)
    is_past = parse_iso(row['starts_at']) <= now
    esc = _esc
    out = ['<section class="section section--light cal-event">', '  <div class="container">']

    # Breadcrumb (visible) — mirrors the BreadcrumbList schema build.py emits.
    out.append('    <nav class="cal-event__crumbs" aria-label="Breadcrumb">')
    out.append(
        f'      <a href="{nav_prefix}">Home</a> <span aria-hidden="true">/</span> '
        f'<a href="{nav_prefix}calendar/">Calendar</a> <span aria-hidden="true">/</span> '
        f'<span>{esc(row["name"])}</span>')
    out.append('    </nav>')

    # Past session: page stays live (build.py sets robots=noindex + drops it from
    # the sitemap) but says so and points at the current list.
    if is_past:
        out.append(
            '    <p class="cal-past-banner">This session has passed. '
            f'<a href="{nav_prefix}calendar/">See what’s on now →</a></p>')

    out.append('    <span class="eyebrow">Front Range calendar</span>')
    out.append(f'    <h1 class="cal-event__h1">{esc(row["name"])}</h1>')

    out.append(f'    <p class="cal-event__desc">{esc(factual_description(row))}</p>')
    note = editorial_note(row)
    if note:
        out.append(f'    <p class="cal-event__note">{esc(note)}</p>')

    img = row.get('image_url')
    if img:
        out.append('    <figure class="cal-event__figure">')
        out.append(
            f'      <img src="{esc(img)}" alt="{esc(alt_text(row))}" '
            f'loading="lazy" decoding="async">')
        out.append(f'      <figcaption>{esc(alt_text(row))}</figcaption>')
        out.append('    </figure>')

    # Facts block
    out.append('    <dl class="cal-event__facts">')
    out.append(
        f'      <dt>When</dt><dd>{esc(sessions_feed.fmt_date_long(row["starts_at"]))} '
        f'· {esc(fmt_time(row["starts_at"]))} (Denver time)</dd>')
    venue_bits = ' · '.join(x for x in (row.get('venue'), row.get('address')) if x)
    if venue_bits:
        out.append(f'      <dt>Where</dt><dd>{esc(venue_bits)}</dd>')
    place = row['neighborhood'] if row['city'] == 'Denver' and row.get('neighborhood') else None
    area = f'{place}, {row["city"]}' if place else row['city']
    out.append(f'      <dt>Area</dt><dd>{esc(area)}</dd>')
    if row.get('price'):
        out.append(f'      <dt>Price</dt><dd>{esc(row["price"])}</dd>')
    if row.get('facilitator'):
        out.append(f'      <dt>Facilitator</dt><dd>{esc(row["facilitator"])}</dd>')
    if row.get('operator'):
        out.append(f'      <dt>Operator</dt><dd>{esc(row["operator"])}</dd>')
    out.append('    </dl>')

    # Links: operator tickets + operator/venue own page + a maps link.
    links = []
    safe = _safe_ext_url(row['ticket_url'])
    if safe:
        links.append(
            f'<a class="btn btn-primary" href="{esc(safe)}" target="_blank" '
            f'rel="noopener">Tickets</a>')
    link_url, link_label = _facil_venue_link(row)
    if link_url:
        links.append(
            f'<a class="cal-event__link" href="{esc(link_url)}" target="_blank" '
            f'rel="noopener">{esc(link_label)}</a>')
    if row.get('address'):
        q = quote_plus(f'{row["address"]}, {row["city"]}, CO')
        maps = f'https://www.google.com/maps/search/?api=1&query={q}'
        links.append(
            f'<a class="cal-event__link" href="{esc(maps)}" target="_blank" '
            f'rel="noopener">Open in Maps</a>')
    if links:
        out.append('    <p class="cal-event__cta">' + ' '.join(links) + '</p>')

    anchor = CITY_ANCHOR.get(row['city'], '')
    out.append(
        f'    <p class="cal-event__back"><a href="{nav_prefix}calendar/#{anchor}">'
        'Part of the Front Range calendar →</a></p>')

    out.append('  </div>')
    out.append('</section>')
    return '\n'.join(out)


def approved_event_rows(cal_feed, now=None):
    """External rows for EVERY approved event — past and future — deduped by
    permalink slug. Drives the permalink-page pipeline (future pages are
    indexed + in the sitemap; past pages stay live but noindex + out of it).
    Firstwater sessions are excluded: they already have their own rich session
    pages and must not get a second, duplicate permalink.
    """
    rows, seen = [], set()
    for e in (cal_feed or {}).get('events', []):
        if e.get('status') != RENDER_STATUS:
            continue
        try:
            parse_iso(e['starts_at'])
        except (KeyError, ValueError):
            continue
        row = _external_row(e)
        slug = event_slug(row)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append(row)
    rows.sort(key=lambda r: parse_iso(r['starts_at']))
    return rows
