#!/usr/bin/env python3
"""Generate the README's flow diagram in both themes.

One source, two files: a light and a dark variant differ only by palette, and
hand-maintaining that pair is how they drift apart. Run after editing:

    python3 assets/make_diagrams.py

Then look at the result -- `rsvg-convert -w 900 assets/flow-dark.svg -o /tmp/f.png`
renders it at roughly the width GitHub displays.
"""
from pathlib import Path

SANS = ("ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, Helvetica, Arial, sans-serif")
MONO = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace")

DARK = dict(
    card="#121A2A", stroke="#26334C", head="#E6EDF6", body="#93A3B8",
    accent="#4ECDC4", accent_soft="#4ECDC4", rail="#64748B",
    chip="#1B2438", quote="#A5B4FC",
)
LIGHT = dict(
    card="#FFFFFF", stroke="#DDE3EC", head="#0F172A", body="#5A6B80",
    accent="#0D9488", accent_soft="#0D9488", rail="#94A3B8",
    chip="#F1F5F9", quote="#4338CA",
)

# Two tracks: how a question finds its answer, and how a session becomes a note.
ROWS = [
    ("RECALL", 96, [
        ("You, in any repo", "“what did we decide about X?”", True),
        ("vault_index.py", "the whole vault as one 3k-token map", False),
        ("The right note", "picked by meaning, not by keyword", False),
    ]),
    ("CAPTURE", 268, [
        ("A session ends", "real work happened", True),
        ("Stop + SessionEnd hooks", "draft, then a written summary", False),
        ("Filed and linked", "under its project hub, validated", False),
    ]),
]

BOX_W, BOX_H, GAP, X0 = 292, 92, 62, 78


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(p):
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1180 404" '
        'width="1180" height="404" role="img" '
        'aria-label="How the second brain answers a question and saves a session">',
        "  <defs>",
        f'    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">',
        f'      <path d="M0 0 L10 5 L0 10 z" fill="{p["accent"]}"/>',
        "    </marker>",
        "  </defs>",
    ]

    for label, y, boxes in ROWS:
        # rail label
        out.append(
            f'  <text x="{X0}" y="{y - 16}" font-family="{MONO}" font-size="11.5" '
            f'letter-spacing="1.8" fill="{p["rail"]}">{label}</text>'
        )
        for i, (head, body, is_quote) in enumerate(boxes):
            x = X0 + i * (BOX_W + GAP)
            out.append(
                f'  <rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="14" '
                f'fill="{p["card"]}" stroke="{p["stroke"]}" stroke-width="1.5"/>'
            )
            # accent bar marks where the track starts
            if i == 0:
                out.append(
                    f'  <rect x="{x}" y="{y + 22}" width="3.5" height="{BOX_H - 44}" '
                    f'rx="1.75" fill="{p["accent"]}"/>'
                )
            out.append(
                f'  <text x="{x + 24}" y="{y + 40}" font-family="{SANS}" font-size="19" '
                f'font-weight="650" fill="{p["head"]}">{esc(head)}</text>'
            )
            fill = p["quote"] if is_quote else p["body"]
            font = SANS if not is_quote else SANS
            style = ' font-style="italic"' if is_quote else ""
            out.append(
                f'  <text x="{x + 24}" y="{y + 66}" font-family="{font}" font-size="14.5"'
                f'{style} fill="{fill}">{esc(body)}</text>'
            )
            if i < len(boxes) - 1:
                ax = x + BOX_W + 14
                out.append(
                    f'  <path d="M{ax} {y + BOX_H / 2} L{ax + GAP - 28} {y + BOX_H / 2}" '
                    f'stroke="{p["accent"]}" stroke-width="1.8" fill="none" '
                    f'marker-end="url(#arrow)" opacity="0.85"/>'
                )

    # the vault underneath both tracks
    vy = 372
    out.append(
        f'  <path d="M{X0} {vy} L1102 {vy}" stroke="{p["stroke"]}" stroke-width="1.5" '
        f'stroke-dasharray="3 5" fill="none"/>'
    )
    out.append(
        f'  <rect x="{X0}" y="{vy - 14}" width="336" height="28" rx="14" fill="{p["chip"]}"/>'
    )
    out.append(
        f'  <text x="{X0 + 18}" y="{vy + 5}" font-family="{MONO}" font-size="12.5" '
        f'letter-spacing="0.3" fill="{p["accent"]}">'
        f'one vault · plain markdown · no database</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


here = Path(__file__).parent
for name, palette in (("flow-dark.svg", DARK), ("flow-light.svg", LIGHT)):
    (here / name).write_text(build(palette))
    print("wrote", name)
