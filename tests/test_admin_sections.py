"""The existing admin page is grouped. Controls and status copy stay in place."""

SECTIONS=(
    ('今日需要处理','admin-today'),
    ('商品','admin-products'),
    ('订单','admin-orders'),
    ('未付款占用','admin-holding'),
    ('求助','admin-help'),
    ('备份','admin-backup'),
    ('操作记录','admin-audit'),
    ('门禁事件','admin-door'),
    ('设置','admin-settings'),
)


def test_admin_page_keeps_labeled_sections(client):
    page=client.get('/').text
    assert 'id="admin-nav"' in page
    assert 'data-panel=' not in page.split('id="admin-nav"',1)[1].split('</nav>',1)[0]
    for label, section_id in SECTIONS:
        assert f'href="#{section_id}"' in page
        assert f'id="{section_id}"' in page
        assert label in page
    for marker in ('id="today-summary"','id="admin-catalog"','id="order-table"','id="holding-list"',
                   'id="help-list"','id="backup-download"','id="audit-list"','id="door-event-list"',
                   'id="store-settings-form"','id="ledger-balance"','非真实资金','实体门未打开'):
        assert marker in page
