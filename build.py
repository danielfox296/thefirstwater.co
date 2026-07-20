#!/usr/bin/env python3
"""
Firstwater — Site Builder
======================
Assembles static HTML pages from modular source files.

Usage:
    python3 build.py

Structure:
    _src/
      layouts/base.html       — HTML shell template
      partials/header.html    — shared nav (edit once, updates everywhere)
      partials/footer.html    — shared footer
      pages/
        <page-name>/
          config.json         — title, description, output path, etc.
          style.css           — page-specific CSS (optional)
          sections/           — content modules in alphabetical order
            01-hero.html
            02-section.html
            ...

Output:
    Root-level HTML files (index.html, how-it-works.html, etc.)
    blog/ subdirectory for blog posts

Notes:
    - Section files are plain HTML (no Markdown dependency needed)
    - Blog posts use output paths like "blog/slug.html" and get
      adjusted nav_prefix ("../") so relative links work
    - Page-specific CSS is injected as an inline <style> block
"""

import os
import posixpath
import sys
import json
import glob
import re
import html as html_mod
import hashlib

REPO     = os.path.dirname(os.path.abspath(__file__))
SRC      = os.path.join(REPO, '_src')
LAYOUTS  = os.path.join(SRC, 'layouts')
PARTIALS = os.path.join(SRC, 'partials')
PAGES    = os.path.join(SRC, 'pages')

# Sessions feed (WP5 seam): fetched from the events service at build time,
# cached in data/sessions-cache.json, never allowed to break the build.
# Stdlib-only module, safe to import unconditionally.
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from _src.lib import sessions_feed
# External-events feed (Front Range /calendar/): same graceful-fallback seam
# as sessions_feed. Stdlib-only, safe to import unconditionally.
from _src.lib import external_events
SITE_URL = 'https://thefirstwater.co'

# Sitewide description used in LocalBusiness + WebSite JSON-LD.
# Assembled from pre-existing approved schema copy plus the canonical line
# "Each night is built around something worth putting down." (VOICE.md).
SITE_DESCRIPTION = (
    'Facilitated sound sessions in Denver. Engineered sound experiences with '
    'sub-bass, studio-grade production, and formal ceremony. Each night is '
    'built around something worth putting down.'
)

# Public profile URLs (GBP, Eventbrite, Meetup, Insight Timer, socials) for
# schema.org sameAs on the LocalBusiness and publisher entities — the
# cross-source entity stitching the site-plan calls for. Add each URL to
# data/profiles.json as the account goes live; an empty list emits no key.
try:
    with open(os.path.join('data', 'profiles.json'), encoding='utf-8') as _f:
        SAME_AS = [u for u in json.load(_f).get('sameAs', []) if u]
except (FileNotFoundError, json.JSONDecodeError):
    SAME_AS = []


def page_url(output):
    """Public directory-style URL for a built output path.

    'index.html' -> SITE_URL/ ; 'about/index.html' -> SITE_URL/about/ ;
    anything else keeps its literal path.
    """
    if output == 'index.html':
        return f'{SITE_URL}/'
    if output.endswith('/index.html'):
        return f'{SITE_URL}/{output[:-len("index.html")]}'
    return f'{SITE_URL}/{output}'


def _clean_leaf(title):
    """Clean breadcrumb/display leaf name from a full <title>: drop the brand
    suffix and any descriptor tail after a colon or pipe. 'FAQ: What Happens
    ... | Firstwater' -> 'FAQ'."""
    t = title
    for suf in (' | Firstwater', ' — Firstwater'):
        if t.endswith(suf):
            t = t[:-len(suf)]
            break
    return t.split(':')[0].split(' | ')[0].strip()

# ---------------------------------------------------------------------------
# New blog renderer (Jinja2 + YAML pipeline)
# ---------------------------------------------------------------------------
# These imports are deferred so the existing build still works even when
# jinja2/markdown/pyyaml are not installed — they're only needed when a
# new-format blog post is encountered or --lint is used.

_blog_renderer = None   # lazy-loaded module reference
_jinja_env = None       # lazy-loaded Jinja2 Environment


def _ensure_blog_renderer():
    """Lazy-import the blog renderer and its dependencies.

    Returns (blog_renderer_module, jinja_env) or raises ImportError
    with a helpful install message.
    """
    global _blog_renderer, _jinja_env
    if _blog_renderer is not None:
        return _blog_renderer, _jinja_env

    # Make _src importable
    if REPO not in sys.path:
        sys.path.insert(0, REPO)

    try:
        from _src.lib import blog_renderer as br
        from _src.lib import reading_time  # noqa: F401 — validates import
    except ImportError as e:
        raise ImportError(
            f"Blog renderer dependency missing: {e}\n"
            "Install with: pip install jinja2 markdown pyyaml"
        ) from e

    templates_dir = os.path.join(SRC, 'templates')
    _blog_renderer = br
    _jinja_env = br.create_jinja_env(templates_dir)
    return _blog_renderer, _jinja_env


def _is_new_format_blog(page_path: str) -> bool:
    """Check if a page directory contains a new-format blog content.yaml."""
    yaml_path = os.path.join(page_path, 'content.yaml')
    if not os.path.exists(yaml_path):
        return False
    try:
        br, _ = _ensure_blog_renderer()
        return br.is_new_format(yaml_path)
    except ImportError:
        return False


def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def parse_simple_yaml(text):
    """Parse the subset of YAML used by content files (no PyYAML needed).
    Supports: nested string maps (key: value, with indented children)."""
    root = {}
    stack = [(root, -1)]  # (dict, indent_level)

    for raw_line in text.split('\n'):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())

        if ':' in stripped:
            k, v = stripped.split(':', 1)
            k = k.strip()
            v = v.strip()

            # Pop stack back to correct parent
            while len(stack) > 1 and stack[-1][1] >= indent:
                stack.pop()

            parent = stack[-1][0]

            if v:
                # Strip quotes and unescape
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1].replace('\\"', '"')
                elif v.startswith("'") and v.endswith("'"):
                    v = v[1:-1]
                parent[k] = v
            else:
                # Nested map
                child = {}
                parent[k] = child
                stack.append((child, indent))

    return root


