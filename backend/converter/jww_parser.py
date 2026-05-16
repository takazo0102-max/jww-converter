"""
JWW (Jw_cad) binary file parser.

Parses the proprietary JWW format based on MFC CArchive serialization.
Reference: https://www.jwcad.net/jwdatafmt.txt (v7.02 spec)

Supports entity types: Line, Circle/Arc, Ellipse, Text, Solid, Point,
Dimension, Block, and gracefully skips unknown entities.
"""

import struct
import io
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class JwwEntity:
    entity_type: str
    group_layer: int = 0
    pen_style: int = 0
    pen_color: int = 0
    pen_width: int = 0
    layer: int = 0
    glayer: int = 0
    flg: int = 0


@dataclass
class JwwLine(JwwEntity):
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0


@dataclass
class JwwCircle(JwwEntity):
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 0.0
    start_angle: float = 0.0
    arc_angle: float = 0.0
    tilt_angle: float = 0.0
    flatness: float = 1.0
    is_full_circle: bool = True


@dataclass
class JwwText(JwwEntity):
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    font_type: int = 0
    size_x: float = 0.0
    size_y: float = 0.0
    spacing: float = 0.0
    angle: float = 0.0
    font_name: str = ""
    text: str = ""


@dataclass
class JwwSolid(JwwEntity):
    points: list = field(default_factory=list)
    rgb_color: int = 0


@dataclass
class JwwPoint(JwwEntity):
    x: float = 0.0
    y: float = 0.0
    code: int = 0
    rotation: float = 0.0
    scale: float = 1.0


@dataclass
class JwwDimension(JwwEntity):
    line: Optional[JwwLine] = None
    text: Optional[JwwText] = None
    # Extension lines for proper dimension rendering
    ext_line1: Optional[JwwLine] = None
    ext_line2: Optional[JwwLine] = None
    arrow_line1: Optional[JwwLine] = None
    arrow_line2: Optional[JwwLine] = None


@dataclass
class JwwBlock(JwwEntity):
    base_x: float = 0.0
    base_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    block_number: int = 0


@dataclass
class JwwBlockDef:
    """Block definition containing child entities."""
    block_number: int = 0
    name: str = ""
    entities: list = field(default_factory=list)


@dataclass
class JwwLayerInfo:
    group_index: int = 0
    layer_index: int = 0
    name: str = ""
    state: int = 0
    protect: int = 0


@dataclass
class JwwDrawingData:
    version: int = 0
    memo: str = ""
    paper_size: int = 3
    layers: list = field(default_factory=list)
    layer_group_names: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    block_defs: list = field(default_factory=list)
    # Stats for diagnostics
    skipped_entities: dict = field(default_factory=dict)


