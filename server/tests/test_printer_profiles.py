from unittest.mock import patch

import pytest
from PIL import Image
from pydantic import ValidationError
from app.models import Printer, Template
from app.schemas import PrinterInput, TemplateInput
from app.printer import PrintError, build_print_job

@pytest.mark.parametrize('model,dpi', [('DP4300M',300),('DP4300H',300),('DP4600H',600),('DP4300HD',300)])
def test_profile_normalizes_protocol_and_dpi(model,dpi):
    p = PrinterInput(name='P',ip='unused',model=model)
    assert p.protocol == 'jscript'
    assert p.dpi == dpi


def test_unknown_profile_rejected():
    with pytest.raises(ValidationError): PrinterInput(name='P',ip='unused',model='unknown')


def template(**kw):
    return Template(name='custom',printer_id=1,bytes_per_row=160,height=100,**kw)


def test_profile_rejects_ink_outside_width_before_send():
    bitmap=Image.new('L',(1280,100),255);bitmap.putpixel((1270,30),0)
    with patch('app.printer_jscript.render_label_bitmap',return_value=bitmap):
        with pytest.raises(PrintError,match='printable width'):
            build_print_job(template(),Printer(name='P',ip='unused',model='DP4300H'), 'a','b')


def test_profile_trims_only_blank_padding_and_uses_material_dimensions():
    bitmap=Image.new('L',(1280,100),255);bitmap.putpixel((20,30),0)
    with patch('app.printer_jscript.render_label_bitmap',return_value=bitmap):
        job=build_print_job(template(media_height_mm=12.5,media_gap_mm=2.5),Printer(name='P',ip='unused',model='DP4300H'),'a','b')
    assert b'S l1;0,0,12.5,15,105.7\r\n' in job
    assert job.startswith(b'd ASC;TDSIMG\r\n04E80064')  # 1256 aligned bits


def test_legacy_dimensions_stay_unchanged():
    job=build_print_job(template(),Printer(name='P',ip='unused',protocol='jscript'),'','')
    assert b'S l1;0,0,8,11,104\r\n' in job


@pytest.mark.parametrize('settings',[{'media_gap_mm':-1},{'media_height_mm':-1},{'media_gap_mm':float('inf')}])
def test_invalid_material_dimensions(settings):
    with pytest.raises(ValidationError): TemplateInput(bytes_per_row=10,height=100,**settings)


def test_600_profile_uses_native_raster_even_with_default_model_dpi():
    job = build_print_job(Template(name='custom',printer_id=1,bytes_per_row=20,height=50),
                          Printer(name='P',ip='unused',model='DP4600H'), '', '')
    assert job.startswith(b'd ASC;TDSIMG\r\n01400064')


def test_explicit_material_height_rejects_clipped_text():
    bitmap=Image.new('L',(1280,100),255);bitmap.putpixel((20,90),0)
    with patch('app.printer_jscript.render_label_bitmap',return_value=bitmap):
        with pytest.raises(PrintError,match='material height'):
            build_print_job(template(media_height_mm=2),Printer(name='P',ip='unused',model='DP4300H'),'a','b')


def test_profile_migration_preserves_existing_printer_and_template(monkeypatch):
    from pathlib import Path
    from sqlalchemy import create_engine
    from alembic import command
    from alembic.config import Config
    import app.db as db
    engine = create_engine('sqlite://')
    monkeypatch.setattr(db, 'engine', engine)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, 'f8a2d6e901bc')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO printer (id,name,ip,port,notes,protocol,dpi) VALUES (1,'P','unused',9100,'kept','jscript',600)")
        # Persist the pre-migration model fields without inserting new columns.
        from sqlalchemy import inspect, text
        columns = {col['name'] for col in inspect(c).get_columns('template')}
        data = {k:v for k,v in template().model_dump().items() if k in columns and k != 'id'}
        c.execute(text('INSERT INTO template (' + ','.join(data) + ') VALUES (' + ','.join(':'+k for k in data) + ')'),data)
    command.upgrade(config, 'head')
    command.check(config)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT model, dpi, protocol, notes FROM printer').one() == ('custom',600,'jscript','kept')
        assert c.exec_driver_sql('SELECT media_height_mm, media_gap_mm, bytes_per_row FROM template').one() == (0,3,160)
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    engine.dispose()