def resolve_content(template, data):
    """Replace {{content.x.y}} placeholders with values from data dict."""
    if not data:
        return template

    def replace_placeholder(m):
        path = m.group(1).strip()
        obj = data
        for key in path.split('.'):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return m.group(0)
        return str(obj) if obj is not None else m.group(0)

    return re.sub(r'\{\{(content\.[\w.]+)\}\}', replace_placeholder, template)


def collect_sections(sections_dir):
    """Collect section files from a directory in alphabetical order."""
    files = sorted(glob.glob(os.path.join(sections_dir, '*.html')))
    return files


def lint():
    """Validate all new-format blog posts without generating HTML.

    Prints errors and warnings.  Returns True if all posts pass
    (warnings are OK), False if any errors were found.
    """
    br, _ = _ensure_blog_renderer()

    print('Linting new-format blog posts...\n')
    total_errors = []
    total_warnings = []

    for entry in sorted(os.listdir(PAGES)):
        if not entry.startswith('blog-'):
            continue
        page_path = os.path.join(PAGES, entry)
        yaml_path = os.path.join(page_path, 'content.yaml')
        if not os.path.exists(yaml_path):
            continue
        if not br.is_new_format(yaml_path):
            continue

        data = br.load_post(yaml_path)
        errors, warnings = br.validate_post(data, yaml_path)

        for w in warnings:
            print(f'  ⚠ {w}')
            total_warnings.append(w)
        for e in errors:
            print(f'  ✗ {e}')
            total_errors.append(e)

        if not errors and not warnings:
            print(f'  ✓ {entry}')
        elif not errors:
            print(f'  ✓ {entry} (with warnings)')

    print(f'\nLint complete: {len(total_errors)} error(s), {len(total_warnings)} warning(s).')

    if total_errors:
        print('\nLint FAILED — fix errors before building.')
        return False
    return True