class MfcReader:
    """Reads MFC CArchive serialized binary data."""

    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)
        self.class_registry = {}
        self.next_class_tag = 1

    @property
    def pos(self):
        return self.stream.tell()

    @property
    def remaining(self):
        cur = self.stream.tell()
        self.stream.seek(0, 2)
        end = self.stream.tell()
        self.stream.seek(cur)
        return end - cur

    def read_bytes(self, n: int) -> bytes:
        data = self.stream.read(n)
        if len(data) < n:
            raise EOFError(f"Expected {n} bytes, got {len(data)}")
        return data

    def read_byte(self) -> int:
        return struct.unpack('<B', self.read_bytes(1))[0]

    def read_word(self) -> int:
        return struct.unpack('<H', self.read_bytes(2))[0]

    def read_dword(self) -> int:
        return struct.unpack('<I', self.read_bytes(4))[0]

    def read_int32(self) -> int:
        return struct.unpack('<i', self.read_bytes(4))[0]

    def read_double(self) -> float:
        return struct.unpack('<d', self.read_bytes(8))[0]

    def read_bool(self) -> bool:
        return self.read_dword() != 0

    def read_cstring(self) -> str:
        length = self.read_byte()
        if length == 0xFF:
            length = self.read_word()
            if length == 0xFFFF:
                length = self.read_dword()

        if length == 0:
            return ""

        raw = self.read_bytes(length)
        try:
            return raw.decode('shift_jis')
        except UnicodeDecodeError:
            try:
                return raw.decode('cp932')
            except UnicodeDecodeError:
                return raw.decode('latin-1')

    def read_unicode_string(self) -> str:
        sig = self.read_bytes(3)
        if sig == b'\xff\xfe\xff':
            char_count = self.read_dword()
            if char_count == 0:
                return ""
            raw = self.read_bytes(char_count * 2)
            return raw.decode('utf-16-le')
        else:
            self.stream.seek(-3, 1)
            return self.read_cstring()

    def read_class_tag(self) -> tuple:
        """
        Read MFC CArchive class/object tag.
        MFC assigns sequential tags to both classes and objects.
        Returns (class_name, is_new_class).
        """
        w = self.read_word()

        if w == 0:
            return None, False

        if w == 0xFFFF:
            schema = self.read_word()
            name_len = self.read_word()
            class_name = self.read_bytes(name_len).decode('ascii')
            self.class_registry[self.next_class_tag] = class_name
            self.next_class_tag += 1  # tag for class
            self.next_class_tag += 1  # tag for object instance
            return class_name, True

        if w == 0x7FFF:
            big_tag = self.read_dword()
            tag = big_tag & 0x7FFF
        elif w & 0x8000:
            tag = w & 0x7FFF
        else:
            tag = w

        self.next_class_tag += 1  # tag for object instance
        class_name = self.class_registry.get(tag, f"Unknown_{tag}")
        return class_name, False

    def skip(self, n: int):
        self.stream.seek(n, 1)

    def save_position(self) -> int:
        """Save current stream position for rollback."""
        return self.stream.tell()

    def restore_position(self, pos: int):
        """Restore stream to a saved position."""
        self.stream.seek(pos)


# Known byte sizes for entity data (after base data) for skip-recovery.
# These are approximate sizes used when we need to skip an entity that
# failed mid-parse. Base data is already consumed.
ENTITY_DATA_SIZES = {
    'CDataSen': 32,       # 4 doubles (x1,y1,x2,y2)
    'CDataEnko': 60,      # 7 doubles + 1 dword
    'CDataTen': 16,       # 2 doubles (minimum, may have extras)
    'CDataMoji': 64,      # 4 doubles + dword + 4 doubles + 2 strings (variable)
    'CDataSolid': 64,     # 8 doubles (4 points) + optional dword
    'CDataBlock': 44,     # 5 doubles + 1 dword
}


