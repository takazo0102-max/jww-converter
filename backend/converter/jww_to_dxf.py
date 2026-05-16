"""
Converts parsed JWW drawing data into an ezdxf DXF document.
"""

import math
import re
import ezdxf
from converter.jww_parser import (
    JwwDrawingData, JwwLine, JwwCircle, JwwText,
    JwwSolid, JwwPoint, JwwDimension, JwwBlock,
)

JWW_COLOR_TO_ACI = {
    1: 4,    # 水色 -> Cyan
    2: 7,    # 白/黒 -> White
    3: 3,    # 緑 -> Green
    4: 2,    # 黄 -> Yellow
    5: 6,    # 紫 -> Magenta
    6: 5,    # 青 -> Blue
    7: 4,    # 水色 -> Cyan
    8: 1,    # 赤 -> Red
    9: 6,    # ピンク -> Magenta
}

JWW_LINETYPE_MAP = {
    1: "Continuous",
    2: "DASHED",
    3: "DASHED2",
    4: "DASHDOT",
    5: "DASHDOT",
    6: "CENTER",
    7: "DIVIDE",
    8: "DIVIDE2",
    9: "DOT",
}

PAPER_SIZES = {
    0: (1189, 841),   # A0
    1: (841, 594),    # A1
    2: (594, 420),    # A2
    3: (420, 297),    # A3
    4: (297, 210),    # A4
}


_current_layer_map = {}
_color_override = {}
_linetype_override = {}

_INVALID_LAYER_CHARS = re.compile(r'[<>/\\\":;?*|=`]')


def _sanitize_layer_name(name: str) -> str:
    sanitized = _INVALID_LAYER_CHARS.sub('_', name)
    sanitized = sanitized.strip()
    if not sanitized:
        sanitized = "0"
    return sanitized


def jww_to_dxf(drawing: JwwDrawingData, color_map: dict = None, linetype_map: dict = None) -> ezdxf.document.Drawing:
    """Convert JWW drawing data to an ezdxf document (R2010 for AutoCAD compat)."""
    global _current_layer_map, _color_override, _linetype_override
    _current_layer_map = _build_layer_name_map(drawing)
    for key in _current_layer_map:
        _current_layer_map[key] = _sanitize_layer_name(_current_layer_map[key])
    _color_override = color_map or {}
    _linetype_override = linetype_map or {}

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    _setup_layers(doc, drawing)
    _setup_linetypes(doc)
    _register_override_linetypes(doc)

    for entity in drawing.entities:
        try:
            _add_entity(doc, msp, entity)
        except Exception:
            continue

    return doc


def _build_layer_name_map(drawing: JwwDrawingData) -> dict:
    """Build a map from (glayer, layer) index pair to layer name string."""
    name_map = {}
    for layer_info in drawing.layers:
        gi = layer_info.group_index
        li = layer_info.layer_index
        if layer_info.name:
            name_map[(gi, li)] = layer_info.name
        else:
            g_char = format(gi, 'X')
            l_char = format(li, 'X')
            name_map[(gi, li)] = f"{g_char}-{l_char}"
    return name_map


def _setup_layers(doc, drawing: JwwDrawingData):
    for layer_name in set(_current_layer_map.values()):
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)


def _setup_linetypes(doc):
    lt_defs = {
        "DASHED": [0.5, 0.5, -0.25],
        "DASHED2": [0.5, 0.25, -0.125],
        "DASHDOT": [1.0, 0.5, -0.25, 0.0, -0.25],
        "CENTER": [1.25, 0.75, -0.25, 0.125, -0.25],
        "HIDDEN": [0.5, 0.25, -0.125],
        "DIVIDE": [1.25, 0.5, -0.25, 0.0, -0.25, 0.0, -0.25],
        "DIVIDE2": [0.625, 0.25, -0.125, 0.0, -0.125, 0.0, -0.125],
        "DOT": [0.25, 0.0, -0.25],
    }
    for name, pattern in lt_defs.items():
        if name not in doc.linetypes:
            doc.linetypes.add(name, pattern=pattern)


def _register_override_linetypes(doc):
    for lt_name in _linetype_override.values():
        if lt_name and lt_name not in doc.linetypes and lt_name != "Continuous":
            doc.linetypes.add(lt_name, pattern=[0.5, 0.25, -0.125])


def _get_layer_name(entity) -> str:
    gi = entity.glayer if entity.glayer < 16 else 0
    li = entity.layer if entity.layer < 16 else 0
    return _current_layer_map.get((gi, li), f"{format(gi, 'X')}-{format(li, 'X')}")


