"""Convert blocks to svg file.

Code originally from https://github.com/lschwetlick/maxio through
https://github.com/chemag/maxio .
"""

import logging
import string
import json
import typing as tp
from pathlib import Path

from rmscene import CrdtId, SceneTree, read_tree
from rmscene import scene_items as si
from rmscene.text import TextDocument

from rmc.exporters.writing_tools import Pen

_logger = logging.getLogger(__name__)

SCREEN_WIDTH = 1404
SCREEN_HEIGHT = 1872
SCREEN_DPI = 226

SCALE = 72.0 / SCREEN_DPI

PAGE_WIDTH_PT = SCREEN_WIDTH * SCALE
PAGE_HEIGHT_PT = SCREEN_HEIGHT * SCALE
X_SHIFT = PAGE_WIDTH_PT // 2


def scale(screen_unit: float) -> float:
    return screen_unit * SCALE


# For now, at least, the xx and yy function are identical to scale
xx = scale
yy = scale

TEXT_TOP_Y = -88
LINE_HEIGHTS = {
    # Based on a rm file having 4 anchors based on the line height I was able to find a value of
    # 69.5, but decided on 70 (to keep integer values)
    si.ParagraphStyle.PLAIN: 70,
    si.ParagraphStyle.BULLET: 35,
    si.ParagraphStyle.BULLET2: 35,
    si.ParagraphStyle.BOLD: 70,
    si.ParagraphStyle.HEADING: 150,
    si.ParagraphStyle.CHECKBOX: 35,
    si.ParagraphStyle.CHECKBOX_CHECKED: 35,

    # There appears to be another format code (value 0) which is used when the
    # text starts far down the page, which case it has a negative offset (line
    # height) of about -20?
    #
    # Probably, actually, the line height should be added *after* the first
    # line, but there is still something a bit odd going on here.
}

SVG_HEADER = string.Template("""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" height="$height" width="$width" viewBox="$viewbox">""")


def rm_to_json(rm_path, svg_path):
    """Convert `rm_path` to SVG at `svg_path`."""
    with open(rm_path, "rb") as infile, open(svg_path, "wt") as outfile:
        tree = read_tree(infile)
        tree_to_json(tree, outfile)


def read_template_svg(template_path: Path) -> str:
    lines = template_path.read_text().splitlines()
    return "\n".join(lines[2:-2])


def tree_to_json(tree: SceneTree, output, include_template: Path | None = None):
    """Convert Blocks to SVG."""

    # find the anchor pos for further use
    anchor_pos = build_anchor_pos(tree.root_text)
    _logger.debug("anchor_pos: %s", anchor_pos)

    # find the extremum along x and y
    x_min, x_max, y_min, y_max = get_bounding_box(tree.root, anchor_pos)
    width_pt = xx(x_max - x_min + 1)
    height_pt = yy(y_max - y_min + 1)
    _logger.debug("x_min, x_max, y_min, y_max: %.1f, %.1f, %.1f, %.1f ; scalded %.1f, %.1f, %.1f, %.1f",
                  x_min, x_max, y_min, y_max, xx(x_min), xx(x_max), yy(y_min), yy(y_max))


    page = {
        "width": width_pt,
        "height": height_pt,
        "x": xx(x_min),
        "y": yy(y_min),
    }


    text = []
    if tree.root_text is not None:
        text = draw_text(tree.root_text, output)

    points = draw_group(tree.root, output, anchor_pos, True)

    r = {
        "page" : page,
        "pageOrg": {
            "width": x_max,
            "height": y_max,
            "x": x_min,
            "y": y_min,
        },
        "text" : text,
        "points" : points
    }
    json_string = json.dumps(r, indent=4)
    output.write(json_string)


def build_anchor_pos(text: tp.Optional[si.Text]) -> tp.Dict[CrdtId, int]:
    """
    Find the anchor pos

    :param text: the root text of the remarkable file
    """
    # Special anchors adjusted based on pen_size_test.strokes.rm
    anchor_pos = {
        CrdtId(0, 281474976710654): 100,
        CrdtId(0, 281474976710655): 100,
    }

    if text is not None:
        # Save anchor from text
        doc = TextDocument.from_scene_item(text)
        ypos = text.pos_y + TEXT_TOP_Y
        for i, p in enumerate(doc.contents):
            anchor_pos[p.start_id] = ypos
            for subp in p.contents:
                for k in subp.i:
                    anchor_pos[k] = ypos  # TODO check these anchor are used
            ypos += LINE_HEIGHTS.get(p.style.value, 70)

    return anchor_pos