class JwwParser:
    """Parses JWW binary files."""

    MAGIC = b"JwwData."

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.reader: MfcReader = None
        self.version = 0
        self.drawing = JwwDrawingData()
        self._entity_positions = []  # Track positions for recovery

    def parse(self) -> JwwDrawingData:
        with open(self.filepath, 'rb') as f:
            raw = f.read()

        if not raw.startswith(self.MAGIC):
            raise ValueError("Not a valid JWW file (missing JwwData. header)")

        data = raw[8:]
        self.reader = MfcReader(data)
        self._parse_header()
        self._parse_layer_settings()
        self._parse_drawing_settings()
        self._parse_layer_names()
        self._parse_entity_list()

        if self.drawing.skipped_entities:
            logger.info(f"Skipped entity types: {self.drawing.skipped_entities}")

        return self.drawing

    def _parse_header(self):
        r = self.reader
        self.version = r.read_dword()
        self.drawing.version = self.version
        self.drawing.memo = r.read_cstring()
        self.drawing.paper_size = r.read_dword()
        r.read_dword()  # m_nWriteGLay

    def _parse_layer_settings(self):
        r = self.reader
        for gi in range(16):
            group_state = r.read_dword()
            write_layer = r.read_dword()
            scale = r.read_double()
            group_protect = r.read_dword()

            for li in range(16):
                layer_state = r.read_dword()
                layer_protect = r.read_dword()

                layer_info = JwwLayerInfo(
                    group_index=gi,
                    layer_index=li,
                    state=layer_state,
                    protect=layer_protect,
                )
                self.drawing.layers.append(layer_info)

    def _parse_drawing_settings(self):
        r = self.reader
        for _ in range(14):
            r.read_dword()
        for _ in range(5):
            r.read_dword()
        r.read_dword()  # dummy
        r.read_dword()  # m_nMaxDrawWid
        r.read_double()  # print origin X
        r.read_double()  # print origin Y
        r.read_double()  # printer ratio
        r.read_dword()  # printer settings
        r.read_dword()  # memory/grid mode
        r.read_double()  # grid min interval
        r.read_double()  # grid interval X
        r.read_double()  # grid interval Y
        r.read_double()  # grid origin X
        r.read_double()  # grid origin Y

    def _parse_layer_names(self):
        r = self.reader
        for i in range(256):
            name = r.read_cstring()
            if i < len(self.drawing.layers):
                self.drawing.layers[i].name = name

        self.drawing.layer_group_names = []
        for _ in range(16):
            self.drawing.layer_group_names.append(r.read_cstring())

    def _find_entity_list(self):
        """Scan forward to find the CObList start (WORD count + FFFF class tag)."""
        r = self.reader
        data = r.stream.getvalue()
        pos = r.pos
        while pos < len(data) - 14:
            if data[pos] == 0xFF and data[pos + 1] == 0xFF:
                schema = struct.unpack_from('<H', data, pos + 2)[0]
                name_len = struct.unpack_from('<H', data, pos + 4)[0]
                if 5 <= name_len <= 20 and pos + 6 + name_len <= len(data):
                    name = data[pos + 6:pos + 6 + name_len]
                    if name.startswith(b'CData') and all(32 <= b < 127 for b in name):
                        r.stream.seek(pos - 2)
                        return True
            pos += 1
        return False

    def _parse_entity_list(self):
        r = self.reader
        if not self._find_entity_list():
            return

        try:
            count = r.read_word()
            if count == 0xFFFF:
                count = r.read_dword()
        except EOFError:
            return

        for i in range(count):
            if r.remaining < 4:
                break
            try:
                entity = self._read_entity()
                if entity:
                    self.drawing.entities.append(entity)
            except (EOFError, struct.error):
                break
            except Exception as e:
                logger.warning(f"Error parsing entity {i}: {e}")
                # Try to recover by scanning for next entity tag
                if not self._try_recover_to_next_entity():
                    break

    def _try_recover_to_next_entity(self) -> bool:
        """
        Attempt to recover stream position by scanning for the next
        valid CData class tag. Returns True if recovery succeeded.
        """
        r = self.reader
        data = r.stream.getvalue()
        pos = r.pos

        # Scan forward looking for a valid class tag pattern
        scan_limit = min(pos + 2000, len(data) - 10)
        while pos < scan_limit:
            # Look for existing class tag reference (0x8000 | tag)
            w = struct.unpack_from('<H', data, pos)[0]
            if w & 0x8000:
                tag = w & 0x7FFF
                if tag in r.class_registry:
                    class_name = r.class_registry[tag]
                    if class_name.startswith('CData'):
                        r.stream.seek(pos)
                        return True
            # Look for new class definition (0xFFFF)
            if w == 0xFFFF and pos + 6 < len(data):
                name_len = struct.unpack_from('<H', data, pos + 4)[0]
                if 5 <= name_len <= 20 and pos + 6 + name_len <= len(data):
                    name = data[pos + 6:pos + 6 + name_len]
                    if name.startswith(b'CData') and all(32 <= b < 127 for b in name):
                        r.stream.seek(pos)
                        return True
            pos += 1
        return False

    def _read_entity(self):
        r = self.reader
        pos_before = r.save_position()
        class_name, _ = r.read_class_tag()
        if class_name is None:
            return None
        return self._parse_entity_by_class(class_name, pos_before)

    def _read_base_data(self) -> dict:
        r = self.reader
        base = {
            'group_layer': r.read_int32(),
            'pen_style': r.read_byte(),
            'pen_color': r.read_word(),
            'pen_width': r.read_word() if self.version >= 351 else 0,
            'layer': r.read_word(),
            'glayer': r.read_word(),
            'flg': r.read_word(),
        }
        return base

    def _parse_entity_by_class(self, class_name: str, pos_before: int):
        if class_name == 'CDataSen':
            return self._parse_line()
        elif class_name == 'CDataEnko':
            return self._parse_circle()
        elif class_name == 'CDataTen':
            return self._parse_point()
        elif class_name == 'CDataMoji':
            return self._parse_text()
        elif class_name == 'CDataSunpou':
            return self._parse_dimension()
        elif class_name == 'CDataSolid':
            return self._parse_solid()
        elif class_name == 'CDataBlock':
            return self._parse_block()
        else:
            # Unknown entity type - track it and try to skip safely
            self.drawing.skipped_entities[class_name] = \
                self.drawing.skipped_entities.get(class_name, 0) + 1
            logger.debug(f"Skipping unknown entity: {class_name}")
            self._skip_unknown_entity(class_name)
            return None

    def _skip_unknown_entity(self, class_name: str):
        """
        Attempt to skip an unknown entity by reading its base data
        and then scanning for the next valid entity tag.

        Most JWW entities start with the same base data structure,
        so we try to consume it to stay aligned.
        """
        r = self.reader
        try:
            # Most CData* entities share the same base structure
            # Try to read and discard base data
            self._read_base_data()
        except (EOFError, struct.error):
            pass
        # The remaining entity-specific data is variable length,
        # so we rely on _try_recover_to_next_entity in the caller

    def _parse_line(self) -> JwwLine:
        r = self.reader
        base = self._read_base_data()
        line = JwwLine(
            entity_type='line',
            x1=r.read_double(),
            y1=r.read_double(),
            x2=r.read_double(),
            y2=r.read_double(),
            **base,
        )
        return line

    def _parse_circle(self) -> JwwCircle:
        r = self.reader
        base = self._read_base_data()
        cx = r.read_double()
        cy = r.read_double()
        radius = r.read_double()
        start_angle = r.read_double()
        arc_angle = r.read_double()
        tilt_angle = r.read_double()
        flatness = r.read_double()
        is_full = r.read_dword() != 0

        return JwwCircle(
            entity_type='circle',
            cx=cx, cy=cy, radius=radius,
            start_angle=start_angle, arc_angle=arc_angle,
            tilt_angle=tilt_angle, flatness=flatness,
            is_full_circle=is_full,
            **base,
        )

    def _parse_point(self) -> JwwPoint:
        r = self.reader
        base = self._read_base_data()
        x = r.read_double()
        y = r.read_double()
        code = 0
        rotation = 0.0
        scale = 1.0

        if base['pen_style'] == 100:
            code = r.read_dword()
            rotation = r.read_double()
            scale = r.read_double()

        return JwwPoint(
            entity_type='point',
            x=x, y=y, code=code,
            rotation=rotation, scale=scale,
            **base,
        )

    def _parse_text(self) -> JwwText:
        r = self.reader
        base = self._read_base_data()
        x1 = r.read_double()
        y1 = r.read_double()
        x2 = r.read_double()
        y2 = r.read_double()
        font_type = r.read_dword()
        size_x = r.read_double()
        size_y = r.read_double()
        spacing = r.read_double()
        angle = r.read_double()
        font_name = r.read_cstring()
        text = r.read_cstring()

        return JwwText(
            entity_type='text',
            x1=x1, y1=y1, x2=x2, y2=y2,
            font_type=font_type,
            size_x=size_x, size_y=size_y,
            spacing=spacing, angle=angle,
            font_name=font_name, text=text,
            **base,
        )

    def _parse_solid(self) -> JwwSolid:
        r = self.reader
        base = self._read_base_data()
        points = []
        for _ in range(4):
            x = r.read_double()
            y = r.read_double()
            points.append((x, y))

        rgb_color = 0
        if base['pen_color'] == 10:
            rgb_color = r.read_dword()

        return JwwSolid(
            entity_type='solid',
            points=points,
            rgb_color=rgb_color,
            **base,
        )

    def _parse_dimension(self) -> JwwDimension:
        r = self.reader
        base = self._read_base_data()

        line_base = self._read_base_data()
        x1 = r.read_double()
        y1 = r.read_double()
        x2 = r.read_double()
        y2 = r.read_double()
        dim_line = JwwLine(entity_type='line', x1=x1, y1=y1, x2=x2, y2=y2, **line_base)

        text_base = self._read_base_data()
        tx1 = r.read_double()
        ty1 = r.read_double()
        tx2 = r.read_double()
        ty2 = r.read_double()
        font_type = r.read_dword()
        size_x = r.read_double()
        size_y = r.read_double()
        spacing = r.read_double()
        angle = r.read_double()
        font_name = r.read_cstring()
        text = r.read_cstring()
        dim_text = JwwText(
            entity_type='text',
            x1=tx1, y1=ty1, x2=tx2, y2=ty2,
            font_type=font_type, size_x=size_x, size_y=size_y,
            spacing=spacing, angle=angle,
            font_name=font_name, text=text,
            **text_base,
        )

        return JwwDimension(
            entity_type='dimension',
            line=dim_line,
            text=dim_text,
            **base,
        )

    def _parse_block(self) -> JwwBlock:
        r = self.reader
        base = self._read_base_data()
        bx = r.read_double()
        by = r.read_double()
        sx = r.read_double()
        sy = r.read_double()
        rot = r.read_double()
        bn = r.read_dword()

        return JwwBlock(
            entity_type='block',
            base_x=bx, base_y=by,
            scale_x=sx, scale_y=sy,
            rotation=rot, block_number=bn,
            **base,
        )


