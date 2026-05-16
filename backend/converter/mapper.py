"""
Applies user-defined layer/color/linetype mappings to entities.
Handles DXF, DWG, and JWW input files.
"""

import os
import logging
import ezdxf

logger = logging.getLogger(__name__)


def map_entities(filepath: str, mapping_config: dict, direction: str = "to-jww"):
    """
    Applies user-defined layers, colors, and linetypes mappings to entities.
    Returns the modified ezdxf document ready for export.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.jww':
        return _map_jww_entities(filepath, mapping_config)

    if ext == '.dwg':
        return _map_dwg_entities(filepath, mapping_config, direction)

    # DXF file
    doc = ezdxf.readfile(filepath)
    _apply_mapping(doc, mapping_config, direction)
    return doc


def _map_jww_entities(filepath: str, mapping_config: dict):
    """Parse JWW file and apply mapping to produce a DXF document."""
    from converter.jww_parser import parse_jww
    from converter.jww_to_dxf import jww_to_dxf

    drawing = parse_jww(filepath)

    color_map = mapping_config.get("colors", {})
    linetype_map = mapping_config.get("linetypes", {})
    layer_map = mapping_config.get("layers", {})

    doc = jww_to_dxf(drawing, color_map=color_map, linetype_map=linetype_map)

    # Apply layer renaming
    msp = doc.modelspace()
    for new_layer_name in set(layer_map.values()):
        if new_layer_name not in doc.layers:
            doc.layers.add(new_layer_name)

    for entity in msp:
        orig_layer = entity.dxf.layer
        if orig_layer in layer_map:
            entity.dxf.layer = layer_map[orig_layer]

    return doc


def _map_dwg_entities(filepath: str, mapping_config: dict, direction: str):
    """
    Read DWG file via ODA File Converter and apply mapping.
    """
    from converter.parser import _read_dwg_via_oda

    doc = _read_dwg_via_oda(filepath)
    if doc is None:
        raise ValueError(
            "DWGファイルの読み込みに失敗しました。"
            "サーバーにODA File Converterが必要です。"
        )

    _apply_mapping(doc, mapping_config, direction)
    return doc


def _apply_mapping(doc, mapping_config: dict, direction: str):
    """Apply layer/color/linetype mapping to an ezdxf document."""
    msp = doc.modelspace()

    layer_map = mapping_config.get("layers", {})
    color_map = mapping_config.get("colors", {})
    linetype_map = mapping_config.get("linetypes", {})

    # Create new layers
    for new_layer_name in set(layer_map.values()):
        if new_layer_name not in doc.layers:
            doc.layers.add(new_layer_name)

    for entity in msp:
        # Layer mapping
        orig_layer = entity.dxf.layer
        if orig_layer in layer_map:
            entity.dxf.layer = layer_map[orig_layer]

        # Color mapping
        orig_color = str(entity.dxf.color) if hasattr(entity.dxf, 'color') else "256"
        if orig_color in color_map:
            mapped_val = color_map[orig_color]

            if direction == "to-jww":
                aci_color = _jww_color_to_aci(mapped_val)
            else:
                aci_color = int(mapped_val) if str(mapped_val).isdigit() else 256

            try:
                entity.dxf.color = aci_color
            except Exception as e:
                logger.warning(f"Failed to set color on entity: {e}")

        # Linetype mapping
        orig_linetype = str(entity.dxf.linetype) if hasattr(entity.dxf, 'linetype') else "Continuous"
        if orig_linetype in linetype_map:
            mapped_lt = linetype_map[orig_linetype]

            if direction == "to-jww":
                dxf_lt = _jww_linetype_to_dxf(mapped_lt)
            else:
                dxf_lt = mapped_lt

            if dxf_lt not in doc.linetypes:
                try:
                    doc.linetypes.add(dxf_lt, pattern=[0.0])
                except Exception:
                    pass

            try:
                entity.dxf.linetype = dxf_lt
            except Exception as e:
                logger.warning(f"Failed to set linetype on entity: {e}")


def _jww_color_to_aci(jww_color_str: str) -> int:
    """Convert JWW color number string to AutoCAD ACI color."""
    mapping = {
        "1": 4,   # 水色 -> Cyan
        "2": 7,   # 白/黒 -> White
        "3": 3,   # 緑 -> Green
        "4": 2,   # 黄 -> Yellow
        "5": 6,   # 紫 -> Magenta
        "6": 5,   # 青 -> Blue
        "7": 4,   # 水色 -> Cyan
        "8": 1,   # 赤 -> Red
        "9": 6,   # ピンク -> Magenta
    }
    return mapping.get(str(jww_color_str), 7)


def _jww_linetype_to_dxf(jww_lt_str: str) -> str:
    """Convert JWW linetype number string to DXF linetype name."""
    mapping = {
        "1": "Continuous",
        "2": "DASHED",
        "3": "DASHED2",
        "4": "DASHDOT",
        "5": "DASHDOT",
        "6": "CENTER",
        "7": "DIVIDE",
        "8": "DIVIDE2",
        "9": "DOT",
    }
    return mapping.get(str(jww_lt_str), "Continuous")
