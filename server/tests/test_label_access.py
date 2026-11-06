"""The cable database is gated exactly like the cart that prints from it."""
from test_stations import admin, client, create, db, login

LABEL_READS = ['/api/labels/count', '/api/labels/search?q=1.1',
               '/api/labels/bundles?discipline_id=1',
               '/api/labels/by-bundle?discipline_id=1&bundle=1']


def test_label_reads_stay_passwordless_without_a_station(client):
    # LAN-only installs provision no station and must keep working.
    for url in LABEL_READS:
        assert client.get(url).status_code == 200, url


def test_label_reads_require_a_reader_once_a_station_exists(client):
    create(client)
    headers = login(client)
    for url in LABEL_READS:
        anonymous = client.get(url)
        assert anonymous.status_code == 401, url
        assert 'CBL#1.1' not in anonymous.text, url
        assert client.get(url, headers={'Authorization': 'Bearer forged'}).status_code == 401, url
        assert client.get(url, headers=headers).status_code == 200, url
        assert client.get(url, headers=admin()).status_code == 200, url
    # A reader still gets the whole catalogue, not an emptied one.
    hits = client.get('/api/labels/search?q=1.1', headers=headers).json()['hits']
    assert [hit['left_text'] for hit in hits] == ['CBL#1.1']
    # Preview resolves the operator itself; it stays closed the same way.
    assert client.get('/api/labels/1/preview').status_code == 401