def _get_aci_color(jww_color: int) -> int:
    if str(jww_color) in _color_override:
        val = _color_override[str(jww_color)]
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return JWW_COLOR_TO_ACI.get(jww_color, 7)


def _get_linetype(jww_style: int) -> str:
    if str(jww_style) in _linetype_override:
        return _linetype_override[str(jww_style)]
    return JWW_LINETYPE_MAP.get(jww_style, "Continuous")


def _make_attribs(entity) -> dict:
    return {
        'layer': _get_layer_name(entity),
        'color': _get_aci_color(entity.pen_color),
        'linetype': _get_linetype(entity.pen_style),
    }


def _add_entity(doc, msp, entity):
    if isinstance(entity, JwwLine):
        _add_line(msp, entity)
    elif isinstance(entity, JwwCircle):
        _add_circle(msp, entity)
    elif isinstance(entity, JwwText):
        _add_text(msp, entity)
    elif isinstance(entity, JwwSolid):
        _add_solid(msp, entity)
    elif isinstance(entity, JwwPoint):
        _add_point(msp, entity)
    elif isinstance(entity, JwwDimension):
        _add_dimension(msp, entity)


def _add_line(msp, entity: JwwLine):
    msp.add_line(
        (entity.x1, entity.y1),
        (entity.x2, entity.y2),
        dxfattribs=_make_attribs(entity),
    )


def _add_circle(msp, entity: JwwCircle):
    attribs = _make_attribs(entity)

    if entity.is_full_circle and entity.flatness == 1.0:
        msp.add_circle(
            (entity.cx, entity.cy),
            entity.radius,
            dxfattribs=attribs,
        )
    elif entity.flatness != 1.0:
        _add_ellipse(msp, entity, attribs)
    else:
        start_deg = math.degrees(entity.start_angle)
        end_deg = math.degrees(entity.start_angle + entity.arc_angle)
        msp.add_arc(
            (entity.cx, entity.cy),
            entity.radius,
            start_deg,
            end_deg,
            dxfattribs=attribs,
        )


def _add_ellipse(msp, entity: JwwCircle, attribs: dict):
    major_axis_length = entity.radius
    ratio = entity.flatness if entity.flatness != 0 else 1.0

    cos_t = math.cos(entity.tilt_angle)
    sin_t = math.sin(entity.tilt_angle)
    major_axis = (major_axis_length * cos_t, major_axis_length * sin_t, 0)

    if entity.is_full_circle:
        start_param = 0.0
        end_param = math.tau
    else:
        start_param = entity.start_angle
        end_param = entity.start_angle + entity.arc_angle

    msp.add_ellipse(
        (entity.cx, entity.cy, 0),
        major_axis,
        ratio,
        start_param,
        end_param,
        dxfattribs=attribs,
    )


def _add_text(msp, entity: JwwText):
    if not entity.text:
        return

    attribs = _make_attribs(entity)
    height = entity.size_y if entity.size_y > 0 else 3.0
    rotation = math.degrees(entity.angle) if entity.angle != 0 else 0.0

    attribs['height'] = height
    if rotation:
        attribs['rotation'] = rotation

    msp.add_text(
        entity.text,
        dxfattribs=attribs,
    ).set_placement((entity.x1, entity.y1))


def _add_solid(msp, entity: JwwSolid):
    if len(entity.points) < 3:
        return

    attribs = _make_attribs(entity)
    pts = entity.points

    if entity.rgb_color and entity.pen_color == 10:
        r = (entity.rgb_color >> 16) & 0xFF
        g = (entity.rgb_color >> 8) & 0xFF
        b = entity.rgb_color & 0xFF
        attribs['true_color'] = ezdxf.colors.rgb2int((r, g, b))

    if len(pts) >= 4:
        msp.add_solid(
            [pts[0], pts[1], pts[2], pts[3]],
            dxfattribs=attribs,
        )
    else:
        msp.add_solid(
            [pts[0], pts[1], pts[2]],
            dxfattribs=attribs,
        )


def _add_point(msp, entity: JwwPoint):
    attribs = _make_attribs(entity)
    msp.add_point((entity.x, entity.y), dxfattribs=attribs)


def _add_dimension(msp, entity: JwwDimension):
    if entity.line:
        _add_line(msp, entity.line)
    if entity.text:
        _add_text(msp, entity.text)
