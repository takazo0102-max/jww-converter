import ezdxf
from ezdxf.addons import importer

def export_optimized_dxf(doc, out_filepath: str):
    """
    Saves the modified ezdxf document as a DXF file optimized for Jw_cad.
    Jw_cad natively reads DXF very well, so passing proper layers and colors solves the issue.
    To avoid "引数が正しくありません" (invalid argument) in Jw_cad, the DXF MUST be
    in an older format like R12 (AC1009) or R2000 (AC1015).
    """
    if doc.dxfversion != 'AC1009':
        try:
            # Try to safely downgrade to AC1009
            r12_doc = ezdxf.new('AC1009')
            # Copy layer definitions
            for layer in doc.layers:
                if layer.dxf.name not in r12_doc.layers:
                    r12_doc.layers.add(layer.dxf.name)
            
            # Use importer to transfer modelspace safely
            importer.Importer(doc, r12_doc).import_modelspace()
            
            doc = r12_doc
        except Exception as e:
            print(f"Downgrade to R12 failed: {e}. Attempting to save as is with R2000 compatibility.")
            doc.dxfversion = 'AC1015' # Try R2000 at least

    # Ensure Japanese encoding for Jw_cad text compatibility
    if '$DWGCODEPAGE' not in doc.header:
        doc.header['$DWGCODEPAGE'] = 'ANSI_932'
    elif doc.header['$DWGCODEPAGE'] != 'ANSI_932':
        doc.header['$DWGCODEPAGE'] = 'ANSI_932'

    doc.saveas(out_filepath)

