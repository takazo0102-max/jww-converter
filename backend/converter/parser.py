"""
Entry point for parsing uploaded files (DXF, DWG, JWW).
Extracts metadata (layers, colors, linetypes) for the mapping UI.
"""

import os
import logging
import ezdxf
from ezdxf import recover

logger = logging.getLogger(__name__)


def parse_dxf(filepath: str):
    """
    Parses a DXF/DWG/JWW file and extracts unique layers, colors, and linetypes.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.jww':
        return _parse_jww(filepath)

    if ext == '.dwg':
        return _parse_dwg(filepath)

    # DXF file
    return _parse_dxf_file(filepath)


def _parse_dxf_file(filepath: str) -> dict:
    """Parse a DXF file and extract metadata."""
    try:
        try:
            doc = ezdxf.readfile(filepath)
        except IOError:
            raise Exception("File not found or read error.")
        except ezdxf.DXFStructureError:
            doc, auditor = recover.readfile(filepath)
            if auditor.has_errors:
                logger.warning(f"DXF Recovered with errors: {auditor.errors}")

        return _extract_dxf_metadata(doc)

    except Exception as e:
        logger.error(f"parse_dxf error: {e}")
        raise


def _parse_dwg(filepath: str) -> dict:
    """Parse a DWG file via ODA File Converter and extract metadata."""
    try:
        doc = _read_dwg_via_oda(filepath)
        if doc:
            meta = _extract_dxf_metadata(doc)
            meta['source_format'] = 'dwg'
            return meta
    except Exception as e:
        logger.warning(f"ODA DWG read failed: {e}")

    # Fallback: extract basic info from DWG binary header
    return _parse_dwg_header(filepath)


def _read_dwg_via_oda(filepath: str):
    """Read a DWG file by converting to DXF via ODA, then reading with ezdxf."""
    from ezdxf.addons import odafc
    from converter.dwg_exporter import _ensure_oda_configured

    if not _ensure_oda_configured():
        return None

    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_dxf = os.path.join(temp_dir, 'converted.dxf')

    try:
        odafc.export_dwg(ezdxf.readfile(filepath) if filepath.endswith('.dxf') else None,
                         temp_dxf, version='R2010')
    except Exception:
        pass

    # Use ODA to convert DWG -> DXF
    try:
        import subprocess
        import shutil

        input_dir = os.path.dirname(os.path.abspath(filepath))
        input_file = os.path.basename(filepath)
        output_dir = temp_dir

        # Find ODA executable
        oda_paths = [
            "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
            "/usr/bin/ODAFileConverter",
            "/usr/local/bin/ODAFileConverter",
            "/opt/ODAFileConverter/ODAFileConverter",
        ]
        oda_exec = None
        for p in oda_paths:
            if os.path.isfile(p):
                oda_exec = p
                break

        if not oda_exec:
            # Try ezdxf's configured path
            try:
                oda_exec = ezdxf.options.get("odafc-addon", "unix_exec_path")
                if not os.path.isfile(oda_exec):
                    oda_exec = None
            except Exception:
                pass

        if not oda_exec:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        # Detect input version from header
        with open(filepath, 'rb') as f:
            header = f.read(6).decode('ascii', errors='replace')

        version_map = {
            'AC1032': 'ACAD2018', 'AC1027': 'ACAD2013', 'AC1024': 'ACAD2010',
            'AC1021': 'ACAD2007', 'AC1018': 'ACAD2004', 'AC1015': 'ACAD2000',
            'AC1014': 'ACAD14', 'AC1012': 'ACAD13', 'AC1009': 'ACAD12',
        }
        input_version = version_map.get(header, 'ACAD2018')

        # Copy DWG to temp input dir to avoid path issues
        import shutil as sh
        temp_input_dir = os.path.join(temp_dir, 'input')
        os.makedirs(temp_input_dir, exist_ok=True)
        temp_input_file = os.path.join(temp_input_dir, 'input.dwg')
        sh.copy2(filepath, temp_input_file)

        temp_output_dir = os.path.join(temp_dir, 'output')
        os.makedirs(temp_output_dir, exist_ok=True)

        # ODA args: input_dir output_dir output_version output_type recurse audit
        # output_type: 0=DXF_ASCII
        env = os.environ.copy()
        if 'DISPLAY' not in env:
            env['DISPLAY'] = ':99'

        result = subprocess.run(
            [oda_exec, temp_input_dir, temp_output_dir,
             'ACAD2010', 'DXF', '0', '1'],
            capture_output=True, text=True, timeout=30,
            env=env
        )

        # Find the output DXF
        output_dxf = os.path.join(temp_output_dir, 'input.dxf')
        if os.path.isfile(output_dxf):
            doc = ezdxf.readfile(output_dxf)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return doc
        else:
            # Check for any .dxf file in output
            for f in os.listdir(temp_output_dir):
                if f.lower().endswith('.dxf'):
                    doc = ezdxf.readfile(os.path.join(temp_output_dir, f))
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return doc

        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    except Exception as e:
        logger.error(f"ODA conversion failed: {e}")
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def _parse_dwg_header(filepath: str) -> dict:
    """
    Extract basic metadata from DWG binary header when ODA is not available.
    """
    with open(filepath, 'rb') as f:
        header = f.read(6)

    version_names = {
        b'AC1032': 'AutoCAD 2018+',
        b'AC1027': 'AutoCAD 2013',
        b'AC1024': 'AutoCAD 2010',
        b'AC1021': 'AutoCAD 2007',
        b'AC1018': 'AutoCAD 2004',
        b'AC1015': 'AutoCAD 2000',
        b'AC1014': 'AutoCAD R14',
    }
    version = version_names.get(header, f'Unknown ({header})')

    return {
        "layers": ["0"],
        "colors": [1, 2, 3, 4, 5, 6, 7, 256],
        "linetypes": ["Continuous", "DASHED", "CENTER", "HIDDEN"],
        "dwg_version": version,
        "note": "DWGファイルはサーバーでODA File Converterにより変換されます"
    }


def _extract_dxf_metadata(doc) -> dict:
    """Extract metadata from an ezdxf document."""
    layers = []
    for layer in doc.layers:
        layers.append(layer.dxf.name)

    colors = set()
    linetypes = set()
    entity_types = {}

    msp = doc.modelspace()
    for entity in msp:
        etype = entity.dxftype()
        entity_types[etype] = entity_types.get(etype, 0) + 1

        if hasattr(entity.dxf, 'color'):
            colors.add(entity.dxf.color)
        if hasattr(entity.dxf, 'linetype'):
            linetypes.add(entity.dxf.linetype)

    colors.add(256)  # BYLAYER default

    return {
        "layers": list(layers),
        "colors": sorted(colors),
        "linetypes": sorted(linetypes) if linetypes else ["Continuous"],
        "entity_counts": entity_types,
        "total_entities": sum(entity_types.values()),
    }


def _parse_jww(filepath: str):
    """Parse a JWW file and extract metadata."""
    from converter.jww_parser import parse_jww, get_jww_metadata
    drawing = parse_jww(filepath)
    metadata = get_jww_metadata(drawing)
    return metadata
