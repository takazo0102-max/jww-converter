"""
Converts parsed JWW drawing data into an ezdxf DXF document.

Thread-safe: all state is passed via function parameters, no global mutation.
"""

import math
import re
import logging
import ezdxf
from converter.jww_parser import (
    JwwDrawingData, JwwLine, JwwCircle, JwwText,
    JwwSolid, JwwPoint, JwwDimension, JwwBlock,
)

logger = logging.getLogger(__name__)

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

_INVALID_LAYER_CHARS = re.compile(r'[<>/\\\":;?*|=`]')


def _sanitize_layer_name(name: str) -> str:
    sanitized = _INVALID_LAYER_CHARS.sub('_', name)
    sanitized = sanitized.strip()
    if not sanitized:
        sanitized = "0"
    return sanitized


class JwwToDxfConverter:
    """Thread-safe JWW to DXF converter. All state is instance-scoped."""

    # JWW pen width index to DXF lineweight (in 1/100 mm)
    JWW_PEN_WIDTH_TO_LINEWEIGHT = {
        0: -1,    # Default (ByLayer)
        1: 13,    # 0.13mm
        2: 18,    # 0.18mm
        3: 25,    # 0.25mm
        4: 35,    # 0.35mm
        5: 50,    # 0.50mm
        6: 70,    # 0.70mm
        7: 100,   # 1.00mm
        8: 140,   # 1.40mm
        9: 200,   # 2.00mm
    }

    # JWW layer state meanings
    LAYER_STATE_VISIBLE = 1      # 表示
    LAYER_STATE_EDITABLE = 3     # 編集可
    LAYER_STATE_HIDDEN = 0       # 非表示
    LAYER_STATE_DISPLAY_ONLY = 2 # 表示のみ

    def __init__(self, drawing: JwwDrawingData,
                 color_map: dict = None, linetype_map: dict = None):
        self.drawing = drawing
        self.color_override = color_map or {}
        self.linetype_override = linetype_map or {}
        self._group_names = self._build_group_names()
        self.layer_map = self._build_layer_name_map()
        self._layer_states = self._build_layer_states()
        # Sanitize all layer names
        for key in self.layer_map:
            self.layer_map[key] = _sanitize_layer_name(self.layer_map[key])
        self.doc = None
        self.msp = None
        self._block_entity_map = {}  # block_number -> list of entities
        self._error_count = 0

    def convert(self) -> ezdxf.document.Drawing:
        """Execute conversion and return ezdxf document."""
        self.doc = ezdxf.new('R2010')
        self.msp = self.doc.modelspace()

        self._setup_layers()
        self._setup_linetypes()
        self._register_override_linetypes()
        self._build_block_definitions()
        self._setup_paper_space()

        for entity in self.drawing.entities:
            try:
                self._add_entity(self.msp, entity)
            except Exception as e:
                self._error_count += 1
                logger.warning(f"Error converting {entity.entity_type}: {e}")
                continue

        if self._error_count > 0:
            logger.info(f"Conversion completed with {self._error_count} errors "
                        f"({len(self.drawing.entities)} entities total)")

        return self.doc

    def _build_group_names(self) -> dict:
        """Build group index -> group name map."""
        group_names = {}
        for i, name in enumerate(self.drawing.layer_group_names):
            if name:
                group_names[i] = name
        return group_names

    def _build_layer_name_map(self) -> dict:
        """
        Build a map from (glayer, layer) index pair to layer name string.
        Uses 'GroupName|LayerName' format to disambiguate same-named layers
        in different groups. Only adds group prefix for groups with entities.
        """
        name_map = {}
        # First pass: collect all layer names to detect duplicates
        layer_names_by_group = {}
        for layer_info in self.drawing.layers:
            gi = layer_info.group_index
            li = layer_info.layer_index
            if layer_info.name:
                layer_names_by_group.setdefault(layer_info.name, set()).add(gi)

        # Detect which names appear in multiple groups
        duplicate_names = {name for name, groups in layer_names_by_group.items()
                          if len(groups) > 1}

        for layer_info in self.drawing.layers:
            gi = layer_info.group_index
            li = layer_info.layer_index
            if layer_info.name:
                base_name = layer_info.name
                # Add group prefix for disambiguation when same name in multiple groups
                if base_name in duplicate_names and gi in self._group_names:
                    name_map[(gi, li)] = f"{self._group_names[gi]}_{base_name}"
                else:
                    name_map[(gi, li)] = base_name
            else:
                g_char = format(gi, 'X')
                l_char = format(li, 'X')
                name_map[(gi, li)] = f"{g_char}-{l_char}"
        return name_map

    def _build_layer_states(self) -> dict:
        """Build (glayer, layer) -> state map for visibility/lock control."""
        states = {}
        for layer_info in self.drawing.layers:
            gi = layer_info.group_index
            li = layer_info.layer_index
            states[(gi, li)] = layer_info.state
        return states

    def _setup_layers(self):
        """Set up DXF layers with visibility and lock states from JWW.
        Only creates layers that have entities assigned to them."""
        # Find which layers actually have entities
        used_layer_keys = set()
        for entity in self.drawing.entities:
            gi = entity.glayer if entity.glayer < 16 else 0
            li = entity.layer if entity.layer < 16 else 0
            used_layer_keys.add((gi, li))

        # Build reverse map for used layers only
        used_layer_names = set()
        name_to_keys = {}
        for key in used_layer_keys:
            name = self.layer_map.get(key)
            if name:
                used_layer_names.add(name)
                name_to_keys.setdefault(name, []).append(key)

        for layer_name in used_layer_names:
            if layer_name not in self.doc.layers:
                layer = self.doc.layers.add(layer_name)

                # Apply state from JWW (use first matching key's state)
                keys = name_to_keys.get(layer_name, [])
                if keys:
                    state = self._layer_states.get(keys[0], 1)
                    if state == 0:  # 非表示
                        layer.off()
                    elif state == 2:  # 表示のみ (locked)
                        layer.lock()

    def _setup_linetypes(self):
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
            if name not in self.doc.linetypes:
                self.doc.linetypes.add(name, pattern=pattern)

    def _register_override_linetypes(self):
        for lt_name in self.linetype_override.values():
            if lt_name and lt_name not in self.doc.linetypes and lt_name != "Continuous":
                self.doc.linetypes.add(lt_name, pattern=[0.5, 0.25, -0.125])

    def _setup_paper_space(self):
        """Set up basic paper space based on JWW paper size."""
        paper = PAPER_SIZES.get(self.drawing.paper_size)
        if paper:
            try:
                self.doc.header['$LIMMIN'] = (0, 0)
                self.doc.header['$LIMMAX'] = paper
            except Exception:
                pass

    def _build_block_definitions(self):
        """
        Build DXF block definitions from JWW block entities.
        JWW blocks are defined by grouping entities with the same block_number.
        We also check the drawing's block_defs if populated.
        """
        # Collect entities that belong to blocks (by block reference)
        # Note: In JWW, block definitions are stored as a separate entity list
        # Since the parser currently reads entities from the main list,
        # block references are stored as JwwBlock but definitions may not
        # be fully available. We create empty block defs for now.
        for entity in self.drawing.entities:
            if isinstance(entity, JwwBlock):
                bn = entity.block_number
                if bn not in self._block_entity_map:
                    self._block_entity_map[bn] = True

        # Create block definitions from block_defs if available
        for block_def in self.drawing.block_defs:
            block_name = f"JWW_BLOCK_{block_def.block_number}"
            if block_name not in self.doc.blocks:
                blk = self.doc.blocks.new(block_name)
                for child_entity in block_def.entities:
                    try:
                        self._add_entity(blk, child_entity)
                    except Exception as e:
                        logger.warning(f"Error in block def {block_name}: {e}")

    def _get_layer_name(self, entity) -> str:
        gi = entity.glayer if entity.glayer < 16 else 0
        li = entity.layer if entity.layer < 16 else 0
        return self.layer_map.get((gi, li), f"{format(gi, 'X')}-{format(li, 'X')}")

    def _get_aci_color(self, jww_color: int) -> int:
        if str(jww_color) in self.color_override:
            val = self.color_override[str(jww_color)]
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return JWW_COLOR_TO_ACI.get(jww_color, 7)

    def _get_linetype(self, jww_style: int) -> str:
        if str(jww_style) in self.linetype_override:
            return self.linetype_override[str(jww_style)]
        return JWW_LINETYPE_MAP.get(jww_style, "Continuous")

    def _make_attribs(self, entity) -> dict:
        attribs = {
            'layer': self._get_layer_name(entity),
            'color': self._get_aci_color(entity.pen_color),
            'linetype': self._get_linetype(entity.pen_style),
        }
        # Map pen width to DXF lineweight
        lw = self.JWW_PEN_WIDTH_TO_LINEWEIGHT.get(entity.pen_width)
        if lw is not None and lw > 0:
            attribs['lineweight'] = lw
        return attribs

    def _add_entity(self, target, entity):
        """Add entity to a target (modelspace or block)."""
        if isinstance(entity, JwwLine):
            self._add_line(target, entity)
        elif isinstance(entity, JwwCircle):
            self._add_circle(target, entity)
        elif isinstance(entity, JwwText):
            self._add_text(target, entity)
        elif isinstance(entity, JwwSolid):
            self._add_solid(target, entity)
        elif isinstance(entity, JwwPoint):
            self._add_point(target, entity)
        elif isinstance(entity, JwwDimension):
            self._add_dimension(target, entity)
        elif isinstance(entity, JwwBlock):
            self._add_block_ref(target, entity)

    def _add_line(self, target, entity: JwwLine):
        target.add_line(
            (entity.x1, entity.y1),
            (entity.x2, entity.y2),
            dxfattribs=self._make_attribs(entity),
        )

    def _add_circle(self, target, entity: JwwCircle):
        attribs = self._make_attribs(entity)

        if entity.is_full_circle and entity.flatness == 1.0:
            target.add_circle(
                (entity.cx, entity.cy),
                entity.radius,
                dxfattribs=attribs,
            )
        elif entity.flatness != 1.0:
            self._add_ellipse(target, entity, attribs)
        else:
            start_deg = math.degrees(entity.start_angle)
            end_deg = math.degrees(entity.start_angle + entity.arc_angle)
            target.add_arc(
                (entity.cx, entity.cy),
                entity.radius,
                start_deg,
                end_deg,
                dxfattribs=attribs,
            )

    def _add_ellipse(self, target, entity: JwwCircle, attribs: dict):
        major_axis_length = entity.radius
        ratio = entity.flatness if entity.flatness != 0 else 1.0

        # Clamp ratio to valid DXF range (0, 1]
        if ratio > 1.0:
            # Swap axes: minor becomes major
            major_axis_length = entity.radius * ratio
            ratio = 1.0 / ratio

        cos_t = math.cos(entity.tilt_angle)
        sin_t = math.sin(entity.tilt_angle)
        major_axis = (major_axis_length * cos_t, major_axis_length * sin_t, 0)

        if entity.is_full_circle:
            start_param = 0.0
            end_param = math.tau
        else:
            # Convert JWW angles to DXF eccentric anomaly parameters
            # JWW stores angles as absolute angles from the major axis
            # DXF ELLIPSE uses eccentric anomaly (parametric angle)
            start_param = self._angle_to_eccentric_anomaly(
                entity.start_angle, ratio)
            end_param = self._angle_to_eccentric_anomaly(
                entity.start_angle + entity.arc_angle, ratio)

        target.add_ellipse(
            (entity.cx, entity.cy, 0),
            major_axis,
            ratio,
            start_param,
            end_param,
            dxfattribs=attribs,
        )

    @staticmethod
    def _angle_to_eccentric_anomaly(angle: float, ratio: float) -> float:
        """
        Convert a true angle to eccentric anomaly for DXF ELLIPSE.
        The eccentric anomaly E relates to the true angle theta by:
            tan(E) = tan(theta) / ratio
        """
        if ratio == 0 or ratio == 1.0:
            return angle

        # Normalize to [0, 2pi)
        angle_norm = angle % math.tau

        # Use atan2 for proper quadrant handling
        x = math.cos(angle_norm)
        y = math.sin(angle_norm)
        # Eccentric anomaly: scale the y-component by 1/ratio
        e_angle = math.atan2(y / ratio, x)

        # Preserve the full rotation count
        full_rotations = angle - angle_norm
        return e_angle + full_rotations

    def _add_text(self, target, entity: JwwText):
        if not entity.text:
            return

        attribs = self._make_attribs(entity)
        height = entity.size_y if entity.size_y > 0 else 3.0
        rotation = math.degrees(entity.angle) if entity.angle != 0 else 0.0

        text_content = entity.text

        # Check for multi-line text (JWW uses \n for line breaks)
        if '\n' in text_content:
            # Use MTEXT for multi-line
            attribs['char_height'] = height
            if rotation:
                attribs['rotation'] = rotation
            # Calculate approximate width from text and character size
            max_line_len = max(len(line) for line in text_content.split('\n'))
            char_width = entity.size_x if entity.size_x > 0 else height * 0.7
            attribs['width'] = max_line_len * char_width * 1.1

            mtext = target.add_mtext(
                text_content,
                dxfattribs=attribs,
            )
            mtext.set_location((entity.x1, entity.y1))
        else:
            # Single-line TEXT
            attribs['height'] = height
            if rotation:
                attribs['rotation'] = rotation

            # Set width factor from size_x/size_y ratio
            if entity.size_x > 0 and entity.size_y > 0:
                width_factor = entity.size_x / entity.size_y
                if 0.1 < width_factor < 10.0 and abs(width_factor - 1.0) > 0.01:
                    attribs['width'] = width_factor

            # Set text style for Japanese fonts
            style_name = self._get_or_create_text_style(entity.font_name)
            if style_name:
                attribs['style'] = style_name

            target.add_text(
                text_content,
                dxfattribs=attribs,
            ).set_placement((entity.x1, entity.y1))

    def _get_or_create_text_style(self, font_name: str) -> str:
        """Get or create a DXF text style for a JWW font name."""
        if not font_name:
            return ""

        # Normalize the style name (remove spaces for DXF compatibility)
        style_name = _sanitize_layer_name(font_name.replace(' ', ''))

        if style_name not in self.doc.styles:
            try:
                self.doc.styles.new(style_name, dxfattribs={
                    'font': font_name,
                })
            except Exception:
                return ""

        return style_name

    def _add_solid(self, target, entity: JwwSolid):
        if len(entity.points) < 3:
            return

        attribs = self._make_attribs(entity)
        pts = entity.points

        if entity.rgb_color and entity.pen_color == 10:
            r = (entity.rgb_color >> 16) & 0xFF
            g = (entity.rgb_color >> 8) & 0xFF
            b = entity.rgb_color & 0xFF
            attribs['true_color'] = ezdxf.colors.rgb2int((r, g, b))

        if len(pts) >= 4:
            target.add_solid(
                [pts[0], pts[1], pts[2], pts[3]],
                dxfattribs=attribs,
            )
        else:
            target.add_solid(
                [pts[0], pts[1], pts[2]],
                dxfattribs=attribs,
            )

    def _add_point(self, target, entity: JwwPoint):
        attribs = self._make_attribs(entity)
        target.add_point((entity.x, entity.y), dxfattribs=attribs)

    def _add_dimension(self, target, entity: JwwDimension):
        """
        Add dimension entity. Renders as LINE + TEXT for maximum compatibility,
        since JWW dimensions don't map 1:1 to DXF DIMENSION entities.
        """
        if entity.line:
            self._add_line(target, entity.line)
        if entity.text:
            self._add_text(target, entity.text)
        # Also add extension/arrow lines if present
        if entity.ext_line1:
            self._add_line(target, entity.ext_line1)
        if entity.ext_line2:
            self._add_line(target, entity.ext_line2)
        if entity.arrow_line1:
            self._add_line(target, entity.arrow_line1)
        if entity.arrow_line2:
            self._add_line(target, entity.arrow_line2)

    def _add_block_ref(self, target, entity: JwwBlock):
        """Add a block reference (INSERT entity) to the target."""
        block_name = f"JWW_BLOCK_{entity.block_number}"

        # Create an empty block if not already defined
        if block_name not in self.doc.blocks:
            self.doc.blocks.new(block_name)

        attribs = self._make_attribs(entity)
        attribs['xscale'] = entity.scale_x if entity.scale_x != 0 else 1.0
        attribs['yscale'] = entity.scale_y if entity.scale_y != 0 else 1.0
        attribs['rotation'] = math.degrees(entity.rotation) if entity.rotation else 0.0

        target.add_blockref(
            block_name,
            (entity.base_x, entity.base_y),
            dxfattribs=attribs,
        )


def jww_to_dxf(drawing: JwwDrawingData,
               color_map: dict = None,
               linetype_map: dict = None) -> ezdxf.document.Drawing:
    """
    Convert JWW drawing data to an ezdxf document (R2010 for AutoCAD compat).
    Thread-safe: creates a new converter instance per call.
    """
    converter = JwwToDxfConverter(drawing, color_map, linetype_map)
    return converter.convert()
