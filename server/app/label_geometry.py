"""Map template rectangles (EasyMark-style storage) to Panduit TCP raster."""
from __future__ import annotations

from .models import Template


def is_turn_tell_300(template: Template) -> bool:
    """4.25″×2.125″ Turn-Tell row (EasyMark @ 300 DPI)."""
    if template.bytes_per_row == 160 and template.height == 638:
        return True
    # Mis-saved templates (e.g. still 156×862 from form defaults) must still
    # get column/Y fixes when the SKU name is clearly Turn-Tell.
    name = template.name.upper()
    return "X150" in name or "X200X150" in name


def text_rect(
    template: Template, *, cable_left: bool, scale: float = 1.0
) -> tuple[float, float, float, float]:
    """Print area for one sticker.

    ``cable_left`` follows Excel/UI: left column → left sticker on the cable.

    ``scale`` multiplies the returned pixel coordinates so the same template can
    be rendered at a higher-DPI head's native density (e.g. 2.0 for a 600-DPI
    DP4600H); the template stores its geometry in the 300-DPI design grid.

    Turn-Tell @ 300 DPI (Panduit raw TCP vs EasyMark export):
    - **Y:** ``raster_y = height − editor_y`` (feed direction).
    - **X:** UI-left → ``right_*`` coords (physical left sticker on the row).
    - **Text:** each column rotated 180° in ``printer.py`` (not the whole page).
    """
    if is_turn_tell_300(template):
        side = "right" if cable_left else "left"
    else:
        side = "left" if cable_left else "right"

    x0 = getattr(template, f"{side}_left") + template.gap_left
    x1 = getattr(template, f"{side}_right") - template.gap_right
    em_top = getattr(template, f"{side}_top") + template.gap_top
    em_bottom = getattr(template, f"{side}_bottom") - template.gap_bottom

    if is_turn_tell_300(template):
        h = float(template.height)
        y0 = h - em_bottom
        y1 = h - em_top
        return (x0 * scale, y0 * scale, x1 * scale, y1 * scale)

    return (x0 * scale, em_top * scale, x1 * scale, em_bottom * scale)