def _strip_inline_markup(text):
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', text)
    text = re.sub(r'<a\s+[^>]*>([^<]*)</a>', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


_HOWTO_SUBHEAD_RE = re.compile(
    r'\b(this week|walk[- ]?through|where to start|how to test|how do you|what to do)\b',
    re.IGNORECASE,
)


def auto_extract_howto(post_data, min_steps=2, max_step_chars=400):
    """Extract HowTo steps from a procedural blog post.

    Conservative detector: returns a HowTo only when a prose block immediately
    follows a procedural-sounding subhead AND that prose block has ≥min_steps
    paragraphs each prefixed with `**Step name.**` markdown.

    Walks in reverse so a benchmarks section earlier in the post (which can
    also use bold-prefix paragraphs as category labels) doesn't get mistaken
    for steps. The procedural section is conventionally the last cluster of
    bold-prefix paragraphs before the CTA.
    """
    sections = post_data.get('sections', [])
    for i in range(len(sections) - 1, -1, -1):
        block = sections[i]
        if block.get('type') != 'prose':
            continue
        prev_subhead = None
        for j in range(i - 1, -1, -1):
            if sections[j].get('type') == 'subhead':
                prev_subhead = sections[j].get('text', '') or ''
                break
        if not prev_subhead or not _HOWTO_SUBHEAD_RE.search(prev_subhead):
            continue
        body = (block.get('body') or '').strip()
        paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
        steps = []
        for para in paragraphs:
            m = re.match(r'^\*\*([^*]+?)\*\*\.?\s*(.*)$', para, re.DOTALL)
            if not m:
                continue
            name = m.group(1).strip().rstrip('.').strip()
            text = m.group(2).strip()
            if not name or not text:
                continue
            text = _strip_inline_markup(text)
            if len(text) > max_step_chars:
                text = text[:max_step_chars].rsplit(' ', 1)[0] + '…'
            steps.append({"name": name, "text": text})
        if len(steps) >= min_steps:
            return {
                "name": post_data.get('title', '').strip(),
                "description": post_data.get('meta_description', '').strip(),
                "steps": steps,
            }
    return None


def auto_extract_faqs(post_data, max_answer_chars=600, min_answer_chars=40):
    """Extract FAQ pairs from a YAML post: question subheads + following prose.

    A subhead whose text ends in '?' becomes a question. The answer is the
    concatenation of every prose block until the next subhead, with markdown
    and inline HTML stripped, capped at max_answer_chars.
    """
    sections = post_data.get('sections', [])
    faqs = []
    for i, block in enumerate(sections):
        if block.get('type') != 'subhead':
            continue
        text = (block.get('text') or '').strip()
        if not text.endswith('?'):
            continue
        answer_parts = []
        for nxt in sections[i + 1:]:
            t = nxt.get('type')
            if t == 'subhead':
                break
            if t == 'prose':
                body = (nxt.get('body') or '').strip()
                if body:
                    answer_parts.append(body)
        if not answer_parts:
            continue
        clean = _strip_inline_markup('\n\n'.join(answer_parts))
        if len(clean) < min_answer_chars:
            continue
        if len(clean) > max_answer_chars:
            clean = clean[:max_answer_chars].rsplit(' ', 1)[0] + '…'
        faqs.append({"q": text, "a": clean})
    return faqs


def _ldjson(obj):
    """Serialize `obj` for embedding inside a <script type="application/ld+json">
    block, safe against markup breakout.

    json.dumps leaves '<', '>', '&' and the U+2028/U+2029 line separators raw, so
    a string field containing '</script>' would close the script element and let
    any following markup execute as HTML (stored XSS). Unicode-escape those
    characters: the JSON stays valid and semantically identical for consumers
    (a parser reads \\u003c as '<'), but no literal '</script>' can appear in the
    emitted page. HTML-entity escaping ('&lt;') is WRONG here — a <script>
    raw-text element does not decode entities, so consumers would read the
    literal entity.
    """
    return (json.dumps(obj, indent=2)
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026')
            .replace('\u2028', '\\u2028')
            .replace('\u2029', '\\u2029'))


def build():
    # Load shared pieces
    base   = read(os.path.join(LAYOUTS,  'base.html'))
    header = read(os.path.join(PARTIALS, 'header.html'))
    footer = read(os.path.join(PARTIALS, 'footer.html'))

    # Cache-bust styles.css with a content fingerprint so Cloudflare CDN
    # serves the new file immediately after each deploy without a manual purge.
    with open(os.path.join(REPO, 'styles.css'), 'rb') as _f:
        _styles_ver = hashlib.md5(_f.read()).hexdigest()[:8]
    base = base.replace('styles.css"', f'styles.css?v={_styles_ver}"')

    pages_built = []

    # Load the sessions feed (WP5). On any failure this falls back to the
    # committed data/sessions-cache.json, then to an empty feed — the build
    # always proceeds.
    print('Loading sessions feed...')
    feed = sessions_feed.load_feed(REPO)
    print()

    # Load the external-events (calendar) feed, same never-break-the-build
    # discipline: /feeds/calendar.json > committed data/external-events.json >
    # empty. Since the 2026-07 brand split the calendar LIVES at
    # soundbathcalendar.com; this feed is only used to emit a redirect stub
    # per old /calendar/event/<slug>/ URL. Every other page is unaffected.
    print('Loading calendar feed...')
    cal_feed = external_events.load_feed(REPO)
    print()

    # Find all page directories (supports nested: pages/blog-posts/slug/)
    page_dirs = []
    for root, dirs, files in os.walk(PAGES):
        if 'config.json' in files:
            page_dirs.append(root)

    for page_path in sorted(page_dirs):
        page_name = os.path.relpath(page_path, PAGES)

        config_path = os.path.join(page_path, 'config.json')
        config      = json.loads(read(config_path))

        if config.get('skip'):
            continue

        # ---------------------------------------------------------------
        # REDIRECT STUB
        # If config has `redirect_to`, emit a minimal meta-refresh page
        # and skip the full layout pipeline. Used to preserve SEO equity
        # for old slugs after a post is renamed/consolidated.
        # ---------------------------------------------------------------
        if config.get('redirect_to'):
            redirect_target = config['redirect_to']
            redirect_output = config.get('output', f'{page_name}.html')
            safe_target = html_mod.escape(redirect_target, quote=True)
            redirect_title = html_mod.escape(
                config.get('title', 'Redirecting… | Firstwater'), quote=True
            )
            # Canonical must be absolute; resolve relative targets against
            # the stub's own directory (meta-refresh/JS stay relative).
            if redirect_target.startswith(('http://', 'https://')):
                canonical_href = redirect_target
            else:
                _resolved = posixpath.normpath(posixpath.join(
                    posixpath.dirname(redirect_output), redirect_target))
                canonical_href = f'{SITE_URL}/{"" if _resolved == "." else _resolved}'
                if redirect_target.endswith('/') and not canonical_href.endswith('/'):
                    canonical_href += '/'
            safe_canonical = html_mod.escape(canonical_href, quote=True)
            stub = (
                '<!DOCTYPE html>\n'
                '<html lang="en">\n'
                '<head>\n'
                '<meta charset="utf-8">\n'
                f'<title>{redirect_title}</title>\n'
                f'<link rel="canonical" href="{safe_canonical}">\n'
                f'<meta http-equiv="refresh" content="0; url={safe_target}">\n'
                '<meta name="robots" content="noindex">\n'
                '</head>\n'
                '<body>\n'
                f'<p>This page has moved. Redirecting to <a href="{safe_target}">{safe_target}</a>.</p>\n'
                f'<script>window.location.replace("{safe_target}");</script>\n'
                '</body>\n'
                '</html>\n'
            )
            out_path = os.path.join(REPO, redirect_output)
            if not os.path.abspath(out_path).startswith(os.path.abspath(REPO)):
                print(f'  ✗ SKIPPED {redirect_output} — path escapes repo root')
                continue
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(stub)
            pages_built.append(redirect_output)
            print(f'  ↪ {redirect_output} → {redirect_target}')
            continue

        # ---------------------------------------------------------------
        # NEW-FORMAT BLOG POST DETECTION
        # If this page has a new-format content.yaml (with sections array),
        # render it through the Jinja2 blog pipeline instead of the old
        # section-file pipeline.  Old-format posts fall through untouched.
        # ---------------------------------------------------------------
        output_check = config.get('output', f'{page_name}.html')
        use_new_renderer = (
            output_check.startswith(('blog/', 'sessions/'))
            and _is_new_format_blog(page_path)
        )

        if use_new_renderer:
            # --- New blog renderer path ---
            br, env = _ensure_blog_renderer()
            # Compute the all-posts frontmatter list once per build and reuse.
            # Without this cache the call is O(n²): every new-format post
            # re-scans + YAML-parses every other post (~12k parses for 110
            # posts, ~5 min builds vs ~10s).
            if not hasattr(build, '_all_posts_cache'):
                build._all_posts_cache = br.collect_all_post_frontmatter(PAGES)
            all_posts = build._all_posts_cache

            try:
                content_html, post_data = br.render_post(page_path, env, all_posts)
            except (ValueError, FileNotFoundError) as exc:
                print(f'  ✗ {output_check} — {exc}')
                raise SystemExit(1)

            # Pull metadata from the YAML frontmatter.
            # config.seo_title (STRUCTURE-owned) wins so session <title>s follow
            # the SEO pattern from config.json without touching content.yaml
            # (which the content pipeline owns and which drives the H1). Falls
            # back to the post's own seo_title/title.
            _raw_title = (config.get('seo_title') or post_data.get('seo_title')
                          or post_data.get('title', config.get('title', 'Firstwater')))
            # Strip any existing suffix (legacy or canonical) before re-appending
            for legacy in (' | Firstwater', ' — Firstwater', ' | Sound Sessions', ' — Sound Sessions'):
                if _raw_title.endswith(legacy):
                    _raw_title = _raw_title[:-len(legacy)]
                    break
            title = f"{_raw_title} | Firstwater"
            description = post_data.get('meta_description',
                                        config.get('meta_description', ''))
            output      = output_check
            nav_prefix  = '../' * output_check.count('/')
            css_path    = nav_prefix
            content     = content_html

            # Store new-format post data for RSS generation later.
            # Session pages also use this renderer but are not blog posts:
            # only blog/ outputs belong in the feed.
            if output_check.startswith('blog/'):
                if not hasattr(build, '_new_format_posts'):
                    build._new_format_posts = []
                build._new_format_posts.append(post_data)

        else:
            # --- Original pipeline (unchanged) ---
            # seo_title (if set) drives the <title> tag; title drives the H1.
            title       = config.get('seo_title') or config.get('title', 'Firstwater')
            description = config.get('description', '') or config.get('meta_description', '')
            output      = config.get('output', f'{page_name}.html')

            # Determine nav_prefix based on output depth
            depth = output.count('/')
            nav_prefix = '../' * depth
            css_path = nav_prefix

            # Assemble content from sections in order
            sections_dir  = os.path.join(page_path, 'sections')
            if os.path.isdir(sections_dir):
                section_files = collect_sections(sections_dir)
                content = '\n\n'.join(read(f).strip() for f in section_files)
            else:
                content = ''

            # Apply content.yaml substitutions (if present)
            content_yaml_path = os.path.join(page_path, 'content.yaml')
            if os.path.exists(content_yaml_path):
                yaml_data = parse_simple_yaml(read(content_yaml_path))
                content = resolve_content(content, {'content': yaml_data})

        # ---------------------------------------------------------------
        # SESSIONS FEED INJECTION (WP5)
        # Session pages: append the dates/tickets block (inside the article)
        # for future on_sale/sold_out/scheduled sessions of this event.
        # Homepage: fill the hero next-date slot with the earliest future
        # on_sale/scheduled session. With no sessions (the empty-cache
        # state) both branches are no-ops and output is byte-identical.
        # ---------------------------------------------------------------
        page_sessions = []
        _sess_match = re.fullmatch(r'sessions/([^/]+)/index\.html', output)
        if _sess_match and use_new_renderer:
            page_sessions = sessions_feed.sessions_for_slug(feed, _sess_match.group(1))

            # Session pages reuse the blog article template but are selling
            # pages, not posts: strip the byline/read-time and reading-progress
            # bar, and put a plain status line where the byline was — the real
            # date/room when the feed has a live session, else the config
            # fallback ('Denver · first date being set'). Blog posts never pass
            # through here and keep both.
            _status = sessions_feed.status_line(
                page_sessions,
                fallback=config.get('status_line', 'Denver · first date being set'),
            )
            content = sessions_feed.strip_blog_chrome(content, _status)

            if page_sessions:
                # Depth-correct asset prefix (nav_prefix is '../' for all
                # new-renderer pages, which is wrong at sessions/<slug>/ depth).
                # render_sessions_block emits the .logistics card + one-click
                # ticket button + js/sessions.js; Event JSON-LD is emitted below.
                _asset_prefix = '../' * output.count('/')
                _block = sessions_feed.render_sessions_block(page_sessions, _asset_prefix)
                if '</article>' in content:
                    content = content.replace('</article>', _block + '\n\n</article>', 1)
                else:
                    content += '\n\n' + _block

        if output == 'index.html':
            _next = sessions_feed.next_session(feed)
            if _next:
                _hero_label = (
                    f'<a href="sessions/{html_mod.escape(_next["event_slug"], quote=True)}/">'
                    f'Denver &middot; next session '
                    f'{html_mod.escape(sessions_feed.fmt_date_short(_next["starts_at"]))}</a>'
                )
                content = re.sub(
                    r'(<span class="hero-date fade-up">).*?(</span>)',
                    lambda m: m.group(1) + _hero_label + m.group(2),
                    content, count=1, flags=re.DOTALL,
                )

        # ---------------------------------------------------------------
        # SHARED LAYOUT ASSEMBLY (both old and new pipelines converge)
        # ---------------------------------------------------------------

        # Robots meta tag — new-format YAML can override via `robots:` field
        robots_value = (post_data.get('robots') if use_new_renderer else None) \
                       or config.get('robots', 'index, follow')

        # Meta description tag
        meta_desc = ''
        if description:
            safe_desc = html_mod.escape(description, quote=True)
            meta_desc = f'<meta name="description" content="{safe_desc}">'

        # Load page-specific CSS
        style_path = os.path.join(page_path, 'style.css')
        page_style = ''
        if os.path.exists(style_path):
            css_content = read(style_path).strip()
            if css_content:
                page_style = f'<style>\n{css_content}\n  </style>'

        # (No separate blog.css: all .blog-* rules live in styles.css, which
        # base.html already links. A styles/blog.css link here 404'd.)

        # Apply nav_prefix to header and footer
        page_header = header.strip().replace('{{nav_prefix}}', nav_prefix)
        page_footer = footer.strip().replace('{{nav_prefix}}', nav_prefix)
        if config.get('no_chrome'):
            page_header = ''
            page_footer = ''

        # Compute canonical URL (directory-style; never /index.html)
        canonical_url = page_url(output)
        # Frontmatter canonical override (new-format posts): consolidate a
        # near-duplicate spoke onto its hub without a destructive 301 — the page
        # stays live for readers/internal links, ranking signal points to the hub.
        if use_new_renderer and post_data.get('canonical'):
            canonical_url = post_data['canonical']

        # Determine if blog post (the blog listing page is not a post:
        # it gets LocalBusiness schema, not Article + author)
        is_blog = output.startswith('blog/') and output != 'blog/index.html'

        # Clean title for OG/schema (strip suffixes)
        og_title = title
        for suffix in [' — Firstwater', ' — Sound Sessions']:
            if og_title.endswith(suffix):
                og_title = og_title[:-len(suffix)]
                break

        # Clean leaf name for BreadcrumbList (no brand suffix, no descriptor
        # tail). Session/blog pages use their content-owned display title;
        # root pages use an explicit config `breadcrumb`, else a derived name.
        if use_new_renderer:
            leaf_name = post_data.get('title') or _clean_leaf(title)
        else:
            leaf_name = config.get('breadcrumb') or _clean_leaf(title)

        # OG type
        og_type = 'article' if is_blog else 'website'

        # OG image — check new-format YAML first, then config.json
        og_image = f'{SITE_URL}/img/og-default.png'
        _og_from_yaml = post_data.get('og_image', '') if use_new_renderer else ''
        if _og_from_yaml:
            og_image = _og_from_yaml if _og_from_yaml.startswith('http') else f'{SITE_URL}/{_og_from_yaml.lstrip("/")}'
        elif config.get('og_image'):
            og_image = config['og_image'] if config['og_image'].startswith('http') else f'{SITE_URL}/{config["og_image"]}'
        elif is_blog:
            slug = output.replace('blog/', '').replace('.html', '')
            for ext in ['jpg', 'png']:
                img_path = os.path.join(REPO, 'img', 'blog', f'{slug}.{ext}')
                if os.path.exists(img_path):
                    og_image = f'{SITE_URL}/img/blog/{slug}.{ext}'
                    break

        # Build OG tags (escape user-provided strings)
        safe_og_title = html_mod.escape(og_title, quote=True)
        safe_og_desc  = html_mod.escape(description, quote=True)
        og_tags = '\n  '.join([
            f'<meta property="og:title" content="{safe_og_title}">',
            f'<meta property="og:description" content="{safe_og_desc}">',
            f'<meta property="og:url" content="{canonical_url}">',
            f'<meta property="og:type" content="{og_type}">',
            f'<meta property="og:image" content="{og_image}">',
            f'<meta property="og:site_name" content="Firstwater">',
            f'<meta property="og:locale" content="en_US">',
        ])

        if is_blog:
            # For new-format posts, dates come from YAML; for old, from config.json
            # Pseudonymity: the founder's legal name never enters machine-
            # readable data. Until name day the author is the business itself;
            # the [NAME] pseudonym replaces this when it lands.
            if use_new_renderer:
                _pub_time = post_data.get('date', '2026-03-25')
                _author_name = post_data.get('author', {}).get('name', 'Firstwater') if isinstance(post_data.get('author'), dict) else 'Firstwater'
            else:
                _pub_time = config.get('date_published', '2026-03-25')
                _author_name = 'Firstwater'
            og_tags += '\n  ' + f'<meta property="article:published_time" content="{_pub_time}">'
            og_tags += '\n  ' + f'<meta property="article:author" content="{_author_name}">'

        # Build Twitter Card tags
        twitter_tags = '\n  '.join([
            f'<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{safe_og_title}">',
            f'<meta name="twitter:description" content="{safe_og_desc}">',
            f'<meta name="twitter:image" content="{og_image}">',
        ])

        # Build JSON-LD schema
        if is_blog:
            if use_new_renderer:
                date_published = post_data.get('date', '2026-03-25')
                date_modified = post_data.get('last_updated', date_published)
            else:
                date_published = config.get('date_published', '2026-03-25')
                date_modified = config.get('date_modified', '2026-03-25')
            _schema_author = _author_name
            # Organization author until name day: a Person node would need a
            # real or pseudonymous name, and neither exists publicly yet.
            _author_type = 'Organization' if _schema_author == 'Firstwater' else 'Person'
            schema = {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": og_title,
                "author": {
                    "@type": _author_type,
                    "name": _schema_author
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "Firstwater",
                    "url": SITE_URL
                },
                "datePublished": date_published,
                "dateModified": date_modified,
                "description": description,
                "image": og_image,
                "mainEntityOfPage": {
                    "@type": "WebPage",
                    "@id": canonical_url
                },
                "about": [
                    {"@type": "Thing", "name": "sound sessions"},
                    {"@type": "Thing", "name": "sound baths"},
                    {"@type": "Thing", "name": "deep rest"}
                ]
            }
        else:
            schema = {
                "@context": "https://schema.org",
                "@type": "LocalBusiness",
                "name": "Firstwater",
                "url": SITE_URL,
                "image": f"{SITE_URL}/img/og-default.png",
                "description": SITE_DESCRIPTION,
                "areaServed": {
                    "@type": "AdministrativeArea",
                    "name": "Denver metro and the Colorado Front Range"
                },
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Denver",
                    "addressRegion": "CO",
                    "addressCountry": "US"
                },
                "priceRange": "$$",
                "knowsAbout": [
                    "sound sessions",
                    "sound baths",
                    "sound healing",
                    "engineered sub-bass sound experiences",
                    "group facilitation",
                    "group sound sessions",
                    "deep rest"
                ]
            }
            if SAME_AS:
                schema["sameAs"] = SAME_AS

        schema_json = f'<script type="application/ld+json">\n{json.dumps(schema, indent=2)}\n  </script>'

        # VideoObject schema — emitted for new-format blog posts that embed a
        # YouTube video (frontmatter `video:` block). Chapters become Clip
        # parts so Google and AI engines can deep-link key moments.
        if is_blog and use_new_renderer and post_data.get('video'):
            _v = post_data['video']
            _vid = _v.get('id', '')
            _watch = f'https://www.youtube.com/watch?v={_vid}'
            video_schema = {
                "@context": "https://schema.org",
                "@type": "VideoObject",
                "name": _v.get('title', og_title),
                "description": description,
                "thumbnailUrl": [og_image],
                "uploadDate": _v.get('upload_date', date_published),
                "contentUrl": _watch,
                "embedUrl": f'https://www.youtube.com/embed/{_vid}',
                "publisher": {
                    "@type": "Organization",
                    "name": "Firstwater",
                    "url": SITE_URL
                }
            }
            if _v.get('duration'):
                video_schema["duration"] = _v["duration"]
            _chapters = _v.get('chapters') or []
            if _chapters:
                video_schema["hasPart"] = [
                    {
                        "@type": "Clip",
                        "name": c.get('label', ''),
                        "startOffset": c.get('time', 0),
                        "url": f"{_watch}&t={c.get('time', 0)}s",
                    }
                    for c in _chapters
                ]
            schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(video_schema, indent=2)}\n  </script>'

        # WebSite schema — added to homepage only
        if output == 'index.html':
            website_schema = {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "Firstwater",
                "url": SITE_URL,
                "description": SITE_DESCRIPTION,
                "publisher": {
                    "@type": "Organization",
                    "name": "Firstwater"
                }
            }
            if SAME_AS:
                website_schema["publisher"]["sameAs"] = SAME_AS
            schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(website_schema, indent=2)}\n  </script>'

        # FAQPage schema — manual `faq` in config.json wins; otherwise
        # auto-extract Q-A pairs from question H2s in YAML-format blog posts.
        faq_items = config.get('faq', [])
        if not faq_items and is_blog and use_new_renderer:
            faq_items = auto_extract_faqs(post_data)
        if faq_items:
            faq_schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["q"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["a"]
                        }
                    }
                    for item in faq_items
                ]
            }
            schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(faq_schema, indent=2)}\n  </script>'

        # HowTo schema — auto-extract from YAML-format how-to-* blog posts
        # with a `**Step name.**`-prefixed paragraph cluster. Conservative
        # detector: returns None unless the post is clearly procedural.
        if is_blog and use_new_renderer:
            howto = auto_extract_howto(post_data)
            if howto:
                howto_schema = {
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": howto["name"],
                    "description": howto["description"],
                    "step": [
                        {
                            "@type": "HowToStep",
                            "position": i + 1,
                            "name": s["name"],
                            "text": s["text"],
                        }
                        for i, s in enumerate(howto["steps"])
                    ],
                }
                schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(howto_schema, indent=2)}\n  </script>'

        # BreadcrumbList schema — all pages except homepage
        if output != 'index.html':
            # Build breadcrumb items
            crumbs = [{"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_URL + "/"}]

            if is_blog:
                crumbs.append({"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE_URL + "/blog/"})
                crumbs.append({"@type": "ListItem", "position": 3, "name": leaf_name})
            elif output.startswith('sessions/') and output != 'sessions/index.html':
                crumbs.append({"@type": "ListItem", "position": 2, "name": "Sessions", "item": SITE_URL + "/sessions/"})
                crumbs.append({"@type": "ListItem", "position": 3, "name": leaf_name})
            else:
                crumbs.append({"@type": "ListItem", "position": 2, "name": leaf_name})

            breadcrumb_schema = {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": crumbs
            }
            schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(breadcrumb_schema, indent=2)}\n  </script>'

        # Service schema — corporate page only. Metadata layer, so planner
        # language is fine here (Appendix E finding 3).
        if output == 'corporate/index.html':
            service_schema = {
                "@context": "https://schema.org",
                "@type": "Service",
                "name": "Corporate & Group Sound Sessions",
                "serviceType": "Corporate wellness event",
                "provider": {"@type": "LocalBusiness", "name": "Firstwater", "url": "https://thefirstwater.co"},
                "areaServed": {"@type": "AdministrativeArea", "name": "Denver metro and the Colorado Front Range"},
                "offers": {"@type": "Offer", "price": "450", "priceCurrency": "USD"},
                "url": "https://thefirstwater.co/corporate/"
            }
            schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(service_schema, indent=2)}\n  </script>'

        # Event schema (WP5) — one per real dated session on this page.
        # Only ever emitted when the feed has a future dated session, which
        # is exactly DESIGN.md's "Event schema once a real date exists" rule.
        if page_sessions:
            _event_title = (post_data.get('title') if use_new_renderer else config.get('title', '')) or og_title
            _event_title = _event_title.split(' — ')[0].strip()
            for _s in page_sessions:
                _ev = sessions_feed.event_schema(
                    _s, _event_title, canonical_url, SITE_URL,
                    description=description, image=og_image,
                )
                schema_json += f'\n  <script type="application/ld+json">\n{json.dumps(_ev, indent=2)}\n  </script>'

        # Substitute into base layout
        html = base
        html = html.replace('{{title}}',            title)
        html = html.replace('{{robots}}',           robots_value)
        html = html.replace('{{meta_description}}', meta_desc)
        html = html.replace('{{canonical_url}}',    canonical_url)
        html = html.replace('{{css_path}}',         css_path)
        html = html.replace('{{page_style}}',       page_style)
        # Add RSS autodiscovery link
        og_tags = f'<link rel="alternate" type="application/rss+xml" title="Firstwater Blog" href="{css_path}rss.xml">\n  ' + og_tags

        html = html.replace('{{og_tags}}',          og_tags)
        html = html.replace('{{twitter_tags}}',     twitter_tags)
        html = html.replace('{{schema_json}}',      schema_json)
        html = html.replace('{{header}}',           page_header)
        html = html.replace('{{content}}',          content)
        html = html.replace('{{footer}}',           page_footer)
        # Second pass: content/header/footer may themselves use {{css_path}}
        # for depth-correct asset links (e.g. hero images in section files).
        html = html.replace('{{css_path}}',         css_path)

        # Write output file (validate path stays within repo)
        out_path = os.path.join(REPO, output)
        if not os.path.abspath(out_path).startswith(os.path.abspath(REPO)):
            print(f'  ✗ SKIPPED {output} — path escapes repo root')
            continue
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)

        pages_built.append(output)
        print(f'  ✓ {output}')

    # --- Per-event redirect stubs (/calendar/event/<slug>/) ---
    # The calendar moved to soundbathcalendar.com (2026-07 brand split). Every
    # old permalink URL gets a meta-refresh + canonical + noindex stub pointing
    # at its new home, so links and rankings transfer. No sitemap entries.
    _event_outputs = build_event_redirects(cal_feed)
    pages_built.extend(_event_outputs)

    print(f'\nBuilt {len(pages_built)} pages.')

    # --- Generate RSS Feed ---
    print('\nGenerating RSS feed...')
    import datetime

    rss_items = []
    # Track slugs already added by the new renderer to avoid duplicates
    new_format_slugs = set()
    if hasattr(build, '_new_format_posts'):
        for post_data in build._new_format_posts:
            slug = post_data.get('slug', '')
            new_format_slugs.add(slug)

            rss_title = post_data.get('title', 'Firstwater')
            rss_desc = post_data.get('meta_description', post_data.get('dek', ''))
            rss_date = post_data.get('date', '2026-03-25')
            rss_link = f'{SITE_URL}/blog/{slug}.html'

            try:
                dt = datetime.datetime.strptime(rss_date, '%Y-%m-%d')
                pub_date = dt.strftime('%a, %d %b %Y 00:00:00 +0000')
            except Exception:
                pub_date = 'Tue, 25 Mar 2026 00:00:00 +0000'

            rss_items.append({
                'title': rss_title,
                'link': rss_link,
                'description': rss_desc,
                'pubDate': pub_date,
                'date_sort': rss_date,
            })

    # Old-format posts (from config.json)
    for page_path in sorted(page_dirs):
        config_path = os.path.join(page_path, 'config.json')
        config = json.loads(read(config_path))
        if config.get('skip') or config.get('redirect_to'):
            continue
        output = config.get('output', '')
        # The blog index itself is not a post: startswith('blog/') is true for
        # it, so exclude it explicitly or it ships as a junk placeholder <item>.
        if not output.startswith('blog/') or output == 'blog/index.html':
            continue

        # Skip if this post was already added by the new renderer
        old_slug = output.replace('blog/', '').replace('.html', '')
        if old_slug in new_format_slugs:
            continue

        title = config.get('title', 'Firstwater')
        # Clean title
        for suffix in [' — Firstwater', ' — Sound Sessions']:
            if title.endswith(suffix):
                title = title[:-len(suffix)]
                break

        description = config.get('description', '') or config.get('meta_description', '')
        date_published = config.get('date_published', '2026-03-25')
        link = f'{SITE_URL}/{output}'

        # Convert date to RFC 822 format
        try:
            dt = datetime.datetime.strptime(date_published, '%Y-%m-%d')
            pub_date = dt.strftime('%a, %d %b %Y 00:00:00 +0000')
        except:
            pub_date = 'Tue, 25 Mar 2026 00:00:00 +0000'

        rss_items.append({
            'title': title,
            'link': link,
            'description': description,
            'pubDate': pub_date,
            'date_sort': date_published
        })

    # Sort by date descending
    rss_items.sort(key=lambda x: x['date_sort'], reverse=True)

    # Build RSS XML
    # Channel description reuses the blog index meta description verbatim
    # (_src/pages/blog-index/config.json) — no new copy.
    rss_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>Firstwater Blog</title>
  <link>{site_url}/blog/</link>
  <description>Writing on sound, rooms, and what people put down in them. From the producer behind Denver sound sessions.</description>
  <language>en-us</language>
  <atom:link href="{site_url}/rss.xml" rel="self" type="application/rss+xml"/>
'''.format(site_url=SITE_URL)

    for item in rss_items[:20]:  # Last 20 posts
        # Escape XML special chars in description
        desc = item['description'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        title = item['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        rss_xml += f'''  <item>
    <title>{title}</title>
    <link>{item['link']}</link>
    <description>{desc}</description>
    <pubDate>{item['pubDate']}</pubDate>
    <guid>{item['link']}</guid>
  </item>
'''

    rss_xml += '''</channel>
</rss>'''

    rss_path = os.path.join(REPO, 'rss.xml')
    with open(rss_path, 'w', encoding='utf-8') as f:
        f.write(rss_xml)
    print('  ✓ rss.xml')

    # --- Generate sitemap.xml (calendar URLs no longer listed) ---
    generate_sitemap(page_dirs)

    # --- Generate llms.txt ---
    generate_llms()


NEW_CALENDAR_URL = 'https://soundbathcalendar.com'


def build_event_redirects(cal_feed):
    """Emit a redirect stub per approved external event at the OLD permalink
    path /calendar/event/<slug>/index.html, pointing at the same slug on
    soundbathcalendar.com (the calendar's home since the 2026-07 brand split).

    Same stub anatomy as the config-driven `redirect_to` pages (journal.html
    pattern): canonical to the new URL, meta refresh, noindex, JS fallback.
    Slugs are deterministic from the dedup_key, so old and new sites agree.
    Returns the built output paths (never sitemap entries — stubs stay out).
    """
    print('\nGenerating calendar redirect stubs...')
    # Clear the old rendered pages first: the whole /calendar/event/ tree is
    # regenerated as stubs for exactly the current feed's slugs.
    import shutil
    shutil.rmtree(os.path.join(REPO, 'calendar', 'event'), ignore_errors=True)
    rows = external_events.approved_event_rows(cal_feed)
    if not rows:
        print('  (none)')
        return []

    built = []
    for row in rows:
        slug = external_events.event_slug(row)
        if not slug:
            continue
        output = f'calendar/event/{slug}/index.html'
        target = f'{NEW_CALENDAR_URL}/event/{slug}/'
        safe_target = html_mod.escape(target, quote=True)
        stub = (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '<meta charset="utf-8">\n'
            '<title>This page has moved | Firstwater</title>\n'
            f'<link rel="canonical" href="{safe_target}">\n'
            f'<meta http-equiv="refresh" content="0; url={safe_target}">\n'
            '<meta name="robots" content="noindex">\n'
            '</head>\n'
            '<body>\n'
            f'<p>This page has moved. Redirecting to <a href="{safe_target}">{safe_target}</a>.</p>\n'
            f'<script>window.location.replace("{safe_target}");</script>\n'
            '</body>\n'
            '</html>\n'
        )
        out_path = os.path.join(REPO, output)
        if not os.path.abspath(out_path).startswith(os.path.abspath(REPO)):
            print(f'  ✗ SKIPPED {output} — path escapes repo root')
            continue
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(stub)
        built.append(output)
        print(f'  ↪ {output} → {target}')

    return built


def _sitemap_url_entry(loc, lastmod):
    """Render one <url> block: loc + lastmod. changefreq/priority are dropped
    (Google ignores both); lastmod is the field crawlers actually use."""
    lines = ['  <url>', f'    <loc>{loc}</loc>']
    if lastmod:
        lines.append(f'    <lastmod>{lastmod}</lastmod>')
    lines.append('  </url>')
    return '\n'.join(lines) + '\n'


def _page_lastmod(page_path):
    """YYYY-MM-DD from the newest source file in a page dir (config.json,
    content.yaml, sections/*.html). Falls back to today if none stat-able."""
    import datetime
    candidates = [os.path.join(page_path, 'config.json'),
                  os.path.join(page_path, 'content.yaml')]
    candidates += glob.glob(os.path.join(page_path, 'sections', '*.html'))
    mtimes = [os.path.getmtime(p) for p in candidates if os.path.exists(p)]
    if not mtimes:
        return datetime.date.today().isoformat()
    return datetime.date.fromtimestamp(max(mtimes)).isoformat()


def generate_sitemap(page_dirs, extra_urls=None):
    """Generate sitemap.xml from page configs. Each <url> carries only <loc>
    and <lastmod> (changefreq/priority dropped — Google ignores them). lastmod
    comes from config `lastmod`, new-format blog YAML `last_updated`/`date`, or
    a fallback to the newest source-file mtime in the page dir.

    Exclusions: skip pages, redirect stubs, 404.html, any page whose
    effective robots value contains "noindex", and any new-format blog post
    whose YAML `canonical` points somewhere other than its own URL (it has
    consolidated onto a hub page and shouldn't compete with it in the
    sitemap).

    `extra_urls` is an iterable of (loc, lastmod) for pages emitted outside the
    _src/pages pipeline (the UPCOMING per-event calendar permalink pages); past
    event pages are already filtered out by the caller.

    Order: homepage, then root pages alphabetical by output, then the event
    permalink pages by loc, then blog posts by lastmod descending.
    """
    print('\nGenerating sitemap...')

    br = None  # lazy — only needed if a new-format blog post is encountered
    homepage_entry = None
    root_entries = []   # (output, xml)
    blog_entries = []   # (sort_key, output, xml)

    for page_path in sorted(page_dirs):
        page_name = os.path.relpath(page_path, PAGES)
        config_path = os.path.join(page_path, 'config.json')
        config = json.loads(read(config_path))

        if config.get('skip') or config.get('redirect_to'):
            continue

        output = config.get('output', f'{page_name}.html')
        if output == '404.html':
            continue

        is_blog = output.startswith('blog/') and output != 'blog/index.html'
        is_new_format = is_blog and _is_new_format_blog(page_path)

        if is_new_format:
            if br is None:
                br, _ = _ensure_blog_renderer()
            data = br.load_post(os.path.join(page_path, 'content.yaml'))
            robots_value = data.get('robots') or config.get('robots', 'index, follow')
            if 'noindex' in robots_value:
                continue
            canonical = data.get('canonical')
            own_url = page_url(output)
            if canonical and canonical != own_url:
                print(f'  ↷ sitemap: excluding {output} (canonical → {canonical})')
                continue
            lastmod = data.get('last_updated') or data.get('date')
            loc = own_url
        elif is_blog:
            # Old-format blog post fallback (none exist today, but keep the
            # pipeline correct if one shows up before being migrated).
            robots_value = config.get('robots', 'index, follow')
            if 'noindex' in robots_value:
                continue
            lastmod = config.get('date_modified') or config.get('date_published')
            loc = page_url(output)
        else:
            robots_value = config.get('robots', 'index, follow')
            if 'noindex' in robots_value:
                continue
            lastmod = config.get('lastmod')
            loc = page_url(output)

        # lastmod is the one field crawlers use; fall back to source mtime.
        if not lastmod:
            lastmod = _page_lastmod(page_path)
        xml = _sitemap_url_entry(loc, lastmod)

        if is_blog:
            blog_entries.append((lastmod or '', output, xml))
        elif output == 'index.html':
            homepage_entry = xml
        else:
            root_entries.append((output, xml))

    root_entries.sort(key=lambda x: x[0])
    # Newest lastmod first; fall back to output name for determinism on ties.
    blog_entries.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # Upcoming event permalink pages, sorted by loc for a stable ordering.
    event_entries = sorted(
        ((loc, _sitemap_url_entry(loc, lastmod)) for loc, lastmod in (extra_urls or [])),
        key=lambda x: x[0],
    )

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    if homepage_entry:
        parts.append(homepage_entry.rstrip('\n'))
    parts.extend(xml.rstrip('\n') for _, xml in root_entries)
    parts.extend(xml.rstrip('\n') for _, xml in event_entries)
    parts.extend(xml.rstrip('\n') for _, _, xml in blog_entries)
    parts.append('</urlset>')
    sitemap_xml = '\n'.join(parts) + '\n'

    with open(os.path.join(REPO, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    print(f'  ✓ sitemap.xml ({1 if homepage_entry else 0}+{len(root_entries)} root, '
          f'{len(event_entries)} event, {len(blog_entries)} blog)')


def generate_llms():
    """Generate llms.txt from _src/llms-template.txt (hand-maintained prose
    and non-blog sections) plus a generated blog-post list.

    Each blog line is `- [title](url): llms_description-or-meta_description`.
    Excludes new-format blog posts whose effective robots value contains
    "noindex" (none exist today, but the rule mirrors the sitemap gate).
    Order: lastmod (last_updated-or-date) descending — the current
    hand-maintained file has no single clear sort rule (checked: not date
    ascending, not date descending, not directory/alphabetical order — it's
    organic insertion order from manual edits over time), so per the
    fallback rule this uses date descending, newest first.
    """
    print('\nGenerating llms.txt...')

    br, _ = _ensure_blog_renderer()

    entries = []  # (sort_key, line)
    for entry in sorted(os.listdir(PAGES)):
        if not entry.startswith('blog-'):
            continue
        page_path = os.path.join(PAGES, entry)
        config_path = os.path.join(page_path, 'config.json')
        yaml_path = os.path.join(page_path, 'content.yaml')
        if not os.path.exists(config_path) or not os.path.exists(yaml_path):
            continue
        config = json.loads(read(config_path))
        if config.get('skip') or config.get('redirect_to'):
            continue
        if not br.is_new_format(yaml_path):
            continue  # old-format posts: none exist today

        data = br.load_post(yaml_path)
        robots_value = data.get('robots') or config.get('robots', 'index, follow')
        if 'noindex' in robots_value:
            continue

        output = config.get('output', f'{entry}.html')
        # Mirror the sitemap gate: a post whose canonical points at a different
        # page (a slug shared with a distinct root asset) is consolidated away —
        # list only the canonical URL, not this duplicate. (WEB-F1/F2, 2026-07-12)
        canonical = data.get('canonical')
        own_url = page_url(output)
        if canonical and canonical != own_url:
            print(f'  ↷ llms: excluding {output} (canonical → {canonical})')
            continue

        slug = data.get('slug', entry.replace('blog-', '', 1))
        url = f'{SITE_URL}/blog/{slug}.html'
        title = data.get('title', 'Firstwater')
        description = data.get('llms_description') or data.get('meta_description', '')
        lastmod = data.get('last_updated') or data.get('date') or ''

        line = f'- [{title}]({url}): {description}'
        entries.append((lastmod, output, line))

    entries.sort(key=lambda x: (x[0], x[1]), reverse=True)
    blog_block = '\n'.join(line for _, _, line in entries)

    # Only emit the "## Blog" section when posts exist — no empty heading.
    blog_section = ('\n## Blog\n\n' + blog_block + '\n') if blog_block else ''

    template_path = os.path.join(SRC, 'llms-template.txt')
    template = read(template_path)
    llms_txt = template.replace('{{blog_section}}', blog_section)
    if not llms_txt.endswith('\n'):
        llms_txt += '\n'

    with open(os.path.join(REPO, 'llms.txt'), 'w', encoding='utf-8') as f:
        f.write(llms_txt)
    print(f'  ✓ llms.txt ({len(entries)} blog entries)')


if __name__ == '__main__':
    if '--lint' in sys.argv:
        print('Firstwater — Lint mode\n')
        ok = lint()
        sys.exit(0 if ok else 1)
    else:
        print('Building Firstwater...\n')
        build()
        print('\nDone.')
