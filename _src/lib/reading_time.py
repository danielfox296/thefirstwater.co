"""
Reading time calculator for Entuned blog posts.

Counts words across prose-bearing block types and converts to minutes
at 200 wpm, rounded up.
"""

import math
import re

# Block types that contain readable body text.
READABLE_TYPES = {'prose', 'aside', 'key_takeaways', 'pullquote'}


def _strip_markdown(text: str) -> str:
    """Remove Markdown/HTML syntax so we count real words only."""
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Strip Markdown links — keep the label text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Strip emphasis markers
    text = re.sub(r'[*_`~]+', '', text)
    return text


def _count_words(text: str) -> int:
    """Count whitespace-delimited words after stripping markup."""
    return len(_strip_markdown(text).split())


def calculate_reading_time(sections: list) -> int:
    """Return estimated reading time in minutes (200 wpm, rounded up).

    Scans all prose, aside, key_takeaways, and pullquote blocks.
    Returns at least 1 minute.
    """
    total_words = 0

    for block in sections:
        btype = block.get('type', '')

        if btype == 'prose':
            total_words += _count_words(block.get('body', ''))

        elif btype == 'aside':
            total_words += _count_words(block.get('body', ''))
            total_words += _count_words(block.get('title', ''))

        elif btype == 'key_takeaways':
            for item in block.get('items', []):
                total_words += _count_words(str(item))

        elif btype == 'pullquote':
            total_words += _count_words(block.get('text', ''))

    minutes = math.ceil(total_words / 200)
    return max(1, minutes)
