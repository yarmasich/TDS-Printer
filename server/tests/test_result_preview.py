import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine
from unittest.mock import patch
from app.api.labels import label_preview
from app.models import Label, Discipline, DataHall, Project, Printer, Template
from app.materials import get_material, template_geometry

@pytest.fixture
def scene():
    engine=create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        p=Printer(name='P',ip='unused',model='DP4300H')
        project=Project(name='P');s.add_all([p,project]);s.commit()
        hall=DataHall(name='H',project_id=project.id);s.add(hall);s.commit()
        t=Template(name='T',printer_id=p.id,**template_geometry(get_material('R200X150V1T')))
        s.add(t);s.commit()
        d=Discipline(name='D',data_hall_id=hall.id,template_id=t.id);s.add(d);s.commit()
        label=Label(discipline_id=d.id,left_text='LEFT',right_text='RIGHT');s.add(label);s.commit()
        yield s,label,t,p

def test_preview_uses_label_text_and_bound_printer_without_sending(scene):
    s,l,t,p=scene
    with patch('app.calibration.render_preview_png', return_value=b'png') as render:
        result=label_preview(l.id,session=s)
    assert result['image']=='data:image/png;base64,cG5n'
    assert result['material']['width_mm']==50.8
    assert result['material']['height_mm']==38.1
    assert result['width']==1280
    assert result['areas'][0]['x']==pytest.approx(1280-t.right_right)
    assert result['areas'][0]['y']==pytest.approx(t.right_top)
    assert render.call_args.args==(t,'LEFT','RIGHT')
    assert render.call_args.kwargs['printer'].id==p.id

def test_preview_missing_label_and_template(scene):
    s,l,t,p=scene
    with pytest.raises(HTTPException) as e: label_preview(999999,session=s)
    assert e.value.status_code==404
    d=s.get(Discipline,l.discipline_id);d.template_id=None;s.add(d);s.commit()
    with pytest.raises(HTTPException) as e: label_preview(l.id,session=s)
    assert e.value.status_code==400

def test_preview_reports_render_error_and_custom_material(scene):
    from app.printer import PrintError
    s,l,t,p=scene
    with patch('app.calibration.render_preview_png',side_effect=PrintError('Text does not fit')):
        with pytest.raises(HTTPException) as e: label_preview(l.id,session=s)
    assert e.value.status_code==400
    t.material_sku='';s.add(t);s.commit()
    with patch('app.calibration.render_preview_png',return_value=b'png'):
        assert label_preview(l.id,session=s)['material'] is None

def test_preview_contains_actual_png_and_no_printer_connection_data(scene):
    import base64
    from io import BytesIO
    from PIL import Image
    s,l,t,p=scene
    result=label_preview(l.id,session=s)
    image=Image.open(BytesIO(base64.b64decode(result['image'].split(',',1)[1])))
    assert image.format=='PNG'
    assert image.size==(result['width'],result['height'])
    assert 'printer' not in result and 'ip' not in result and 'template' not in result
