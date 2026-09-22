#!/usr/bin/env python3
"""
IndexNow ping — submits sitemap URLs after a deploy; changed-only when a
pre-deploy baseline is supplied.

Runs in CI after the Pages deploy step (see .github/workflows/deploy.yml).
ORDERING MATTERS: the workflow snapshots the LIVE sitemap to a file BEFORE
the build/deploy steps — by the time this script runs, live already equals
the new sitemap, so a post-deploy fetch would always diff empty. Against
that pre-deploy baseline, only URLs that are new or whose <lastmod> changed
are submitted; when nothing changed the ping is skipped entirely (audit
FW-CODE-1: no more resubmitting every URL on every deploy). Without a
readable baseline (first deploy, snapshot failed) every URL is submitted —
the old behavior.

Stdlib only. Never fails the deploy: any error is reported and swallowed.

Key file: /<KEY>.txt at the site root, served at https://thefirstwater.co/<KEY>.txt

Usage: indexnow.py [--baseline <live-sitemap.xml>] [--dry-run]
"""

import json
import re
import sys
import urllib.request

SITE = "thefirstwater.co"
KEY = "09dfe161f3a062373ee2bbf7766db185"
ENDPOINT = "https://api.indexnow.org/indexnow"
SITEMAP = "sitemap.xml"

# One <url> block: loc plus its optional lastmod. Both sitemaps this ever
# parses are emitted by build.py's generator, so the shape is stable.
_URL_RE = re.compile(r"<url>\s*<loc>(.*?)</loc>(?:\s*<lastmod>(.*?)</lastmod>)?", re.S)


def parse_sitemap(text):
    """{loc: lastmod-or-''} for every <url> block in a sitemap."""
    return {loc.strip(): (lastmod or "").strip()
            for loc, lastmod in _URL_RE.findall(text)}


def changed_urls(new, baseline_path):
    """(urls, reason): the URLs to submit and a one-line why.

    A URL is submitted when it's absent from the baseline or its lastmod
    differs (any difference — a lastmod can legitimately move backward when
    the derivation improves). No baseline, or an unreadable/empty one, means
    the diff can't be trusted: submit everything.
    """
    if not baseline_path:
        return sorted(new), "no baseline given — submitting all"
    try:
        with open(baseline_path, encoding="utf-8") as f:
            old = parse_sitemap(f.read())
    except OSError as e:
        return sorted(new), f"baseline unreadable ({e.__class__.__name__}) — submitting all"
    if not old:
        return sorted(new), "baseline empty — submitting all"
    urls = sorted(loc for loc, lm in new.items() if loc not in old or old[loc] != lm)
    return urls, (f"{len(urls)} of {len(new)} URLs new or lastmod-changed "
                  f"vs pre-deploy live sitemap")


def main(argv):
    baseline_path, dry_run = None, False
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--baseline" and args:
            baseline_path = args.pop(0)
        elif arg == "--dry-run":
            dry_run = True
        else:
            print(f"indexnow: unknown argument {arg!r} ignored", file=sys.stderr)

    with open(SITEMAP, encoding="utf-8") as f:
        new = parse_sitemap(f.read())
    if not new:
        print("indexnow: no URLs found in sitemap, skipping")
        return

    urls, reason = changed_urls(new, baseline_path)
    if not urls:
        print(f"indexnow: nothing changed ({reason}) — ping skipped")
        return
    print(f"indexnow: {reason}")

    if dry_run:
        for url in urls:
            print(f"  would submit {url}")
        print(f"indexnow: dry run — {len(urls)} URL(s), nothing sent")
        return

    payload = {
        "host": SITE,
        "key": KEY,
        "keyLocation": f"https://{SITE}/{KEY}.txt",
        "urlList": urls,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"indexnow: submitted {len(urls)} URLs, HTTP {resp.status}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        print(f"indexnow: ping failed ({e}) — deploy unaffected", file=sys.stderr)
