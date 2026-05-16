import ezdxf
from ezdxf.addons import odafc
import os

ODA_MAC_PATH = "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"
ODA_LINUX_PATHS = [
    "/usr/bin/ODAFileConverter",
    "/usr/local/bin/ODAFileConverter",
    "/opt/ODAFileConverter/ODAFileConverter",
]

def _ensure_oda_configured():
    """Register ODA File Converter path with ezdxf if available."""
    if odafc.is_installed():
        return True

    for path in [ODA_MAC_PATH] + ODA_LINUX_PATHS:
        if os.path.isfile(path):
            ezdxf.options.set("odafc-addon", "unix_exec_path", path)
            return True

    return False


def export_optimized_dwg(doc, out_filepath: str):
    """
    Exports the ezdxf document as a DWG file via ezdxf's ODA addon.
    Falls back to DXF if ODA is not available.
    """
    try:
        doc.dxfversion = 'AC1024'
    except Exception:
        pass

    oda_available = _ensure_oda_configured()

    dwg_path = out_filepath.rsplit('.', 1)[0] + '.dwg'

    if oda_available:
        try:
            odafc.export_dwg(doc, dwg_path, version='R2010')
            return
        except Exception as e:
            print(f"ODA DWG export failed: {e}, falling back to DXF")

    doc.saveas(out_filepath)
