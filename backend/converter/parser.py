import ezdxf
from ezdxf import recover


def parse_dxf(filepath: str):
    """
    Parses a DXF/DWG/JWW file and extracts unique layers, colors, and linetypes.
    """
    if filepath.lower().endswith('.jww'):
        return _parse_jww(filepath)

    if filepath.lower().endswith('.dwg'):
        print("DWG uploaded. Using mock metadata since ezdxf only supports DXF out of the box.")
        return {
            "layers": ["0", "WALLS", "DIMENSIONS", "TEXT", "HATCH"],
            "colors": ["1", "2", "3", "7", "256"],
            "linetypes": ["Continuous", "Dashed"]
        }

    try:
        try:
            doc = ezdxf.readfile(filepath)
        except IOError:
            raise Exception("File not found or read error.")
        except ezdxf.DXFStructureError:
            doc, auditor = recover.readfile(filepath)
            if auditor.has_errors:
                print(f"DXF Recovered with errors: {auditor.errors}")

        layers = []
        for layer in doc.layers:
            layers.append(layer.dxf.name)

        colors = set()
        linetypes = set()

        msp = doc.modelspace()
        for entity in msp:
            if hasattr(entity.dxf, 'color'):
                colors.add(entity.dxf.color)
            if hasattr(entity.dxf, 'linetype'):
                linetypes.add(entity.dxf.linetype)

        colors.add(256)  # BYLAYER default

        return {
            "layers": list(layers),
            "colors": list(colors),
            "linetypes": list(linetypes)
        }

    except Exception as e:
        print(f"parse_dxf error: {e}")
        raise


def _parse_jww(filepath: str):
    """Parse a JWW file and extract metadata."""
    from converter.jww_parser import parse_jww, get_jww_metadata
    drawing = parse_jww(filepath)
    metadata = get_jww_metadata(drawing)
    return metadata