def parse_jww(filepath: str) -> JwwDrawingData:
    parser = JwwParser(filepath)
    return parser.parse()


def get_jww_metadata(drawing: JwwDrawingData) -> dict:
    """Extract metadata from parsed JWW data for the mapping UI."""
    layer_name_map = {}
    for layer in drawing.layers:
        gi = layer.group_index
        li = layer.layer_index
        if layer.name:
            layer_name_map[(gi, li)] = layer.name
        else:
            g_char = format(gi, 'X')
            l_char = format(li, 'X')
            layer_name_map[(gi, li)] = f"{g_char}-{l_char}"

    colors = set()
    linetypes = set()
    used_layers = []
    seen_layers = set()

    for entity in drawing.entities:
        colors.add(entity.pen_color)
        linetypes.add(entity.pen_style)

        gi = entity.glayer if entity.glayer < 16 else 0
        li = entity.layer if entity.layer < 16 else 0
        key = (gi, li)
        if key not in seen_layers:
            seen_layers.add(key)
            name = layer_name_map.get(key, f"{format(gi, 'X')}-{format(li, 'X')}")
            used_layers.append(name)

    entity_type_counts = {}
    for entity in drawing.entities:
        t = entity.entity_type
        entity_type_counts[t] = entity_type_counts.get(t, 0) + 1

    return {
        "layers": sorted(used_layers) if used_layers else ["0"],
        "colors": sorted(colors) if colors else [1, 2, 3, 7],
        "linetypes": sorted(linetypes) if linetypes else [1],
        "entity_counts": entity_type_counts,
        "skipped_entities": drawing.skipped_entities,
        "total_entities": len(drawing.entities),
    }
