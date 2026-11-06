"""Admin online backup and isolated restore preview. The live database is never replaced."""
from pathlib import Path
from scripts.restore import restore_backup
from conftest import visitor


def test_admin_can_download_backup_and_preview_it_without_replacing_live(client, admin_header, tmp_path):
    guest=visitor(client)
    product=client.get('/api/products').json()[0]
    assert client.post('/api/orders', headers=guest, json={'request_id':'backup-has-an-order',
        'lines':[{'product_id':product['id'], 'quantity':1}]}).status_code==201
    before=client.get('/api/products').json()[0]['stock']
    assert client.get('/api/admin/backup').status_code==401
    downloaded=client.get('/api/admin/backup', headers=admin_header)
    assert downloaded.status_code==200
    assert downloaded.headers['content-type'].startswith('application/vnd.sqlite3')
    assert downloaded.content.startswith(b'SQLite format 3\x00')
    assert downloaded.headers['x-openretail-live-replaced']=='false'
    saved=tmp_path/'downloaded.sqlite3'
    saved.write_bytes(downloaded.content)
    preview=client.post('/api/admin/restore-preview', headers=admin_header,
                        files={'file':('openretail.sqlite3', downloaded.content, 'application/vnd.sqlite3')})
    assert preview.status_code==200
    body=preview.json()
    assert body['ok'] is True and body['integrity']=='ok'
    assert body['products']==8 and body['orders']==1
    assert body['live_replaced'] is False and body['physical_door_opened'] is False
    assert body['real_door_enabled'] is False
    assert client.get('/api/products').json()[0]['stock']==before
    assert not Path('backups').exists() or saved.name not in [item.name for item in Path('backups').glob('*')]
    live=Path(client.app.state.config.db_path).resolve()
    try:
        restore_backup(saved, live, live=live)
    except SystemExit as exc:
        assert '拒绝覆盖正在使用的数据库' in str(exc)
    else:
        raise AssertionError('live restore was accepted')
    assert client.get('/api/products').json()[0]['stock']==before
    assert client.get('/api/admin/orders', headers=admin_header).json()[0]['id']


def test_invalid_backup_upload_leaves_the_live_database_unchanged(client, admin_header):
    before=client.get('/api/products').json()[0]['stock']
    rejected=client.post('/api/admin/restore-preview', headers=admin_header,
                         files={'file':('notes.txt', b'not a database', 'text/plain')})
    assert rejected.status_code==422
    assert client.get('/api/products').json()[0]['stock']==before
