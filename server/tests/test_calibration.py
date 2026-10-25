from io import BytesIO
from unittest.mock import patch
import pytest
from PIL import Image, ImageOps
from pydantic import ValidationError
from app.models import Printer, Template
from app.schemas import PrinterInput
from app.calibration import apply_calibration, render_preview_png
from app.printer import PrintError


def pair(x=1, y=-1, dpi=300):
    p = Printer(name='P', ip='unused', model='DP4300H', protocol='jscript', dpi=dpi,
                material_calibrations={'R200X150V1T': {'x_mm': x, 'y_mm': y}})
    t = Template(name='T', printer_id=1, material_sku='R200X150V1T', bytes_per_row=125, height=500)
    return p, t

@pytest.mark.parametrize('dpi,shift', [(300,12), (600,24)])
def test_shift_uses_native_dpi_and_actual_printer(dpi, shift):
    p,t = pair(dpi=dpi)
    im=Image.new('L',(1000,500),255); im.putpixel((100,100),0)
    result=apply_calibration(im,t,p,dpi=dpi)
    assert ImageOps.invert(result).getbbox() == (100+shift,100-shift,101+shift,101-shift)
    other=Printer(name='Other',ip='unused',model='DP4300H')
    assert apply_calibration(im,t,other,dpi=dpi).tobytes()==im.tobytes()
    assert im.getpixel((100,100))==0

@pytest.mark.parametrize('x,y', [(-5,0),(0,-5),(5,0),(0,5)])
def test_calibration_never_silently_clips_ink(x,y):
    p,t=pair(x,y)
    im=Image.new('L',(1000,500),0)
    with pytest.raises(PrintError,match='Calibration'):
        apply_calibration(im,t,p,dpi=300)

@pytest.mark.parametrize('offset', [6,-6,float('nan'),float('inf')])
def test_bad_calibration_rejected(offset):
    with pytest.raises(ValidationError):
        PrinterInput(name='P',ip='unused',material_calibrations={'R200X150V1T':{'x_mm':offset,'y_mm':0}})


def test_preview_uses_same_shift_at_design_dpi():
    p,t=pair(dpi=600)
    im=Image.new('L',(1000,500),255); im.putpixel((100,100),0)
    buf=BytesIO();im.save(buf,format='PNG')
    with patch('app.calibration.render_label_png',return_value=buf.getvalue()):
        result=Image.open(BytesIO(render_preview_png(t,'a','b',printer=p)))
    assert ImageOps.invert(result).getbbox()==(112,88,113,89)


def test_sku_normalization_and_partial_patch_preserves_map():
    from app.schemas import PrinterPatch
    settings=PrinterInput(name='P',ip='unused',material_calibrations={' r200x150v1t ':{'x_mm':1,'y_mm':0}})
    assert list(settings.material_calibrations)==['R200X150V1T']
    assert PrinterPatch(name='New').model_dump(exclude_unset=True)=={'name':'New'}


def test_preview_normalizes_stale_named_printer_profile():
    p,t=pair()
    p.protocol='epl2'; p.dpi=203
    t.material_sku='r200x150v1t'
    im=Image.new('L',(1000,500),255); im.putpixel((100,100),0)
    buf=BytesIO(); im.save(buf,format='PNG')
    with patch('app.calibration.render_label_png',return_value=buf.getvalue()):
        result=Image.open(BytesIO(render_preview_png(t,'a','b',printer=p)))
    assert ImageOps.invert(result).getbbox()==(112,88,113,89)


def test_actual_job_rejects_ink_shifted_past_printhead():
    from app.printer import build_print_job
    from app.materials import template_geometry, get_material
    p,t=pair(x=2,y=0)
    t=Template(name='T',printer_id=1,**template_geometry(get_material('R200X150V1T')))
    im=Image.new('L',(1280,638),255)
    # Turn-Tell rotates first: this becomes x=1230, then shifts +24 dots.
    im.putpixel((49,300),0)
    with patch('app.printer_jscript.render_label_bitmap',return_value=im):
        with pytest.raises(PrintError,match='printable width'):
            build_print_job(t,p,'a','b')


def test_calibration_api_updates_only_selected_pair_and_requires_admin():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth_admin import require_admin
    from sqlmodel import SQLModel, Session, create_engine
    from sqlalchemy.pool import StaticPool
    from app.db import get_session
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    def session_override():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session]=session_override
    with TestClient(app) as client:
        assert client.put('/api/printers/1/calibration/R200X150V1T',json={'x_mm':1}).status_code==401
        app.dependency_overrides[require_admin]=lambda:'test'
        try:
            p=client.post('/api/printers',json={'name':'Calibration test','ip':'unused','model':'DP4600H'}).json()
            url=f"/api/printers/{p['id']}/calibration/"
            assert client.put(url+'NOTREAL',json={'x_mm':1}).status_code==404
            assert client.put(url+'R200X150X1J',json={'x_mm':1}).status_code==400
            assert client.put(url+'R200X150V1T',json={'x_mm':6}).status_code==422
            result=client.put(url+'r200x150v1t',json={'x_mm':1.25,'y_mm':-.5})
            assert result.status_code==200,result.text
            assert result.json()['material_calibrations']=={'R200X150V1T':{'x_mm':1.25,'y_mm':-.5}}
            preserved=client.put(f"/api/printers/{p['id']}",json={'notes':'keep calibration','material_calibrations':{}}).json()
            assert preserved['material_calibrations']==result.json()['material_calibrations']
            cleared=client.put(f"/api/printers/{p['id']}",json={'model':'DP4300H'}).json()
            assert cleared['material_calibrations']=={}
        finally:
            app.dependency_overrides.pop(require_admin,None)
            app.dependency_overrides.pop(get_session,None)
            engine.dispose()
