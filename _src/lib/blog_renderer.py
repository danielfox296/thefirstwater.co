"""
Blog renderer for the Entuned "Bowie" static site generator.

Reads new-format content.yaml files (frontmatter + sections array of typed
blocks), validates against schema, and renders through Jinja2 templates.

Old-format posts (flat keys like h1_1, p_1) are detected and skipped so
the existing build pipeline handles them unchanged.
"""

import os
import re

try:
    import yaml
except ImportError:
    raise ImportError(
        "PyYAML is required for the blog renderer.\n"
        "Install it with: pip install pyyaml"
    )

try:
    import jinja2
    import markupsafe
except ImportError:
    raise ImportError(
        "Jinja2 is required for the blog renderer.\n"
        "Install it with: pip install jinja2 markdown"
    )

try:
    import markdown as md_lib
except ImportError:
    raise ImportError(
        "The markdown library is required for the blog renderer.\n"
        "Install it with: pip install jinja2 markdown"
    )

from _src.lib.reading_time import calculate_reading_time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_EYEBROWS = {'A SOUND SESSION', 'JOURNAL', 'FIELD NOTES', 'SOUND', 'PRACTICE'}

KNOWN_BLOCK_TYPES = {
    'prose', 'subhead', 'pullquote', 'stat_callout', 'data_viz',
    'figure', 'aside', 'comparison_table', 'key_takeaways',
    'methodology', 'cta', 'related',
    'video', 'transcript', 'references',
}

# Fields required at the top level of every new-format content.yaml.
REQUIRED_FRONTMATTER = {
    'title', 'slug', 'eyebrow', 'dek', 'date', 'author',
    'meta_description', 'sections',
}

# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def is_new_format(yaml_path: str) -> bool:
    """Return True if content.yaml uses the new blog schema.

    New format: has a top-level 'sections' key whose value is a list.
    Old format: flat keys like h1_1, p_1, btn_1 — no 'sections' key.

    Old-format files use a simplified YAML dialect (parsed by the custom
    parse_simple_yaml in build.py) that may not be valid strict YAML.
    If PyYAML can't parse the file, it's definitely old format.
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    sections = data.get('sections')
    return isinstance(sections, list)


def load_post(yaml_path: str) -> dict:
    """Parse a new-format content.yaml and return the full dict."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_post(data: dict, yaml_path: str = '<unknown>') -> tuple:
    """Validate a parsed post dict against the blog schema.

    Returns (errors: list[str], warnings: list[str]).
    Errors are fatal — build must fail.  Warnings are informational.
    All problems are collected before returning (no fail-fast).
    """
    errors = []
    warnings = []

    # -- Required top-level fields ------------------------------------------
    for field in REQUIRED_FRONTMATTER:
        if field not in data:
            errors.append(f"[{yaml_path}] Missing required field: {field}")

    # -- Eyebrow taxonomy ---------------------------------------------------
    eyebrow = data.get('eyebrow', '')
    if eyebrow and eyebrow not in VALID_EYEBROWS:
        errors.append(
            f"[{yaml_path}] Invalid eyebrow '{eyebrow}'. "
            f"Must be one of: {', '.join(sorted(VALID_EYEBROWS))}"
        )

    # -- Author must have 'name' -------------------------------------------
    author = data.get('author')
    if isinstance(author, dict):
        if 'name' not in author:
            errors.append(f"[{yaml_path}] author must have a 'name' field")
    elif author is not None:
        errors.append(f"[{yaml_path}] 'author' must be a mapping with at least 'name'")

    # -- Hero must have 'src' and 'alt' ------------------------------------
    hero = data.get('hero')
    if isinstance(hero, dict):
        if 'src' not in hero:
            errors.append(f"[{yaml_path}] hero must have a 'src' field")
        if 'alt' not in hero:
            errors.append(f"[{yaml_path}] hero must have an 'alt' field")
    elif hero is not None:
        errors.append(f"[{yaml_path}] 'hero' must be a mapping with 'src' and 'alt'")

    # -- Sections -----------------------------------------------------------
    sections = data.get('sections', [])
    if not isinstance(sections, list):
        errors.append(f"[{yaml_path}] 'sections' must be a list of block dicts")
        return errors, warnings

    has_methodology = False
    has_pilot_data_viz = False
    key_takeaways_index = None

    for i, block in enumerate(sections):
        if not isinstance(block, dict):
            errors.append(f"[{yaml_path}] sections[{i}] is not a dict")
            continue

        btype = block.get('type')
        if btype is None:
            errors.append(f"[{yaml_path}] sections[{i}] missing 'type' field")
            continue

        if btype not in KNOWN_BLOCK_TYPES:
            errors.append(
                f"[{yaml_path}] sections[{i}] unknown block type '{btype}'. "
                f"Known types: {', '.join(sorted(KNOWN_BLOCK_TYPES))}"
            )
            continue

        # Block-specific validation
        if btype == 'stat_callout':
            if 'source' not in block:
                errors.append(
                    f"[{yaml_path}] sections[{i}] stat_callout missing "
                    f"required 'source' field"
                )

        if btype == 'data_viz':
            caption = str(block.get('caption', '')).lower()
            source = str(block.get('source', '')).lower()
            if 'pilot' in caption or 'pilot' in source:
                has_pilot_data_viz = True

        if btype == 'methodology':
            has_methodology = True

        if btype == 'key_takeaways':
            if key_takeaways_index is None:
                key_takeaways_index = i
            else:
                warnings.append(
                    f"[{yaml_path}] Multiple key_takeaways blocks found "
                    f"(indices {key_takeaways_index} and {i})"
                )

    # -- Pilot data_viz requires methodology block --------------------------
    if has_pilot_data_viz and not has_methodology:
        errors.append(
            f"[{yaml_path}] Post contains data_viz citing pilot data but "
            f"no 'methodology' block is present"
        )

    # -- key_takeaways should be first section (warning, not error) ---------
    if key_takeaways_index is not None and key_takeaways_index != 0:
        warnings.append(
            f"[{yaml_path}] key_takeaways block is at sections[{key_takeaways_index}] "
            f"but should be the first section for clean YAML ordering"
        )

    return errors, warnings


