"""
Server-side SVG chart generator for Firstwater blog data visualizations.

Generates inline SVG strings from structured data using brand tokens.
No third-party chart libraries -- pure Python SVG generation.

Brand tokens (DESIGN.md):
    Chart bg:    #12151A  (--panel, raised surface on dark)
    Text:        #F5F7FA  (--paper / --text-on-dark)
    Muted text:  #98A1AB  (--gray)
    Accent:      #62B6E8  (--accent, primary data color)
    Gray:        #98A1AB  (--gray, secondary data color)
    Heading:     Space Grotesk
    Body:        Inter
    Radius:      0 everywhere (sharp editorial edges)
"""

__all__ = ["render_chart"]

# -- Brand tokens ----------------------------------------------------------

_BG = "#12151A"
_TEXT = "#F5F7FA"
_TEXT_MUTED = "#98A1AB"
_SERIES1 = "#62B6E8"
_SERIES2 = "#98A1AB"
_FONT_HEADING = "'Space Grotesk', sans-serif"
_FONT_BODY = "Inter, sans-serif"

# -- Helpers ----------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape XML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _format_value(v) -> str:
    """Format a numeric value for display -- drop trailing .0 on whole numbers."""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _wrap_figure(svg: str, caption: str, source: str) -> str:
    """Wrap an SVG chart in a <figure> with caption and source."""
    parts = ['<figure class="blog-data-viz">']
    parts.append(svg)
    if caption or source:
        parts.append("  <figcaption>")
        if caption:
            parts.append(f"    <span>{_escape(caption)}</span>")
        if source:
            parts.append(
                f'    <cite style="display:block;font-size:0.75em;'
                f"color:{_TEXT_MUTED};margin-top:0.25em;font-style:normal\">"
                f"Source: {_escape(source)}</cite>"
            )
        parts.append("  </figcaption>")
    parts.append("</figure>")
    return "\n".join(parts)


# -- Bar chart --------------------------------------------------------------


def _render_bar(data: list, title: str) -> str:
    """Render a vertical bar chart as SVG.

    Args:
        data: list of {"label": str, "value": number}
        title: chart title

    Returns:
        SVG string.
    """
    if not data:
        raise ValueError("Bar chart requires at least one data point.")

    vb_w, vb_h = 600, 400
    pad_top = 60
    pad_bottom = 60
    pad_left = 60
    pad_right = 30
    chart_w = vb_w - pad_left - pad_right
    chart_h = vb_h - pad_top - pad_bottom

    values = [d["value"] for d in data]
    max_val = max(values) if max(values) > 0 else 1
    # Round up to a nice ceiling for the y-axis
    nice_ceil = _nice_ceil(max_val)

    n = len(data)
    bar_gap_ratio = 0.3
    group_w = chart_w / n
    bar_w = group_w * (1 - bar_gap_ratio)
    gap = group_w * bar_gap_ratio

    # Grid lines (4 horizontal lines)
    grid_lines = []
    y_labels = []
    for i in range(5):
        frac = i / 4
        y = pad_top + chart_h - (frac * chart_h)
        label_val = frac * nice_ceil
        grid_lines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" '
            f'x2="{vb_w - pad_right}" y2="{y:.1f}" '
            f'stroke="{_TEXT_MUTED}" stroke-width="0.5" stroke-dasharray="4,4"/>'
        )
        y_labels.append(
            f'<text x="{pad_left - 8}" y="{y:.1f}" '
            f'text-anchor="end" dominant-baseline="middle" '
            f'fill="{_TEXT_MUTED}" font-size="11" '
            f'font-family="{_FONT_BODY}">{_format_value(label_val)}</text>'
        )

    # Bars
    bars = []
    x_labels = []
    for i, d in enumerate(data):
        x = pad_left + i * group_w + gap / 2
        bar_h = (d["value"] / nice_ceil) * chart_h if nice_ceil else 0
        y = pad_top + chart_h - bar_h

        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{_SERIES1}"/>'
        )
        # Value label above bar
        bars.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" '
            f'text-anchor="middle" fill="{_TEXT}" font-size="12" '
            f'font-family="{_FONT_BODY}">{_format_value(d["value"])}</text>'
        )
        # X-axis label
        x_labels.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{pad_top + chart_h + 20}" '
            f'text-anchor="middle" fill="{_TEXT}" font-size="11" '
            f'font-family="{_FONT_BODY}">{_escape(d["label"])}</text>'
        )

    # Baseline
    baseline = (
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{vb_w - pad_right}" y2="{pad_top + chart_h}" '
        f'stroke="{_TEXT_MUTED}" stroke-width="1"/>'
    )

    # Title
    title_el = (
        f'<text x="{pad_left}" y="30" fill="{_TEXT}" font-size="18" '
        f'font-weight="700" font-family="{_FONT_HEADING}">'
        f"{_escape(title)}</text>"
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" '
        f'role="img" aria-label="{_escape(title)}" '
        f'style="width:100%;height:auto;background:{_BG}">\n'
        f"  {title_el}\n"
        + "\n".join(f"  {g}" for g in grid_lines)
        + "\n"
        + "\n".join(f"  {y}" for y in y_labels)
        + "\n"
        f"  {baseline}\n"
        + "\n".join(f"  {b}" for b in bars)
        + "\n"
        + "\n".join(f"  {x}" for x in x_labels)
        + "\n</svg>"
    )
    return svg


