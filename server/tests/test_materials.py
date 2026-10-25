import pytest
from app.materials import get_material, search_materials, template_geometry
from app.schemas import TemplateInput


def test_exact_thermal_sku_dimensions():
    m = get_material('r200x150v1t')
    assert m.sku == 'R200X150V1T'
    assert m.page_height_mm == 53.975
    assert m.gap_mm == 3.175
    assert m.pitch_mm == 57.15
    assert m.print_height_mm == 12.7
    assert m.columns == 2
    draft = template_geometry(m)
    assert draft['bytes_per_row'] == 160
    assert draft['height'] == 638
    assert draft['media_height_mm'] == 53.975
    TemplateInput(**draft)


def test_complete_sku_distinguishes_laser_stock():
    m = get_material('R200X150X1J')
    assert not m.supported
    with pytest.raises(ValueError): template_geometry(m)


def test_all_supported_materials_have_valid_geometry():
    results = search_materials('',supported_only=True,limit=2000)
    assert results['total'] == 43
    for m in results['items']: TemplateInput(**template_geometry(m))


def test_search_is_bounded_and_exact_sku_first():
    result = search_materials('R200X150',limit=1)
    assert len(result['items']) == 1
    assert result['total'] > 1
    result = search_materials('R200X150V1T',limit=10)
    assert result['items'][0].sku == 'R200X150V1T'


def test_unknown_sku_not_inferred_from_prefix():
    with pytest.raises(KeyError):get_material('R200X150NOTREAL')


def test_catalog_print_requires_known_model_and_supported_stock():
    from app.models import Template, Printer
    from app.printer import build_print_job, PrintError
    t=Template(name='custom name',printer_id=1,**template_geometry(get_material('R200X150V1T')))
    with pytest.raises(PrintError,match='model profile'):
        build_print_job(t,Printer(name='P',ip='unused',protocol='jscript'),'LEFT','RIGHT')
    p=Printer(name='P',ip='unused',model='DP4300H')
    job=build_print_job(t,p,'LEFT','RIGHT')
    assert b'S l1;0,0,53.975,57.15,105.7' in job
    t.material_sku='R200X150X1J'
    with pytest.raises(PrintError,match='Reference only'):build_print_job(t,p,'LEFT','RIGHT')


def test_material_sku_controls_orientation_independently_of_template_name():
    from app.models import Template
    from app.label_geometry import is_turn_tell_300
    t=Template(name='Rack label',printer_id=1,**template_geometry(get_material('R200X150V1T')))
    assert is_turn_tell_300(t)
    t.material_sku='S200X400T1T'
    assert not is_turn_tell_300(t)


def test_catalog_api_auth_pagination_and_unsupported_geometry():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth_admin import require_admin
    with TestClient(app) as client:
        assert client.get('/api/materials').status_code == 401
        app.dependency_overrides[require_admin] = lambda: 'test'
        try:
            result=client.get('/api/materials',params={'q':'R200X150','limit':1})
            assert result.status_code == 200
            assert len(result.json()['items']) == 1
            assert result.json()['total'] > 1
            assert client.get('/api/materials',params={'limit':10000}).status_code == 422
            assert client.get('/api/materials/NOT_A_MATERIAL').status_code == 404
            assert client.get('/api/materials/R200X150X1J').json()['geometry'] is None
            assert client.get('/api/materials/R200X150V1T').json()['geometry']['media_gap_mm'] == 3.175
        finally:
            app.dependency_overrides.pop(require_admin,None)