def get_anchor(item: si.Group, anchor_pos):
    anchor_x = 0.0
    anchor_y = 0.0
    if item.anchor_id is not None:
        assert item.anchor_origin_x is not None
        anchor_x = item.anchor_origin_x.value
        if item.anchor_id.value in anchor_pos:
            anchor_y = anchor_pos[item.anchor_id.value]
            _logger.debug("Group anchor: %s -> y=%.1f (scalded y=%.1f)",
                          item.anchor_id.value,
                          anchor_y,
                          yy(anchor_y))
        else:
            _logger.warning("Group anchor: %s is unknown!", item.anchor_id.value)

    return anchor_x, anchor_y


def get_bounding_box(item: si.Group,
                     anchor_pos: tp.Dict[CrdtId, int],
                     default: tp.Tuple[int, int, int, int] = (- SCREEN_WIDTH // 2, SCREEN_WIDTH // 2, 0, SCREEN_HEIGHT)) \
        -> tp.Tuple[int, int, int, int]:
    """
    Get the bounding box of the given item.
    The minimum size is the default size of the screen.

    :return: x_min, x_max, y_min, y_max: the bounding box in screen units (need to be scalded using xx and yy functions)
    """
    x_min, x_max, y_min, y_max = default

    for child_id in item.children:
        child = item.children[child_id]
        if isinstance(child, si.Group):
            anchor_x, anchor_y = get_anchor(child, anchor_pos)
            x_min_t, x_max_t, y_min_t, y_max_t = get_bounding_box(child, anchor_pos, (0, 0, 0, 0))
            x_min = min(x_min, x_min_t + anchor_x)
            x_max = max(x_max, x_max_t + anchor_x)
            y_min = min(y_min, y_min_t + anchor_y)
            y_max = max(y_max, y_max_t + anchor_y)
        elif isinstance(child, si.Line):
            x_min = min([x_min] + [p.x for p in child.points])
            x_max = max([x_max] + [p.x for p in child.points])
            y_min = min([y_min] + [p.y for p in child.points])
            y_max = max([y_max] + [p.y for p in child.points])

    return x_min, x_max, y_min, y_max


def draw_group(item: si.Group, output, anchor_pos, flatten: bool = False):
    anchor_x, anchor_y = get_anchor(item, anchor_pos)

    items = []
    groups = []

    for child_id in item.children:
        child = item.children[child_id]
        if isinstance(child, si.Group):
            if flatten:
                items.extend(draw_group(child, output, anchor_pos, flatten))
            else:
                groups.append(draw_group(child, output, anchor_pos))
        elif isinstance(child, si.Line):
            if flatten:
                items.extend(draw_stroke(child, output, anchor_x, anchor_y, flatten))
            else:
                items.append(draw_stroke(child, output, anchor_x, anchor_y, flatten))
    if flatten:
        return items
    else:
        return {
            "id": item.node_id.__repr__(),
            "type": "group",
            "items": items,
            "groups": groups,
            "anchor": {
                "x": anchor_x,
                "y": anchor_y,
            },
        }


def draw_stroke(item: si.Line, output, anchor_x = None, anchor_y = None, flatten: bool = False):
    # initiate the pen
    pen = Pen.create(item.tool.value, item.color.value, item.thickness_scale)

    points = []

    last_segment_width = segment_width = 0
    # Iterate through the point to form a polyline
    for point_id, point in enumerate(item.points):
        # align the original position
        xpos = point.x + anchor_x if flatten else point.x
        ypos = point.y + anchor_y if flatten else point.y
        
        if point_id % pen.segment_length == 0:

            segment_color = pen.get_segment_color(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_width = pen.get_segment_width(point.speed, point.direction, point.width, point.pressure,
                                                  last_segment_width)
            segment_opacity = pen.get_segment_opacity(point.speed, point.direction, point.width, point.pressure,
                                                      last_segment_width)
                                                      
            points.append({
                "x": xx(xpos),
                "y": yy(ypos),
                "xorg": point.x,
                "yorg": point.y,
                "anchorx": anchor_x,
                "anchory": anchor_y,
                "color": segment_color,
                "width": segment_width,
                "opacity": segment_opacity,
            })
            
        last_segment_width = segment_width


    # end stroke
    return points


def draw_text(text: si.Text, output):

    y_offset = TEXT_TOP_Y

    doc = TextDocument.from_scene_item(text)

    lines = []

    for p in doc.contents:
        y_offset += LINE_HEIGHTS.get(p.style.value, 70)

        xpos = text.pos_x
        ypos = text.pos_y + y_offset
        cls = p.style.value.name.lower()
        if str(p):
            # TODO: this doesn't take into account the CrdtStr.properties (font-weight/font-style)
            output.write(f'\t\t\t<text x="{xx(xpos)}" y="{yy(ypos)}" class="{cls}">{str(p).strip()}</text>\n')
            lines.append({
                "x": xx(xpos),
                "y": yy(ypos),
                "xorg": xpos,
                "yorg": ypos,
                "text": str(p).strip(),
                "class": cls,
            })

    return lines