# -- Line chart -------------------------------------------------------------


def _render_line(data: list, title: str) -> str:
    """Render a line chart as SVG, supporting single or dual series.

    Args:
        data: list of {"label": str, "value": number[, "value2": number]}
        title: chart title

    Returns:
        SVG string.
    """
    if not data:
        raise ValueError("Line chart requires at least one data point.")

    vb_w, vb_h = 600, 400
    pad_top = 60
    pad_bottom = 60
    pad_left = 60
    pad_right = 30
    chart_w = vb_w - pad_left - pad_right
    chart_h = vb_h - pad_top - pad_bottom

    has_dual = any("value2" in d for d in data)
    all_values = [d["value"] for d in data]
    if has_dual:
        all_values += [d.get("value2", 0) for d in data]
    max_val = max(all_values) if max(all_values) > 0 else 1
    min_val = min(0, min(all_values))
    nice_ceil = _nice_ceil(max_val)

    n = len(data)

    def x_pos(i):
        if n == 1:
            return pad_left + chart_w / 2
        return pad_left + (i / (n - 1)) * chart_w

    def y_pos(v):
        return pad_top + chart_h - ((v / nice_ceil) * chart_h) if nice_ceil else pad_top + chart_h

    # Grid lines
    grid_lines = []
    y_labels = []
    for i in range(5):
        frac = i / 4
        y = pad_top + chart_h - (frac * chart_h)
        label_val = frac * nice_ceil
        grid_lines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" '
            f'x2="{vb_w - pad_right}" y2="{y:.1f}" '
            f'stroke="{_TEXT_MUTED}" stroke-width="0.5" stroke-dasharray="4,4"/>'
        )
        y_labels.append(
            f'<text x="{pad_left - 8}" y="{y:.1f}" '
            f'text-anchor="end" dominant-baseline="middle" '
            f'fill="{_TEXT_MUTED}" font-size="11" '
            f'font-family="{_FONT_BODY}">{_format_value(label_val)}</text>'
        )

    # Primary line
    points_1 = [(x_pos(i), y_pos(d["value"])) for i, d in enumerate(data)]
    polyline_1 = " ".join(f"{x:.1f},{y:.1f}" for x, y in points_1)

    # Dots for primary
    dots_1 = []
    for x, y in points_1:
        dots_1.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
            f'fill="{_SERIES1}" stroke="{_BG}" stroke-width="2"/>'
        )

    # Secondary line (if dual)
    line_2_el = ""
    dots_2 = []
    if has_dual:
        points_2 = [(x_pos(i), y_pos(d.get("value2", 0))) for i, d in enumerate(data)]
        polyline_2 = " ".join(f"{x:.1f},{y:.1f}" for x, y in points_2)
        line_2_el = (
            f'<polyline points="{polyline_2}" '
            f'fill="none" stroke="{_SERIES2}" stroke-width="2.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for x, y in points_2:
            dots_2.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                f'fill="{_SERIES2}" stroke="{_BG}" stroke-width="2"/>'
            )

    # X-axis labels
    x_labels = []
    for i, d in enumerate(data):
        x_labels.append(
            f'<text x="{x_pos(i):.1f}" y="{pad_top + chart_h + 20}" '
            f'text-anchor="middle" fill="{_TEXT}" font-size="11" '
            f'font-family="{_FONT_BODY}">{_escape(d["label"])}</text>'
        )

    # Baseline
    baseline = (
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{vb_w - pad_right}" y2="{pad_top + chart_h}" '
        f'stroke="{_TEXT_MUTED}" stroke-width="1"/>'
    )

    # Title
    title_el = (
        f'<text x="{pad_left}" y="30" fill="{_TEXT}" font-size="18" '
        f'font-weight="700" font-family="{_FONT_HEADING}">'
        f"{_escape(title)}</text>"
    )

    # Legend (only for dual series)
    legend = ""
    if has_dual:
        lx = vb_w - pad_right
        ly = 25
        legend = (
            f'<circle cx="{lx - 130}" cy="{ly}" r="5" fill="{_SERIES1}"/>'
            f'<text x="{lx - 120}" y="{ly + 4}" fill="{_TEXT}" '
            f'font-size="11" font-family="{_FONT_BODY}">Series 1</text>'
            f'<circle cx="{lx - 55}" cy="{ly}" r="5" fill="{_SERIES2}"/>'
            f'<text x="{lx - 45}" y="{ly + 4}" fill="{_TEXT}" '
            f'font-size="11" font-family="{_FONT_BODY}">Series 2</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" '
        f'role="img" aria-label="{_escape(title)}" '
        f'style="width:100%;height:auto;background:{_BG}">\n'
        f"  {title_el}\n"
        f"  {legend}\n"
        + "\n".join(f"  {g}" for g in grid_lines)
        + "\n"
        + "\n".join(f"  {y}" for y in y_labels)
        + "\n"
        f"  {baseline}\n"
        f'  <polyline points="{polyline_1}" '
        f'fill="none" stroke="{_SERIES1}" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>\n'
        + (f"  {line_2_el}\n" if line_2_el else "")
        + "\n".join(f"  {d}" for d in dots_1)
        + "\n"
        + ("\n".join(f"  {d}" for d in dots_2) + "\n" if dots_2 else "")
        + "\n".join(f"  {x}" for x in x_labels)
        + "\n</svg>"
    )
    return svg


