from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import integrations
from app.auth_apikey import generate_key
from app.db import get_session
from app.models import ApiKey, Printer


@pytest.fixture
def fixture(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/catalog.db', connect_args={'check_same_thread':False})
    SQLModel.metadata.create_all(engine)
    key,prefix,digest = generate_key()
    with Session(engine) as session:
        session.add_all([ApiKey(name='FloorHub',prefix=prefix,key_hash=digest),
            Printer(name='Brother',ip='192.0.2.1',model='QL-1110NWBc',protocol='brother_ql'),
            Printer(name='Panduit',ip='192.0.2.2',model='DP4600H',protocol='epl2',dpi=300),
            Printer(name='Manual',ip='192.0.2.3',model='custom',protocol='jscript',dpi=203)])
        session.commit()
    app = FastAPI();app.include_router(integrations.router)
    def sessions():
        with Session(engine) as session:yield session
    app.dependency_overrides[get_session] = sessions
    with TestClient(app) as client:yield client,engine,key
    engine.dispose()


def test_catalog_uses_api_key_and_never_probes_printers(fixture):
    client,engine,key = fixture
    with patch.object(integrations,'ping_printer',side_effect=AssertionError('catalog cannot probe hardware')):
        assert client.get('/api/v1/printer-catalog').status_code == 401
        assert client.get('/api/v1/printer-catalog',headers={'X-API-Key':'invalid'}).status_code == 401
        result = client.get('/api/v1/printer-catalog',headers={'X-API-Key':key})
    assert result.status_code == 200
    rows={row['name']:row for row in result.json()}
    assert rows['Brother']['brand']=='brother' and rows['Brother']['dpi']==300
    assert rows['Panduit']['brand']=='panduit' and rows['Panduit']['dpi']==600 and rows['Panduit']['protocol']=='jscript'
    assert rows['Manual']['brand']=='custom' and rows['Manual']['dpi']==203
    assert all(type(row['id']) is int for row in rows.values())
    assert key not in result.text
    with Session(engine) as session:
        p=session.exec(select(Printer).where(Printer.name=='Panduit')).one()
        assert p.dpi==300 and p.protocol=='epl2' # metadata normalization does not rewrite configuration


def test_existing_printer_roster_contract_is_unchanged(fixture):
    client,_,key = fixture
    response=client.get('/api/v1/printers?ping=false',headers={'X-API-Key':key})
    assert response.status_code==200
    assert set(response.json()[0])=={'name','ip','port','protocol','online','ms','error'}


@pytest.mark.parametrize('model,protocol', [(None,'epl2'),('unrecognized','jscript'),(None,'brother_ql')])
def test_missing_or_unknown_model_stays_custom(model,protocol):
    p=Printer(id=7,name='Legacy',ip='192.0.2.7',model=model,protocol=protocol,dpi=203)
    dto=integrations._catalog_entry(p)
    assert dto.brand=='custom' and dto.dpi==203 and dto.protocol==protocol
