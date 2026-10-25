"""Extract factual stock dimensions from an operator-supplied EasyMark XML.

Usage: python scripts/import_easymark_catalog.py /path/easymark.xml
Does not execute EasyMark or deserialize its binary .pemex files.
"""
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET


def convert(path):
    source = Path(path).read_bytes()
    if len(source) > 5_000_000 or b'<!DOCTYPE' in source or b'<!ENTITY' in source:
        raise ValueError('Unsupported XML input')
    root = ET.fromstring(source)
    rows = []
    for f in root.findall('format'):
        if f.findtext('units') != 'Inches':
            raise ValueError('Unexpected measurement units')
        page, label = f.find('page'), f.find('label')
        def mm(v):
            d = Decimal(v) * Decimal('25.4')
            if not d.is_finite() or d < 0: raise ValueError('Invalid dimension')
            return float(d)
        rows.append(dict(
            sku=f.attrib['key'], printer_type=f.findtext('printertype'), cut_type=f.findtext('cuttype'),
            rows=int(f.findtext('rows')), columns=int(f.findtext('columns')),
            page_width_mm=mm(page.get('width')), page_height_mm=mm(page.get('height')),
            left_margin_mm=mm(page.get('left-margin')), top_margin_mm=mm(page.get('top-margin')),
            print_width_mm=mm(label.get('width')), print_height_mm=mm(label.get('height')),
            column_pitch_mm=mm(label.get('repeat-with')), pitch_mm=mm(label.get('repeat-height')),
            gap_mm=mm(f.get('gap-value','0')),
        ))
    if len({r['sku'].upper() for r in rows}) != len(rows):raise ValueError('Duplicate SKU')
    return dict(source='EasyMark 2.0.0.229 / database/easymark.xml', sha256=hashlib.sha256(source).hexdigest(), items=rows)


if __name__ == '__main__':
    dest=Path(__file__).resolve().parents[1]/'app/data/materials.json'
    result=convert(sys.argv[1])
    dest.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(f"{len(result['items'])} formats → {dest}")