# -- Comparison chart -------------------------------------------------------


def _render_comparison(data: list, title: str) -> str:
    """Render a before/after two-bar comparison as SVG.

    Args:
        data: list of exactly 2 items: {"label": str, "value": number}
        title: chart title

    Returns:
        SVG string.
    """
    if len(data) != 2:
        raise ValueError(
            f"Comparison chart requires exactly 2 data points, got {len(data)}."
        )

    vb_w, vb_h = 400, 300
    pad_top = 55
    pad_bottom = 50
    pad_left = 40
    pad_right = 40
    chart_w = vb_w - pad_left - pad_right
    chart_h = vb_h - pad_top - pad_bottom

    values = [d["value"] for d in data]
    max_val = max(values) if max(values) > 0 else 1
    nice_ceil = _nice_ceil(max_val)

    colors = [_SERIES1, _SERIES2]
    bar_w = chart_w * 0.3
    center_gap = chart_w * 0.1
    total_bars_w = bar_w * 2 + center_gap
    start_x = pad_left + (chart_w - total_bars_w) / 2

    # Grid lines
    grid_lines = []
    for i in range(5):
        frac = i / 4
        y = pad_top + chart_h - (frac * chart_h)
        grid_lines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" '
            f'x2="{vb_w - pad_right}" y2="{y:.1f}" '
            f'stroke="{_TEXT_MUTED}" stroke-width="0.5" stroke-dasharray="4,4"/>'
        )

    # Baseline
    baseline = (
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{vb_w - pad_right}" y2="{pad_top + chart_h}" '
        f'stroke="{_TEXT_MUTED}" stroke-width="1"/>'
    )

    # Bars
    bars = []
    for i, d in enumerate(data):
        x = start_x + i * (bar_w + center_gap)
        bar_h = (d["value"] / nice_ceil) * chart_h if nice_ceil else 0
        y = pad_top + chart_h - bar_h

        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{colors[i]}"/>'
        )
        # Value above bar
        bars.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 10:.1f}" '
            f'text-anchor="middle" fill="{_TEXT}" font-size="16" '
            f'font-weight="600" font-family="{_FONT_BODY}">'
            f"{_format_value(d['value'])}</text>"
        )
        # Label below bar
        bars.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{pad_top + chart_h + 22}" '
            f'text-anchor="middle" fill="{_TEXT}" font-size="12" '
            f'font-family="{_FONT_BODY}">{_escape(d["label"])}</text>'
        )

    # Title
    title_el = (
        f'<text x="{vb_w / 2}" y="28" text-anchor="middle" fill="{_TEXT}" '
        f'font-size="16" font-weight="700" font-family="{_FONT_HEADING}">'
        f"{_escape(title)}</text>"
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" '
        f'role="img" aria-label="{_escape(title)}" '
        f'style="width:100%;height:auto;background:{_BG}">\n'
        f"  {title_el}\n"
        + "\n".join(f"  {g}" for g in grid_lines)
        + "\n"
        f"  {baseline}\n"
        + "\n".join(f"  {b}" for b in bars)
        + "\n</svg>"
    )
    return svg


