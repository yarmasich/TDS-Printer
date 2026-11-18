"""Extract factual stock dimensions from an operator-supplied EasyMark XML.

Usage: python scripts/import_easymark_catalog.py /path/easymark.xml
Does not execute EasyMark or deserialize its binary .pemex files.
"""
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET

# The die-cut label's own size and print-on height live only in prose, e.g.
# '2.000" x 4.000" (50.8mm x 101.6mm) Self-Laminating Label - 1.000" (25.4mm) Print On Height'.
# Unmatched prose leaves the shape unknown rather than guessed from the SKU.
_SIZE = re.compile(r'([\d.]+)"\s*x\s*([\d.]+)"')
_PRINT_ON = re.compile(r'([\d.]+)"\s*\([\d.]+\s*mm\)\s*Print[- ]On Height', re.I)
_KIND = re.compile(r'\)\s*(.+?)\s+Label\b')
# Panduit names R/S stock by its size in hundredths of an inch: S200X400 is
# 2.00" x 4.00". 220 of 230 R/S formats agree with their prose; the rest are
# copy errors, e.g. R150X150V1T / R200X150V1T claim 2.250" on a 2.125" row.
_SKU_SIZE = re.compile(r'^[RS](\d{3})X(\d{3})', re.I)
_FIT = Decimal('0.01')  # inches; EasyMark rounds to 0.001"


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
        description = f.findtext('description') or ''
        size, print_on, kind = _SIZE.search(description), _PRINT_ON.search(description), _KIND.search(description)
        code = _SKU_SIZE.match(f.attrib['key'])
        dims = ((Decimal(code[1]) / 100, Decimal(code[2]) / 100) if code
                else (Decimal(size[1]), Decimal(size[2])) if size else None)
        # No label is longer than its own page row: such a size is misdescribed,
        # so leave the shape unknown rather than draw it wrong. (Print areas
        # are not compared here — EasyMark stores some rotated; the editor
        # checks the print area sits inside the label before drawing.)
        if dims and dims[1] > Decimal(page.get('height')) + _FIT:
            dims = None
        # EasyMark spells the attribute "corner-widt".
        corner = label.get('corner-width', label.get('corner-widt', '0'))
        rows.append(dict(
            sku=f.attrib['key'], printer_type=f.findtext('printertype'), cut_type=f.findtext('cuttype'),
            rows=int(f.findtext('rows')), columns=int(f.findtext('columns')),
            page_width_mm=mm(page.get('width')), page_height_mm=mm(page.get('height')),
            left_margin_mm=mm(page.get('left-margin')), top_margin_mm=mm(page.get('top-margin')),
            print_width_mm=mm(label.get('width')), print_height_mm=mm(label.get('height')),
            column_pitch_mm=mm(label.get('repeat-with')), pitch_mm=mm(label.get('repeat-height')),
            gap_mm=mm(f.get('gap-value','0')),
            label_width_mm=mm(dims[0]) if dims else None,
            label_length_mm=mm(dims[1]) if dims else None,
            print_on_height_mm=mm(print_on.group(1)) if print_on else None,
            label_kind=kind.group(1).strip() if kind else None,
            corner_radius_mm=mm(corner),
        ))
    if len({r['sku'].upper() for r in rows}) != len(rows):raise ValueError('Duplicate SKU')
    return dict(source='EasyMark 2.0.0.229 / database/easymark.xml', sha256=hashlib.sha256(source).hexdigest(), items=rows)


if __name__ == '__main__':
    dest=Path(__file__).resolve().parents[1]/'app/data/materials.json'
    result=convert(sys.argv[1])
    dest.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(f"{len(result['items'])} formats → {dest}")
