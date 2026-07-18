"""Sessions feed loader + renderer for build.py (WP5 seam, site half).

The events service publishes a JSON feed of dated sessions. At build time we:
  1. fetch the feed (env SESSIONS_FEED_URL, default: live service),
  2. validate its shape and write it to data/sessions-cache.json
     (committed, deterministic formatting) so every future build has
     a known-good copy,
  3. on ANY fetch/parse/validation failure: warn and fall back to the
     committed cache. A broken build is never acceptable.

Test fixture path: set SESSIONS_FEED_FILE=/abs/path/to/fixture.json to
build against a local file. Fixture builds NEVER write the cache, so
fixture data cannot leak into the committed cache or subsequent builds.
(A file:// SESSIONS_FEED_URL also works and also never writes the cache:
only http(s) fetches update it.)

Stdlib only — no new dependencies.

FEED CONTRACT (GET {SESSIONS_FEED_URL}):
{ "generated_at": "...", "sessions": [ {
    "id","event_slug","starts_at","ends_at","doors_at",
    "status": "on_sale|sold_out|scheduled|completed",
    "remaining", "waitlist_open",
    "venue": {"name","address","lat","lng"},
    "tiers": [{"id","name","mode":"fixed|sliding","amount",
               "min_amount","suggested_amount"}],
    "checkout_url", "waitlist_url" } ] }
Timestamps ISO-8601 with offset; amounts in cents.
The checkout endpoint expects a POST; we render a form with a
`tier_id` field naming the chosen tier.
"""

import html
import json
import os
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_FEED_URL = 'https://ss-service-production.up.railway.app/feeds/sessions.json'
CACHE_REL_PATH = os.path.join('data', 'sessions-cache.json')
FETCH_TIMEOUT_S = 10
DENVER = ZoneInfo('America/Denver')

# Statuses that produce a visible dates block on a session page.
DISPLAY_STATUSES = ('on_sale', 'sold_out', 'scheduled')
# Statuses eligible for the home-hero next-date slot.
HERO_STATUSES = ('on_sale', 'scheduled')

