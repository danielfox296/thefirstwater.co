#!/usr/bin/env python3
"""Voice gate for thefirstwater.co (2026-09-19).

Encodes the greppable half of VOICE.md and of the estate catalog at
~/Desktop/site-ops/AI-TELLS-2026.md (BASE-VOICE rule 9). The other half is a
read: agent rule, claims frame, the stranger's read-aloud (Layer 7).

Two kinds of output:
  HITS   fail the gate (exit 1): em dashes in copy, "quietly", "not therapy",
         the killed and banned lines, third-person self-reference, "room"
         as the unit noun (control room and the literal-studio sense exempt),
         the door policy, the 2023-26 tell lexicon, sincerity markers and
         candor flags.
  NOTES  are printed for the read and never fail: uncontracted forms on a
         first-person surface, paragraphs closing on a fragment, therapy
         diction outside the entity block and the "sound healing" keyword.

Scans _src/pages/**/sections/*.html (HTML comments stripped), every
content.yaml, config.json meta descriptions and the llms template.

Run: python3 scripts/voice_gate.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "_src"
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# The entity block is Daniel's own words (VOICE.md, ratified 2026-07-18) and is
# exempt from every check; it carries "healing sound" on purpose.
ENTITY = ("The sessions that we hold at Firstwater in Denver gather people from all "
          "walks of life and states into a place of gratitude, stillness, and joy.")

HITS = [
    ("em dash", re.compile("—"), "never in site copy (VOICE.md kill list 7)"),
    ("quietly", re.compile(r"\bquietly\b", re.I), "the word never publishes"),
    ("not therapy", re.compile(r"\bnot (a )?therapy\b", re.I), "never appears, including structured data"),
    ("killed line", re.compile(r"feel (it|a song|the sound)[^.]{0,40}before (you|they|a single)", re.I),
     "the 'feel it before you hear/explain it' family is dead, not paraphrasable"),
    ("killed line", re.compile(r"A dark room\. One light", re.I), "killed 2026-07-21"),
    ("killed line", re.compile(r"Sound you feel before you hear", re.I), "killed 2026-07-21"),
    ("banned line", re.compile(r"doors? (close|closes|closing)[^.]{0,30}start time", re.I), "door policy never appears"),
    ("door policy", re.compile(r"\bdoor policy\b|\blateness policy\b", re.I), "the concept never appears in any form"),
    ("third person", re.compile(r"the producer behind|D\. Fox", re.I), "naming law: never a faceless persona"),
    ("room as unit noun", re.compile(r"(?<!control )(?<!Control )\brooms?\b", re.I),
     "the venue is a space, the gathering is a session"),
    ("tell lexicon", re.compile(
        r"\b(delve|tapestry|testament|realm|seamless|holistic|multifaceted|leverage|"
        r"synergy|elevate|unlock|supercharge|load-bearing|full stop|belt and suspenders|"
        r"smoking gun|the unlock|does the heavy lifting|chef's kiss|at its core|"
        r"it's worth noting|worth stating plainly|put differently|the version of|"
        r"the version where|the shape of|the work is the work)\b", re.I),
     "AI-TELLS Layer 1 and 2"),
    ("sincerity marker", re.compile(r"\b(genuinely|truly)\b|\bI mean that\b|\bI'm upfront\b", re.I),
     "prose that vouches for itself"),
    ("candor flag", re.compile(r"\b(honestly|candidly|full disclosure|the honest answer|honest gap|"
                               r"if I'm honest|if you're honest)\b", re.I),
     "state the thing without a label"),
]

NOTES = [
    ("uncontracted", re.compile(r"\b(it|that|there|here) is\b|\b(they|we|you) (are|will)\b|"
                                r"\bI (am|will|have|would)\b|\b(do|does|did|is|are|was|were|"
                                r"can|could|would|should|will|have|has|had) not\b")),
    ("therapy diction", re.compile(r"\b(healing|processing|integration|regulat\w+|trauma|"
                                   r"normalize|validate|hold space|journey)\b", re.I)),
]
SHORT_CLOSER = re.compile(r"(?:^|\.\s+)([A-Z][^.!?]{0,20}[.!?])\s*$")


def texts():
    """Yield (path, text) for every copy surface."""
    for p in sorted(SRC.glob("pages/**/sections/*.html")):
        yield p, COMMENT.sub("", p.read_text())
    for p in sorted(SRC.glob("pages/**/content.yaml")):
        yield p, p.read_text()
    for p in sorted(SRC.glob("pages/**/config.json")):
        cfg = json.loads(p.read_text())
        yield p, "\n".join(str(cfg.get(k, "")) for k in ("title", "meta_description"))
    for p in (SRC / "llms-template.txt", SRC / "partials" / "header.html", SRC / "partials" / "footer.html"):
        if p.exists():
            yield p, p.read_text()


def strip_markup(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return text.replace("&rsquo;", "'").replace("&amp;", "&")


def main() -> int:
    hits, notes = [], []
    for path, raw in texts():
        rel = path.relative_to(ROOT)
        text = strip_markup(raw)
        if path.suffix == ".yaml":
            # YAML comment lines are provenance notes, not copy.
            text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        for i, line in enumerate(text.splitlines(), 1):
            if ENTITY[:40] in line:
                continue
            for label, pat, fix in HITS:
                if pat.search(line):
                    hits.append((rel, i, label, fix, line.strip()[:100]))
            for label, pat in NOTES:
                found = pat.findall(line)
                if found and not ("sound healing" in line.lower() and label == "therapy diction"):
                    notes.append((rel, i, label, len(found), line.strip()[:100]))
        # A paragraph that closes on a fragment of three words or fewer.
        for para in re.split(r"\n\s*\n", text):
            para = " ".join(para.split())
            m = SHORT_CLOSER.search(para)
            if m and len(m.group(1).split()) <= 3 and len(para) > 120:
                notes.append((rel, 0, "short closer", 1, m.group(1)))

    if notes:
        print("Notes (a read, never a failure):")
        for rel, i, label, n, line in notes:
            where = f"{rel}:{i}" if i else f"{rel}"
            print(f"  {where}  {label} x{n}: {line}")
    if hits:
        print("\nHITS:")
        for rel, i, label, fix, line in hits:
            print(f"  {rel}:{i}  [{label}] {line}\n      -> {fix}")
        print(f"\n{len(hits)} hit(s).")
        return 1
    print("\nGate clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
