"""A Frigate person update is presence metadata, not a theft or unpaid-exit label."""
from workers.frigate_mqtt import forward_event, person_payload


def test_person_update_is_presence_and_does_not_move_stock(client, integration_header, admin_header):
    product=client.get('/api/products').json()[0]
    with client.app.state.db.connect() as conn:
        stock=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        moves=conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        doors=conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']
    update={'type':'update','after':{'id':'person-upd-1','label':'person','camera':'aisle'}}
    calls=[]
    def post(body):
        calls.append(body)
        return client.post('/api/integrations/frigate-event',headers=integration_header,json=body)
    forwarded=forward_event(update,post)
    assert forwarded['forwarded'] is True
    body=forwarded['response'].json()
    assert body['stored'] is True and body['theft_detected'] is False
    assert calls==[update]
    car={'type':'update','after':{'id':'car-upd-1','label':'car','camera':'aisle'}}
    skipped=forward_event(car,post)
    assert skipped['forwarded'] is False and calls==[update]
    assert person_payload({'type':'new','after':{'id':'n1','label':'person','camera':'door'}})['type']=='new'
    assert person_payload({'type':'end','before':{'id':'e1','label':'person','camera':'door'}})['type']=='end'
    assert person_payload({'type':'update','after':{'id':'d1','label':'dog','camera':'door'}}) is None
    assert person_payload({'type':'snapshot','after':{'id':'s1','label':'person','camera':'door'}}) is None
    direct=client.post('/api/integrations/frigate-event',headers=integration_header,json={
        'type':'end','after':{'id':'person-end-1','label':'person','camera':'entrance'}})
    assert direct.json()['stored'] is True and direct.json()['theft_detected'] is False
    ignored=client.post('/api/integrations/frigate-event',headers=integration_header,json={
        'type':'new','after':{'id':'bike-1','label':'bicycle','camera':'entrance'}})
    assert ignored.json()['stored'] is False
    listed=client.get('/api/admin/events',headers=admin_header).json()
    assert listed['physical_door_opened'] is False
    rows={row['event_key']:row for row in listed['frigate']}
    assert rows['person-upd-1:update']['camera']=='aisle' and rows['person-upd-1:update']['label']=='person'
    assert rows['person-end-1:end']['event_type']=='end'
    assert 'bike-1:new' not in rows
    shown='有人 · '+rows['person-upd-1:update']['camera']+' · '+rows['person-upd-1:update']['event_type']
    assert shown=='有人 · aisle · update'
    for banned in ('盗窃','偷盗','未付款离店'):
        assert banned not in shown
    script=__import__('pathlib').Path('web/app.js').read_text(encoding='utf-8')
    assert "'有人 · '+e.camera+' · '+e.event_type" in script
    for banned in ('盗窃','偷盗','未付款离店'):
        assert banned not in script
    assert client.get('/api/admin/inventory-ledger',headers=admin_header).json()['balanced'] is True
    with client.app.state.db.connect() as conn:
        now=conn.execute('SELECT stock,reserved_stock FROM products WHERE id=?',(product['id'],)).fetchone()
        assert now['stock']==stock['stock'] and now['reserved_stock']==stock['reserved_stock']
        assert conn.execute('SELECT COUNT(*) n FROM stock_movements').fetchone()['n']==moves
        assert conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']==orders
        assert conn.execute('SELECT COUNT(*) n FROM door_events').fetchone()['n']==doors
    guest=__import__('conftest').visitor(client)
    assert client.post('/api/orders/'+'x'*32+'/refund',headers=guest).status_code==404