_SCHEMA_AVAILABILITY = {
    'on_sale': 'https://schema.org/InStock',
    'sold_out': 'https://schema.org/SoldOut',
    'scheduled': 'https://schema.org/PreOrder',
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def parse_iso(ts):
    """Parse an ISO-8601 timestamp (offset or trailing Z) to aware datetime."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError(f'timestamp missing offset: {ts!r}')
    return dt


def empty_feed():
    return {'generated_at': None, 'sessions': []}


def validate_feed(feed):
    """Shape-check a parsed feed. Raises ValueError on any problem."""
    if not isinstance(feed, dict):
        raise ValueError('feed root is not an object')
    if not isinstance(feed.get('sessions'), list):
        raise ValueError('feed.sessions is not a list')
    for i, s in enumerate(feed['sessions']):
        where = f'sessions[{i}]'
        if not isinstance(s, dict):
            raise ValueError(f'{where} is not an object')
        for key in ('id', 'event_slug', 'starts_at', 'status'):
            if not isinstance(s.get(key), str) or not s[key]:
                raise ValueError(f'{where}.{key} missing or not a string')
        parse_iso(s['starts_at'])
        for key in ('ends_at', 'doors_at'):
            if s.get(key):
                parse_iso(s[key])
        if not isinstance(s.get('venue'), dict):
            raise ValueError(f'{where}.venue is not an object')
        if not isinstance(s.get('tiers'), list):
            raise ValueError(f'{where}.tiers is not a list')
        for j, t in enumerate(s['tiers']):
            if not isinstance(t, dict):
                raise ValueError(f'{where}.tiers[{j}] is not an object')
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
        log(f'  ⚠ sessions cache unusable ({exc.__class__.__name__}: {exc}) — building with no sessions')
        return empty_feed()


def load_feed(repo_root, log=print):
    """Return the sessions feed dict, never raising.

    Order of precedence:
      SESSIONS_FEED_FILE (local fixture, cache untouched)
      > SESSIONS_FEED_URL fetch (http(s) success refreshes the cache)
      > committed data/sessions-cache.json
      > empty feed.
    """
    cache_path = os.path.join(repo_root, CACHE_REL_PATH)

    fixture = os.environ.get('SESSIONS_FEED_FILE')
    if fixture:
        try:
            with open(fixture, 'r', encoding='utf-8') as f:
                feed = validate_feed(json.load(f))
            log(f'  ✓ sessions feed from fixture {fixture} ({len(feed["sessions"])} session(s); cache untouched)')
            return feed
        except Exception as exc:
            log(f'  ⚠ SESSIONS_FEED_FILE unusable ({exc.__class__.__name__}: {exc}) — using committed cache')
            return _load_cache(cache_path, log)

    url = os.environ.get('SESSIONS_FEED_URL', DEFAULT_FEED_URL)
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
            feed = validate_feed(json.loads(resp.read().decode('utf-8')))
    except Exception as exc:
        log(f'  ⚠ sessions feed unavailable at {url} ({exc.__class__.__name__}) — using committed cache')
        return _load_cache(cache_path, log)

    if url.startswith(('http://', 'https://')):
        _write_cache(cache_path, feed)
        log(f'  ✓ sessions feed fetched ({len(feed["sessions"])} session(s)) — cache refreshed')
    else:
        log(f'  ✓ sessions feed from {url} ({len(feed["sessions"])} session(s); cache untouched)')
    return feed


def client_feed_url():
    """Feed URL baked into pages for the client-side overlay.

    Always an http(s) URL: fixture/file builds still point the overlay at
    the real feed so local paths never leak into built output.
    """
    url = os.environ.get('SESSIONS_FEED_URL', DEFAULT_FEED_URL)
    return url if url.startswith(('http://', 'https://')) else DEFAULT_FEED_URL


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _future(s, now):
    return parse_iso(s['starts_at']) > now


def sessions_for_slug(feed, event_slug, now=None):
    """Displayable future sessions for one event page, soonest first."""
    now = now or datetime.now(timezone.utc)
    out = [s for s in feed.get('sessions', [])
           if s.get('event_slug') == event_slug
           and s.get('status') in DISPLAY_STATUSES
           and _future(s, now)]
    out.sort(key=lambda s: parse_iso(s['starts_at']))
    return out


def next_session(feed, now=None):
    """Earliest future on_sale/scheduled session across all events, or None."""
    now = now or datetime.now(timezone.utc)
    pool = [s for s in feed.get('sessions', [])
            if s.get('status') in HERO_STATUSES and _future(s, now)]
    pool.sort(key=lambda s: parse_iso(s['starts_at']))
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# Formatting (America/Denver, functional copy only)
# ---------------------------------------------------------------------------

def _denver(ts):
    return parse_iso(ts).astimezone(DENVER)


def _day(n):
    return str(int(n))  # strip leading zero portably (no %-d on Windows)


def fmt_date_long(ts):
    d = _denver(ts)
    return f'{d.strftime("%A")}, {d.strftime("%B")} {_day(d.strftime("%d"))}, {d.year}'


def fmt_date_short(ts):
    d = _denver(ts)
    return f'{d.strftime("%B")} {_day(d.strftime("%d"))}'


def fmt_time(ts):
    d = _denver(ts)
    hour = _day(d.strftime("%I"))
    return f'{hour}:{d.strftime("%M")} {d.strftime("%p")}'


def fmt_money(cents):
    if cents is None:
        return None
    dollars = cents / 100
    if dollars == int(dollars):
        return f'${int(dollars)}'
    return f'${dollars:.2f}'


def tier_label(tier):
    """'Standard · $45' or 'Sliding · from $25' (min > suggested > amount)."""
    name = tier.get('name') or 'Ticket'
    if tier.get('mode') == 'sliding':
        base = tier.get('min_amount') or tier.get('suggested_amount') or tier.get('amount')
        price = fmt_money(base)
        price = f'from {price}' if price else None
    else:
        price = fmt_money(tier.get('amount'))
    return f'{name} · {price}' if price else name


# ---------------------------------------------------------------------------
# HTML rendering (reuses existing classes: .logistics, .btn, .blog-subhead)
# ---------------------------------------------------------------------------

_BLOCK_STYLE = (
    '<style>\n'
    '    .session-checkout .btn { margin-top: 1.2rem; }\n'
    '    .session-checkout .btn[disabled] { opacity: 0.45; cursor: not-allowed; filter: none; }\n'
    '    .session-tiers { border: 0; padding: 0; margin: 1rem 0 0; }\n'
    '    .session-tiers label, .session-tier { display: block; margin-top: 0.5rem; }\n'
    '  </style>'
)


def _esc(v):
    return html.escape(str(v), quote=True)


def _render_one(s):
    sid = _esc(s['id'])
    status = s.get('status')
    venue = s.get('venue') or {}
    tiers = s.get('tiers') or []
    parts = []
    parts.append(f'<div class="logistics" data-session-id="{sid}" data-session-status="{_esc(status)}">')

    # Facts list
    parts.append('  <dl>')
    parts.append(f'    <dt>Date</dt><dd>{_esc(fmt_date_long(s["starts_at"]))}</dd>')
    time_bits = [fmt_time(s['starts_at'])]
    if s.get('doors_at'):
        time_bits.append(f'doors {fmt_time(s["doors_at"])}')
    parts.append(f'    <dt>Time</dt><dd>{_esc(" · ".join(time_bits))}</dd>')
    venue_bits = ' · '.join(x for x in (venue.get('name'), venue.get('address')) if x)
    if venue_bits:
        parts.append(f'    <dt>Venue</dt><dd>{_esc(venue_bits)}</dd>')
    if status == 'on_sale' and isinstance(s.get('remaining'), int):
        parts.append(f'    <dt>Seats</dt><dd data-session-remaining>{s["remaining"]} left</dd>')
    else:
        # Empty slot so the client overlay has somewhere to write counts.
        parts.append('    <dt hidden>Seats</dt><dd data-session-remaining hidden></dd>')
    parts.append('  </dl>')

    # Checkout form (POST to the service; tier_id names the chosen tier)
    if status in ('on_sale', 'sold_out') and s.get('checkout_url'):
        parts.append(f'  <form class="session-checkout" method="post" action="{_esc(s["checkout_url"])}">')
        if len(tiers) > 1:
            parts.append('    <fieldset class="session-tiers">')
            for k, t in enumerate(tiers):
                checked = ' checked' if k == 0 else ''
                parts.append(
                    f'      <label><input type="radio" name="tier_id" value="{_esc(t.get("id", ""))}"{checked}> '
                    f'{_esc(tier_label(t))}</label>'
                )
            parts.append('    </fieldset>')
        elif tiers:
            t = tiers[0]
            parts.append(f'    <p class="session-tier">{_esc(tier_label(t))}</p>')
            parts.append(f'    <input type="hidden" name="tier_id" value="{_esc(t.get("id", ""))}">')
        disabled = ' disabled' if status == 'sold_out' else ''
        parts.append(f'    <button type="submit" class="btn btn-primary" data-session-buy{disabled}>Get tickets</button>')
        parts.append('  </form>')
        if status == 'sold_out':
            parts.append('  <p class="session-tier">Sold out.</p>')
    elif status == 'scheduled':
        for t in tiers:
            parts.append(f'  <p class="session-tier">{_esc(tier_label(t))}</p>')
        parts.append('  <p class="session-tier">On sale soon.</p>')

    # Waitlist link — rendered whenever the service gave us a URL, hidden
    # unless sold out with the waitlist open, so the client overlay can
    # toggle it without inventing DOM.
    if s.get('waitlist_url'):
        hide = '' if (status == 'sold_out' and s.get('waitlist_open')) else ' hidden'
        parts.append(f'  <p class="session-waitlist"{hide}><a href="{_esc(s["waitlist_url"])}" data-session-waitlist>Join the waitlist</a></p>')

    parts.append('</div>')
    return '\n'.join(parts)


def render_sessions_block(sessions, nav_prefix):
    """The dates/tickets section injected into a session page. '' if none."""
    if not sessions:
        return ''
    inner = '\n\n'.join(_render_one(s) for s in sessions)
    return (
        f'<section class="session-dates" data-sessions-feed="{_esc(client_feed_url())}">\n'
        f'  {_BLOCK_STYLE}\n'
        f'  <h2 class="blog-subhead blog-subhead--h2">Dates</h2>\n'
        f'{inner}\n'
        f'</section>\n'
        f'<script src="{_esc(nav_prefix)}js/sessions.js" defer></script>'
    )


# ---------------------------------------------------------------------------
# Event JSON-LD (only ever called with real dated sessions, so DESIGN.md's
# "Event schema once a real date exists, not before" holds automatically)
# ---------------------------------------------------------------------------

def _offer(tier, s):
    if tier.get('mode') == 'sliding':
        cents = tier.get('min_amount') or tier.get('suggested_amount') or tier.get('amount') or 0
    else:
        cents = tier.get('amount') or 0
    offer = {
        '@type': 'Offer',
        'name': tier.get('name') or 'Ticket',
        'price': f'{cents / 100:.2f}',
        'priceCurrency': 'USD',
        'availability': _SCHEMA_AVAILABILITY.get(s.get('status'), 'https://schema.org/InStock'),
    }
    if s.get('checkout_url'):
        offer['url'] = s['checkout_url']
    return offer


def event_schema(s, event_title, page_url, site_url, description='', image=''):
    """schema.org Event dict for one dated session."""
    starts = _denver(s['starts_at'])
    venue = s.get('venue') or {}
    place = {'@type': 'Place', 'name': venue.get('name') or 'Venue to be announced'}
    if venue.get('address'):
        place['address'] = venue['address']
    if venue.get('lat') and venue.get('lng'):
        place['geo'] = {'@type': 'GeoCoordinates',
                        'latitude': venue['lat'], 'longitude': venue['lng']}
    ev = {
        '@context': 'https://schema.org',
        '@type': 'Event',
        'name': f'{event_title} · {fmt_date_short(s["starts_at"])}, {starts.year}',
        'startDate': starts.isoformat(),
        'endDate': _denver(s['ends_at']).isoformat() if s.get('ends_at') else starts.isoformat(),
        'eventStatus': 'https://schema.org/EventScheduled',
        'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
        'location': place,
        'organizer': {'@type': 'LocalBusiness', 'name': 'Sound Sessions', 'url': site_url},
        'url': page_url,
    }
    if description:
        ev['description'] = description
    if image:
        ev['image'] = image
    offers = [_offer(t, s) for t in (s.get('tiers') or [])]
    if offers:
        ev['offers'] = offers
    return ev
