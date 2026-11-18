"""Physical label stock from EasyMark: the die-cut label, not just its print area.

EasyMark keeps the label's real size only in each format's description
("2.000" x 4.000" ... Self-Laminating Label - 1.000" ... Print On Height").
Without it the editor drew R200X150 as 38.1 mm long (from the SKU name)
instead of Panduit's 57.2 mm, and had no shape for S-series labels at all.
"""
import importlib.util
from pathlib import Path

import pytest

from app.materials import get_material

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/import_easymark_catalog.py'


def importer():
    spec = importlib.util.spec_from_file_location('import_easymark_catalog', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fmt(key, description, *, label='width="2" height="1"', corners='corner-widt="0.062" corner-height="0.062"'):
    return f'''<format name="{key}" key="{key}" gap-value="0.125" author="PANDUIT CORP.">
    <description>{description}</description><cuttype>Die</cuttype><printertype>Thermal</printertype>
    <units>Inches</units><rows>1</rows><columns>2</columns>
    <page width="4.25" height="4.125" top-margin="0.063" left-margin="0.125" right-margin="0" bottom-margin="0" color="16777215" />
    <label {label} repeat-with="2" repeat-height="4.25" {corners} color="16777215" />
  </format>'''


def convert(tmp_path, *formats):
    source = tmp_path / 'easymark.xml'
    source.write_text('<panduit>' + ''.join(formats) + '</panduit>')
    return {row['sku']: row for row in importer().convert(source)['items']}


def test_self_laminating_label_keeps_its_physical_shape(tmp_path):
    row = convert(tmp_path, fmt('S200X400VATY',
        '2.000" x 4.000" (50.8mm x 101.6mm) Self-Laminating Label - 1.000" (25.4mm) Print On Height'))['S200X400VATY']
    assert row['label_width_mm'] == pytest.approx(50.8)
    assert row['label_length_mm'] == pytest.approx(101.6)
    assert row['print_on_height_mm'] == pytest.approx(25.4)
    assert row['label_kind'] == 'Self-Laminating'
    assert row['corner_radius_mm'] == pytest.approx(1.5748)


def test_turn_tell_length_comes_from_panduit_not_the_sku_name(tmp_path):
    row = convert(tmp_path, fmt('R200X150V1T',
        '2.000" x 2.250"  (50.8mm x 57.2mm) Turn-Tell Label  - 0.500" (12.7mm) Print On Height',
        label='width="2" height="0.5"', corners='corner-widt="0" corner-height="0"'))['R200X150V1T']
    assert row['label_length_mm'] == pytest.approx(57.15)  # not 38.1 from "150"
    assert (row['label_kind'], row['corner_radius_mm']) == ('Turn-Tell', 0)


def test_a_plain_label_has_no_print_on_height(tmp_path):
    # Component labels are opaque all over: no clear film to draw.
    row = convert(tmp_path, fmt('C125X025', '1.250" x 0.250" (31.75mm x 6.35mm) Component Label'))['C125X025']
    assert row['label_length_mm'] == pytest.approx(6.35)
    assert row['print_on_height_mm'] is None and row['label_kind'] == 'Component'


def test_an_unparsed_description_leaves_the_shape_unknown(tmp_path):
    row = convert(tmp_path, fmt('X1', 'Custom stock'))['X1']
    assert row['label_width_mm'] is row['label_length_mm'] is row['label_kind'] is None


def test_the_shipped_catalog_carries_the_shape():
    s = get_material('S200X400VATY')
    assert (s.label_width_mm, s.label_length_mm, s.print_on_height_mm) == pytest.approx((50.8, 101.6, 25.4))
    assert s.label_kind == 'Self-Laminating'
    assert get_material('R200X150V1T').label_length_mm == pytest.approx(57.15)
