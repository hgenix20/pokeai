"""Real-art minimap: crop the full Kanto stitch (docs/pokemon-red-fire-map.png,
16 px per tile) around the player's live tile and draw a marker — the minimap
finally LOOKS like the game (operator request, 2026-07-05).

ANCHORS maps an outdoor map id -> the full-image pixel of that map's tile
(0,0). Anchoring method: zoom a known door tile in the stitch with a 16px
grid overlay and solve origin = door_px - 16*door_tile. Confidence is noted;
provisional anchors get tuned by test-rendering against live positions.
Interiors (caves/buildings) are not on the stitch: render_cells() draws the
live walkability grid instead, so the minimap never freezes.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
MAP_IMAGE = os.path.join(_ROOT, "docs", "pokemon-red-fire-map.png")
TILE = 16

# (map id) -> (origin_px_x, origin_px_y).  PRECISE = door-pixel solved;
# PROVISIONAL = eyeballed block edges, tune via test renders.
ANCHORS: dict = {
    (3, 2): (768, 960),     # Pewter City      PRECISE (P.C. door (17,25))
    (3, 1): (768, 2880),    # Viridian City    PRECISE (P.C. door (26,26))
    (3, 19): (976, 3520),   # Route 1          PROVISIONAL (below Viridian)
    (3, 20): (976, 1632),   # Route 2          PROVISIONAL (above Viridian)
    (3, 21): (1552, 1072),  # Route 3          PROVISIONAL (seam-derived from
                            #   the live Route4(15,20)~Route3(74,3) crossing;
                            #   +-3 tiles, ledge hops in the pair)
    (3, 22): (2496, 800),   # Route 4          PRECISE (3-door solve 7/6:
                            #   Center (12,5)@(2688,880), W mouth (19,5)
                            #   @(2800,880), E door (32,5)@(3008,880))
    (3, 3): (4224, 640),    # Cerulean City    PRECISE (P.C. door tile
                            #   (22,19) from live discover_center 7/6 @
                            #   art pixel (4576,944))
    (3, 0): (976, 4416),    # Pallet Town      PROVISIONAL
}
# Colors for the interior-fallback cells render ('#' wall '.' floor 'g' grass
# 'l' ledge from stream.py's _encode_cells).
_CELL_COLORS = {"#": (34, 40, 56), ".": (96, 110, 140), "g": (58, 130, 86),
                "l": (170, 130, 60)}


@lru_cache(maxsize=1)
def _stitch() -> Image.Image:
    return Image.open(MAP_IMAGE).convert("RGB")


def render_art(map_id, x, y, view_w=25, view_h=19, scale=2) -> bytes | None:
    """PNG crop of the stitch centered on tile (x,y) of `map_id`, player
    marker drawn. None when the map has no anchor (caller falls back)."""
    anchor = ANCHORS.get(tuple(map_id) if map_id else None)
    if not anchor:
        return None
    im = _stitch()
    cx = anchor[0] + x * TILE + TILE // 2
    cy = anchor[1] + y * TILE + TILE // 2
    half_w, half_h = view_w * TILE // 2, view_h * TILE // 2
    x0 = max(0, min(cx - half_w, im.width - 2 * half_w))
    y0 = max(0, min(cy - half_h, im.height - 2 * half_h))
    crop = im.crop((x0, y0, x0 + 2 * half_w, y0 + 2 * half_h)).copy()
    d = ImageDraw.Draw(crop)
    px, py = cx - x0, cy - y0
    d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(255, 255, 255), width=2)
    d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(230, 40, 40))
    if scale != 1:
        crop = crop.resize((crop.width * scale, crop.height * scale),
                           Image.NEAREST)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def render_cells(cells: str, w: int, h: int, player, npcs=(), warps=(),
                 scale=8) -> bytes:
    """Interior fallback: draw the live walkability cells string as a PNG."""
    img = Image.new("RGB", (max(w, 1), max(h, 1)), (20, 24, 36))
    pix = img.load()
    for i, ch in enumerate(cells[:w * h]):
        pix[i % w, i // w] = _CELL_COLORS.get(ch, (20, 24, 36))
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for (nx, ny) in npcs or ():
        d.rectangle([nx * scale + 1, ny * scale + 1,
                     (nx + 1) * scale - 2, (ny + 1) * scale - 2],
                    fill=(220, 80, 120))
    for (wx, wy) in warps or ():
        d.rectangle([wx * scale + 1, wy * scale + 1,
                     (wx + 1) * scale - 2, (wy + 1) * scale - 2],
                    outline=(120, 170, 255), width=2)
    if player:
        px, py = player
        d.ellipse([px * scale - 3, py * scale - 3,
                   (px + 1) * scale + 3, (py + 1) * scale + 3],
                  outline=(255, 255, 255), width=2)
        d.rectangle([px * scale, py * scale,
                     (px + 1) * scale, (py + 1) * scale], fill=(230, 40, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
