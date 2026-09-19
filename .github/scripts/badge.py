#!/usr/bin/env python3
"""Draw badge SVGs locally, with no badge service involved.

Counts change often, so their badge URLs change too, which means GitHub's
camo proxy has to fetch each new URL on demand. When shields.io is rate
limited or down, that fetch fails and the badge renders broken - which is
exactly what happened to the Repos and Featured star badges.

Decorative badges whose URL never changes (the tools list) are fine on
shields: camo caches them effectively forever. Anything carrying a number
is drawn here and committed to the repository, so GitHub serves it directly.

Character widths are approximated per glyph and then pinned with textLength,
so the drawn text always fits the box regardless of the viewer's fonts.
"""

# Advance widths at font-size 11, DejaVu Sans Bold, in px. Good enough for
# the small charset used by labels and numbers; textLength pins the rest.
_WIDTHS = {
    " ": 4.0, ".": 4.2, ",": 4.2, "-": 5.0, "+": 7.5, "/": 5.5, "K": 8.4, "M": 10.5,
}
_DIGIT = 7.0
_UPPER = 8.2
_LOWER = 6.6


def text_width(text, size=11.0):
    total = 0.0
    for char in text:
        if char in _WIDTHS:
            total += _WIDTHS[char]
        elif char.isdigit():
            total += _DIGIT
        elif char.isupper():
            total += _UPPER
        else:
            total += _LOWER
    return total * (size / 11.0)


def _fg(background):
    """Dark text on light fills, white on dark - WCAG-ish relative luminance."""
    value = background.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    try:
        red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return "#fff"

    def channel(component):
        return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
    return "#24292f" if luminance > 0.45 else "#fff"


def _escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_STAR = (
    "M{cx},{cy0} l{r1},{r2} {r3},{r4} -{r5},{r6} {r7},{r8} -{r9},-{r10} "
)


def star_glyph(x, y, size, fill):
    """A five-pointed star, drawn rather than fetched from an icon set."""
    import math

    points = []
    for index in range(10):
        radius = size / 2 if index % 2 == 0 else size / 4.6
        angle = math.pi / 2 + index * math.pi / 5
        points.append(
            "%.2f,%.2f" % (x + radius * math.cos(angle), y - radius * math.sin(angle))
        )
    return '<polygon points="%s" fill="%s"/>' % (" ".join(points), fill)


def render(label, message, color, label_color="#555", style="for-the-badge", star=False):
    """Return an SVG string for a two-part badge."""
    upper = style == "for-the-badge"
    size = 11.0 if upper else 11.0
    height = 28 if upper else 20
    pad = 12 if upper else 9
    spacing = 1.25 if upper else 0.0

    shown_label = label.upper() if upper else label
    shown_message = str(message).upper() if upper else str(message)

    glyph_space = (height * 0.5 + 4) if star else 0
    label_text_w = text_width(shown_label, size) + spacing * max(0, len(shown_label) - 1)
    msg_text_w = text_width(shown_message, size) + spacing * max(0, len(shown_message) - 1)

    label_w = (label_text_w + pad * 2 + glyph_space) if shown_label else (glyph_space + pad)
    msg_w = msg_text_w + pad * 2
    total = label_w + msg_w

    label_cx = label_w / 2 + glyph_space / 2
    msg_cx = label_w + msg_w / 2
    baseline = height / 2 + size * 0.35

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%d" '
        'role="img" aria-label="%s: %s">'
        % (total, height, _escape(shown_label or "stars"), _escape(shown_message)),
        "<title>%s: %s</title>" % (_escape(shown_label or "stars"), _escape(shown_message)),
    ]
    if not upper:
        parts.append(
            '<linearGradient id="s" x2="0" y2="100%%">'
            '<stop offset="0" stop-color="#fff" stop-opacity=".7"/>'
            '<stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>'
            '<stop offset=".9" stop-color="#000" stop-opacity=".3"/>'
            '<stop offset="1" stop-color="#000" stop-opacity=".5"/>'
            "</linearGradient>"
        )
        parts.append(
            '<clipPath id="r"><rect width="%.0f" height="%d" rx="3" fill="#fff"/></clipPath>'
            '<g clip-path="url(#r)">' % (total, height)
        )
    else:
        parts.append("<g>")

    parts.append('<rect width="%.0f" height="%d" fill="%s"/>' % (label_w, height, label_color))
    parts.append(
        '<rect x="%.0f" width="%.0f" height="%d" fill="%s"/>' % (label_w, msg_w, height, color)
    )
    # The sheen reads as dirt when both halves are the same colour.
    if not upper and label_color.lower() != color.lower():
        parts.append('<rect width="%.0f" height="%d" fill="url(#s)"/>' % (total, height))
    parts.append("</g>")

    if star:
        parts.append(star_glyph(pad + height * 0.25, height / 2, height * 0.5, _fg(label_color)))

    font = (
        "font-family='Verdana,DejaVu Sans,Geneva,sans-serif' "
        "font-size='%.0f' font-weight='bold'" % size
    )
    if shown_label:
        parts.append(
            "<text x='%.1f' y='%.1f' textLength='%.1f' lengthAdjust='spacing' "
            "fill='%s' text-anchor='middle' %s letter-spacing='%.2f'>%s</text>"
            % (label_cx, baseline, label_text_w, _fg(label_color), font, spacing, _escape(shown_label))
        )
    parts.append(
        "<text x='%.1f' y='%.1f' textLength='%.1f' lengthAdjust='spacing' "
        "fill='%s' text-anchor='middle' %s letter-spacing='%.2f'>%s</text>"
        % (msg_cx, baseline, msg_text_w, _fg(color), font, spacing, _escape(shown_message))
    )
    parts.append("</svg>")
    return "".join(parts)