# ---------------------------------------------------------------------------
# Jinja2 environment setup
# ---------------------------------------------------------------------------

def create_jinja_env(templates_dir: str) -> jinja2.Environment:
    """Create a Jinja2 environment rooted at the templates directory.

    Registers the `markdown` filter for prose/aside body rendering.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_dir),
        autoescape=jinja2.select_autoescape(['html']),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Custom filter: render Markdown to HTML
    def _markdown_filter(text):
        if not text:
            return ''
        return md_lib.markdown(
            str(text),
            extensions=['smarty', 'tables', 'fenced_code'],
        )

    env.filters['markdown'] = _markdown_filter

    # Custom filter: slugify text for auto-generated anchors
    def _slugify(text):
        slug = re.sub(r'[^\w\s-]', '', str(text).lower())
        return re.sub(r'[\s_]+', '-', slug).strip('-')

    env.filters['slugify'] = _slugify

    return env


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------

def render_block(block: dict, ctx: dict, env: jinja2.Environment) -> str:
    """Render a single typed block to HTML via its Jinja2 partial.

    Raises jinja2.TemplateNotFound if the block template is missing.
    Raises ValueError for unknown block types (belt-and-suspenders —
    validation should catch this before we get here).
    """
    block_type = block.get('type')
    if block_type not in KNOWN_BLOCK_TYPES:
        raise ValueError(f"Unknown block type: '{block_type}'")

    # Auto-generate anchor for subheads if not provided
    if block_type == 'subhead' and 'anchor' not in block:
        block = dict(block)  # shallow copy so we don't mutate source
        text = block.get('text', '')
        block['anchor'] = env.filters['slugify'](text)

    # Generate inline SVG for data_viz blocks
    if block_type == 'data_viz':
        block = dict(block)  # shallow copy
        try:
            from _src.lib.data_viz import render_chart
            block['svg_html'] = markupsafe.Markup(render_chart(
                chart_type=block.get('chart_type', 'bar'),
                data=block.get('data', []),
                title=block.get('title', ''),
                caption=block.get('caption', ''),
                source=block.get('source', ''),
            ))
        except ImportError:
            block['svg_html'] = markupsafe.Markup(
                '<p style="color:#d7af74;">[data_viz: install data_viz.py]</p>'
            )

    # Resolve related posts slugs to full post objects
    if block_type == 'related':
        block = dict(block)
        all_posts = ctx.get('all_posts', [])
        posts_by_slug = {p.get('slug', ''): p for p in all_posts}
        nav_prefix = ctx.get('nav_prefix', '../')
        resolved = []
        for item in block.get('posts', []):
            slug = item.get('slug', '') if isinstance(item, dict) else str(item)
            post = dict(posts_by_slug.get(slug, {
                'slug': slug,
                'title': slug.replace('-', ' ').title(),
                'eyebrow': '',
                'dek': '',
            }))
            # Ensure slug is set
            if 'slug' not in post:
                post['slug'] = slug
            # Resolve hero image path — new-format or standard img/blog/{slug}.jpg
            if 'hero_img' not in post:
                hero = post.get('hero', {})
                if isinstance(hero, dict) and hero.get('src'):
                    post['hero_img'] = hero['src']
                else:
                    post['hero_img'] = f'{nav_prefix}img/blog/{slug}.jpg'
            resolved.append(post)
        block['posts'] = resolved

    template = env.get_template(f"blocks/{block_type}.html")
    return template.render(block=block, ctx=ctx)


# ---------------------------------------------------------------------------
# Post rendering
# ---------------------------------------------------------------------------

def _reorder_sections(sections: list) -> list:
    """Hoist key_takeaways to the front and cta to just before related.

    Returns a new list; does not mutate the input.

    Layout order:
      1. key_takeaways (if present)
      2. all other sections (excluding key_takeaways, cta, related)
      3. cta (if present)
      4. related (if present)
    """
    takeaways = []
    cta = []
    related = []
    body = []

    for block in sections:
        btype = block.get('type')
        if btype == 'key_takeaways':
            takeaways.append(block)
        elif btype == 'cta':
            cta.append(block)
        elif btype == 'related':
            related.append(block)
        else:
            body.append(block)

    return takeaways + body + cta + related


def render_post(post_dir: str, env: jinja2.Environment,
                all_posts: list = None) -> tuple:
    """Render a new-format blog post to full page HTML.

    Args:
        post_dir:  Absolute path to the blog-* page directory.
        env:       Jinja2 environment (from create_jinja_env).
        all_posts: List of frontmatter dicts for all blog posts
                   (used by the related block to look up linked slugs).

    Returns:
        (html_string, post_data_dict)
        where post_data_dict is the parsed YAML with computed fields
        (reading_time, etc.) — useful for blog index / RSS generation.

    Raises on validation errors.
    """
    yaml_path = os.path.join(post_dir, 'content.yaml')
    data = load_post(yaml_path)

    # Validate
    errors, warnings = validate_post(data, yaml_path)
    for w in warnings:
        print(f"  ⚠ WARNING: {w}")
    if errors:
        msg = "Blog schema validation failed:\n" + "\n".join(f"  ✗ {e}" for e in errors)
        raise ValueError(msg)

    # Compute reading time
    sections = data.get('sections', [])
    reading_time = calculate_reading_time(sections)
    data['reading_time'] = reading_time

    # Determine slug and nav_prefix
    slug = data.get('slug', os.path.basename(post_dir).replace('blog-', '', 1))
    nav_prefix = '../'  # blog posts always live at blog/<slug>.html

    # Build context dict shared across all block templates
    ctx = {
        'slug': slug,
        'nav_prefix': nav_prefix,
        'all_posts': all_posts or [],
        'post': data,
    }

    # Separate hoisted blocks from body sections
    key_takeaways_html = ''
    cta_html = ''
    related_html = ''
    body_blocks = []

    for block in sections:
        btype = block.get('type')
        if btype == 'key_takeaways':
            key_takeaways_html = render_block(block, ctx, env)
        elif btype == 'cta':
            cta_html = render_block(block, ctx, env)
        elif btype == 'related':
            related_html = render_block(block, ctx, env)
        else:
            body_blocks.append(render_block(block, ctx, env))

    sections_html = '\n\n'.join(body_blocks)

    # Render the blog post template (article content only — base.html wraps it)
    try:
        page_template = env.get_template('blog_post.html')
    except jinja2.TemplateNotFound:
        raise FileNotFoundError(
            "Missing template: _src/templates/blog_post.html\n"
            "Create it before building new-format blog posts."
        )

    page_html = page_template.render(
        # Unpack all frontmatter as individual template variables
        title=data.get('title', ''),
        slug=slug,
        eyebrow=data.get('eyebrow', ''),
        dek=data.get('dek', ''),
        date=data.get('date', ''),
        author=data.get('author', {}),
        hero=data.get('hero', {}),
        meta_description=data.get('meta_description', ''),
        og_image=data.get('og_image', ''),
        tags=data.get('tags', []),
        reading_time=reading_time,
        nav_prefix=nav_prefix,
        # Pre-rendered HTML blocks
        sections_html=sections_html,
        key_takeaways_html=key_takeaways_html,
        cta_html=cta_html,
        related_html=related_html,
    )

    return page_html, data


def collect_all_post_frontmatter(pages_dir: str) -> list:
    """Scan all blog-* directories and return a list of frontmatter dicts.

    Includes BOTH new-format and old-format posts so the related block
    can resolve slugs across the entire blog.  Each dict includes at
    minimum: title, slug, eyebrow, dek, post_dir.
    """
    posts = []
    for entry in sorted(os.listdir(pages_dir)):
        if not entry.startswith('blog-'):
            continue
        post_dir = os.path.join(pages_dir, entry)
        yaml_path = os.path.join(post_dir, 'content.yaml')
        config_path = os.path.join(post_dir, 'config.json')

        if is_new_format(yaml_path) if os.path.exists(yaml_path) else False:
            # New-format post — full YAML frontmatter
            try:
                data = load_post(yaml_path)
                data['post_dir'] = post_dir
                posts.append(data)
            except Exception:
                continue
        elif os.path.exists(config_path):
            # Old-format post — extract basics from config.json + content.yaml
            try:
                import json
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                raw_title = config.get('title', '')
                # Strip " — Entuned Blog" suffix
                clean_title = raw_title
                for suffix in [' — Entuned Blog', ' — Entuned']:
                    if clean_title.endswith(suffix):
                        clean_title = clean_title[:-len(suffix)]
                        break
                slug = entry.replace('blog-', '', 1)
                posts.append({
                    'title': clean_title,
                    'slug': slug,
                    'eyebrow': '',
                    'dek': config.get('meta_description', ''),
                    'post_dir': post_dir,
                })
            except Exception:
                continue
    return posts
