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
    # Set Qt plugin path for ODA's bundled Qt
    if 'QT_PLUGIN_PATH' not in os.environ:
        import glob
        for pattern in [
            "/usr/bin/ODAFileConverter_*/plugins",
            "/usr/lib/ODAFileConverter*/plugins",
            "/opt/ODAFileConverter*/plugins",
        ]:
            matches = glob.glob(pattern)
            if matches:
                os.environ['QT_PLUGIN_PATH'] = matches[0]
                break

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
            # Save DXF first, then convert to DWG via ODA
            dxf_temp = out_filepath
            doc.saveas(dxf_temp)
            odafc.export_dwg(doc, dwg_path, version='R2010')
            if os.path.isfile(dwg_path):
                return
            else:
                print(f"ODA export completed but DWG file not found at {dwg_path}")
        except Exception as e:
            import traceback
            print(f"ODA DWG export failed: {e}")
            traceback.print_exc()

    doc.saveas(out_filepath)
