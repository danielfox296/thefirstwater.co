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
    "confidence": <0..1>, "dedup_key","status","note","rejection_note" } ] }
Timestamps ISO-8601 with offset (America/Denver local). Only status="approved"
events are ever rendered; candidate/rejected never leave the service and are
filtered here too as a belt-and-braces guard.
"""

import html
import json
import os
import re
import unicodedata
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from _src.lib import sessions_feed
from _src.lib.sessions_feed import DENVER, parse_iso

DEFAULT_FEED_URL = 'https://ss-service-production.up.railway.app/feeds/calendar.json'
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
    'longmont': 'Boulder', 'louisville': 'Boulder', 'lafayette': 'Boulder',
    'superior': 'Boulder', 'nederland': 'Boulder',
    'loveland': 'Fort Collins', 'windsor': 'Fort Collins',
    'greeley': 'Fort Collins', 'wellington': 'Fort Collins',
    'manitou springs': 'Colorado Springs', 'monument': 'Colorado Springs',
    'fountain': 'Colorado Springs',
}

# Statuses that render. Anything else (candidate/rejected/unknown) is dropped.
RENDER_STATUS = 'approved'


# ---------------------------------------------------------------------------
# Normalization / dedup key (contract algorithm — also used by the pull agent
# and the seed generator, kept here as the single source of truth)
# ---------------------------------------------------------------------------

def normalize(s):
    """lowercase, strip accents/diacritics, drop non-alphanumeric-non-space
    chars, collapse whitespace to single spaces, trim."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
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


def _render_row(row, in_strip=False, nav_prefix=''):
    cls = 'cal-row cal-row--firstwater' if row['kind'] == 'firstwater' else 'cal-row'
    parts = [f'<article class="{cls}">']
    parts.append('  <div class="cal-row__when">')
    parts.append(f'    <span class="cal-row__date">{_esc(fmt_row_date(row["starts_at"]))}</span>')
    parts.append(f'    <span class="cal-row__time">{_esc(fmt_time(row["starts_at"]))}</span>')
    parts.append('  </div>')
    parts.append('  <div class="cal-row__body">')

    if row['kind'] == 'firstwater':
        parts.append('    <span class="cal-row__tag">Firstwater</span>')
    parts.append(f'    <h3 class="cal-row__name">{_esc(row["name"])}</h3>')

    # Facts line: operator · venue + neighborhood/city · price. Firstwater rows
    # carry the tag instead of the operator name. When an operator runs its own
    # room (operator == venue) the name is shown once, not doubled.
    meta = []
    if row['kind'] == 'external' and row['operator']:
        meta.append(row['operator'])
    if row['venue'] and normalize(row['venue']) != normalize(row['operator'] if row['kind'] == 'external' else ''):
        meta.append(row['venue'])
    place = _place_label(row, in_strip)
    if place:
        meta.append(place)
    if row['price']:
        meta.append(row['price'])
    if meta:
        parts.append(f'    <p class="cal-row__meta">{_esc(" · ".join(meta))}</p>')

    # Daniel's one-line editorial note — the moat. External rows only, and only
    # when he has written one; bare rows are the honest default.
    if row['kind'] == 'external' and row['note']:
        parts.append(f'    <p class="cal-row__note">{_esc(row["note"])}</p>')

    # Ticket link. External -> their link, new tab. Firstwater -> its session page.
    # Firstwater rows carry an internal, trusted relative path (nav_prefix + slug);
    # external rows carry a scraped URL, so it is scheme-checked before it becomes
    # an href — an unsafe URL simply yields no link (the fact row still stands).
    if row['kind'] == 'firstwater':
        href = f'{nav_prefix}{row["ticket_url"]}'
        parts.append(f'    <p class="cal-row__cta"><a href="{_esc(href)}">Get tickets</a></p>')
    else:
        safe = _safe_ext_url(row['ticket_url'])
        if safe:
            parts.append(
                f'    <p class="cal-row__cta"><a href="{_esc(safe)}" '
                f'target="_blank" rel="noopener">Tickets</a></p>'
            )
    parts.append('  </div>')
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
    known; price only when it can be read accurately from the price string."""
    kind = _parse_price(row['price'])
    url = _safe_ext_url(row['ticket_url']) or None
    if kind[0] == 'fixed':
        offer = {'@type': 'Offer', 'price': _fmt_price_num(kind[1]), 'priceCurrency': 'USD'}
    elif kind[0] == 'free':
        offer = {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}
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


def _external_event(row):
    """schema.org Event for one external row: only fields we actually know."""
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
    if row['operator']:
        ev['organizer'] = {'@type': 'Organization', 'name': row['operator']}
    offer = _external_offer(row)
    if offer:
        ev['offers'] = offer
    _safe_url = _safe_ext_url(row['ticket_url'])
    if _safe_url:
        ev['url'] = _safe_url
    return ev


def _firstwater_event(row, page_url, site_url):
    """Reuse sessions_feed's Event builder so Firstwater rows carry the same
    accurate Event markup as their session pages; strip @context for nesting."""
    ev = sessions_feed.event_schema(
        row['_sess'], row['_event_title'], page_url, site_url,
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
        ev = (_firstwater_event(row, page_url, site_url)
              if row['kind'] == 'firstwater' else _external_event(row))
        items.append({'@type': 'ListItem', 'position': i, 'item': ev})

    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': 'Front Range sound baths this week',
        'itemListElement': items,
    }
