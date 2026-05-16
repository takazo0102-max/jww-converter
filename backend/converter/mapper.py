import logging
import ezdxf

logger = logging.getLogger(__name__)


def map_entities(filepath: str, mapping_config: dict, direction: str = "to-jww"):
    """
    Applies user-defined layers, colors, and linetypes mappings to entities.
    Returns the modified ezdxf document ready for export.
    """
    if filepath.lower().endswith('.jww'):
        return _map_jww_entities(filepath, mapping_config)

    if filepath.lower().endswith('.dwg'):
        return _map_dwg_entities(filepath, mapping_config, direction)

    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    layer_map = mapping_config.get("layers", {})
    color_map = mapping_config.get("colors", {})
    linetype_map = mapping_config.get("linetypes", {})

    for new_layer_name in set(layer_map.values()):
        if new_layer_name not in doc.layers:
            doc.layers.add(new_layer_name)

    for entity in msp:
        orig_layer = entity.dxf.layer
        if orig_layer in layer_map:
            entity.dxf.layer = layer_map[orig_layer]

        orig_color = str(entity.dxf.color) if hasattr(entity.dxf, 'color') else "256"
        if orig_color in color_map:
            mapped_val = color_map[orig_color]

            if direction == "to-jww":
                aci_color = 7
                if mapped_val == "1": aci_color = 4
                elif mapped_val == "2": aci_color = 7
                elif mapped_val == "3": aci_color = 3
                elif mapped_val == "4": aci_color = 2
                elif mapped_val == "5": aci_color = 6
                elif mapped_val == "6": aci_color = 5
                elif mapped_val == "7": aci_color = 4
                elif mapped_val == "8": aci_color = 1
                elif mapped_val == "9": aci_color = 6
            else:
                aci_color = int(mapped_val) if mapped_val.isdigit() else 256

            try:
                entity.dxf.color = aci_color
            except Exception as e:
                logger.warning(f"Failed to set color on entity: {e}")

        orig_linetype = str(entity.dxf.linetype) if hasattr(entity.dxf, 'linetype') else "Continuous"
        if orig_linetype in linetype_map:
            mapped_lt = linetype_map[orig_linetype]
            dxf_lt = "Continuous"

            if direction == "to-jww":
                if mapped_lt == "2": dxf_lt = "DASHED"
                elif mapped_lt == "3": dxf_lt = "DASHED2"
                elif mapped_lt == "4": dxf_lt = "DASHDOT"
                elif mapped_lt == "5": dxf_lt = "DASHDOT"
                elif mapped_lt == "6": dxf_lt = "DASHDOT"
                elif mapped_lt == "7": dxf_lt = "DIVIDE"
                elif mapped_lt == "8": dxf_lt = "DIVIDE"
            else:
                dxf_lt = mapped_lt

            if dxf_lt not in doc.linetypes:
                doc.linetypes.add(dxf_lt, pattern=[0.0])

            try:
                entity.dxf.linetype = dxf_lt
            except Exception as e:
                logger.warning(f"Failed to set linetype on entity: {e}")

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
    Handle DWG files. Attempts to read via ezdxf's ODA addon,
    falls back to error if not available.
    """
    try:
        from ezdxf.addons import odafc
        from converter.dwg_exporter import _ensure_oda_configured

        if _ensure_oda_configured():
            # Convert DWG to DXF via ODA, then read
            import tempfile
            import os
            temp_dxf = filepath.rsplit('.', 1)[0] + '_temp.dxf'
            try:
                odafc.convert(filepath, temp_dxf)
                doc = ezdxf.readfile(temp_dxf)
            finally:
                if os.path.exists(temp_dxf):
                    os.remove(temp_dxf)
            return doc
    except Exception as e:
        logger.warning(f"DWG reading via ODA failed: {e}")

    raise ValueError(
        "DWGファイルの読み込みにはODA File Converterが必要です。"
        "DXFまたはJWW形式でアップロードしてください。"
    )