# -- Utilities --------------------------------------------------------------


def _nice_ceil(value):
    """Round a value up to a 'nice' number for axis scaling.

    Returns a round number >= value that makes for clean grid lines.
    """
    if value <= 0:
        return 1

    import math

    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude

    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 2.5:
        nice = 2.5
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10

    return nice * magnitude


# -- Public API -------------------------------------------------------------

_CHART_RENDERERS = {
    "bar": _render_bar,
    "line": _render_line,
    "comparison": _render_comparison,
}


def render_chart(
    chart_type: str,
    data: list,
    title: str,
    caption: str = "",
    source: str = "",
) -> str:
    """Generate an inline SVG chart wrapped in a <figure> element.

    Args:
        chart_type: One of "bar", "line", or "comparison".
        data:       List of data-point dicts. Shape depends on chart_type:
                        bar/line: [{"label": str, "value": num}, ...]
                        line (dual): [{"label": str, "value": num, "value2": num}, ...]
                        comparison: exactly 2 items, same shape as bar.
        title:      Chart title displayed inside the SVG.
        caption:    Caption text displayed below the chart.
        source:     Data source attribution.

    Returns:
        HTML string containing <figure> with inline SVG.

    Raises:
        ValueError: If chart_type is unknown or data is invalid.
    """
    renderer = _CHART_RENDERERS.get(chart_type)
    if renderer is None:
        raise ValueError(
            f"Unknown chart_type '{chart_type}'. "
            f"Expected one of: {', '.join(_CHART_RENDERERS.keys())}"
        )

    if not isinstance(data, list) or not data:
        raise ValueError("data must be a non-empty list of dicts.")

    svg = renderer(data, title)
    return _wrap_figure(svg, caption, source)
