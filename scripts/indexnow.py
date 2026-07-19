#!/usr/bin/env python3
"""
IndexNow ping — submits every sitemap URL after a deploy.

Runs in CI after the Pages deploy step (see .github/workflows/deploy.yml).
Stdlib only. Never fails the deploy: any error is reported and swallowed.

Key file: /<KEY>.txt at the site root, served at https://thefirstwater.co/<KEY>.txt
"""

import json
import re
import sys
import urllib.request

SITE = "thefirstwater.co"
KEY = "09dfe161f3a062373ee2bbf7766db185"
ENDPOINT = "https://api.indexnow.org/indexnow"
SITEMAP = "sitemap.xml"


def main():
    with open(SITEMAP, encoding="utf-8") as f:
        urls = re.findall(r"<loc>(.*?)</loc>", f.read())
    if not urls:
        print("indexnow: no URLs found in sitemap, skipping")
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
        main()
    except Exception as e:
        print(f"indexnow: ping failed ({e}) — deploy unaffected", file=sys.stderr)
