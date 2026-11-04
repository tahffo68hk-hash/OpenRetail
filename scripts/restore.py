#!/usr/bin/env python3
"""Restore a SQLite backup into an isolated file. Never replaces the live database."""
from pathlib import Path
import argparse
import os
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')

def live_database()->Path:
    src=Path(os.environ.get('DB_PATH',str(ROOT/'data/openretail.sqlite3')))
    if not src.is_absolute():src=ROOT/src
    return src.resolve()

def assess(path:Path)->dict:
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        foreign=conn.execute('PRAGMA foreign_key_check').fetchall()
        products=conn.execute('SELECT COUNT(*) n FROM products').fetchone()['n']
        orders=conn.execute('SELECT COUNT(*) n FROM orders').fetchone()['n']
        paid=conn.execute("SELECT COUNT(*) n FROM orders WHERE status='PAID'").fetchone()['n']
        stock_bad=conn.execute('SELECT COUNT(*) n FROM products WHERE stock<0 OR reserved_stock<0 OR reserved_stock>stock').fetchone()['n']
        reserve_bad=conn.execute('''
            SELECT COUNT(*) n FROM products p
            WHERE p.reserved_stock!=COALESCE((
              SELECT SUM(ol.quantity) FROM order_lines ol
              JOIN orders o ON o.id=ol.order_id
              WHERE ol.product_id=p.id AND o.status IN ('PENDING','PAYMENT_PENDING')
            ),0)''').fetchone()['n']
        unpaid_paid=conn.execute('''
            SELECT COUNT(*) n FROM orders o WHERE o.status='PAID'
            AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id=o.id)''').fetchone()['n']
        total_bad=conn.execute('''
            SELECT COUNT(*) n FROM orders o
            WHERE o.total_cents!=COALESCE((
              SELECT SUM(unit_price_cents*quantity) FROM order_lines ol WHERE ol.order_id=o.id
            ),-1)''').fetchone()['n']
    finally:
        conn.close()
    problems=[]
    if integrity!='ok':problems.append('integrity_check='+integrity)
    if foreign:problems.append(f'foreign_key_check={len(foreign)}')
    if stock_bad:problems.append(f'stock_invariant={stock_bad}')
    if reserve_bad:problems.append(f'reservation_mismatch={reserve_bad}')
    if unpaid_paid:problems.append(f'paid_without_payment={unpaid_paid}')
    if total_bad:problems.append(f'order_total_mismatch={total_bad}')
    return {'integrity':integrity,'products':products,'orders':orders,'paid_orders':paid,
            'problems':problems,'ok':not problems}

def restore_backup(backup:Path,dest:Path)->dict:
    backup=backup.resolve();dest=dest.resolve();live=live_database()
    if not backup.is_file():raise SystemExit(f'找不到备份: {backup}')
    if dest==live:raise SystemExit(f'拒绝覆盖正在使用的数据库: {live}')
    if dest==backup:raise SystemExit('恢复目标不能与备份文件相同')
    if dest.exists():raise SystemExit(f'恢复目标已存在，拒绝覆盖: {dest}')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(backup) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    report=assess(dest)
    if not report['ok']:
        dest.unlink(missing_ok=True)
        raise SystemExit('恢复后一致性检查失败: '+', '.join(report['problems']))
    try:dest.chmod(0o600)
    except OSError:pass
    report['dest']=str(dest)
    report['live_untouched']=str(live)
    return report

def main(argv=None):
    parser=argparse.ArgumentParser(description='Restore an OpenRetail backup without touching the live database')
    parser.add_argument('--backup',required=True)
    parser.add_argument('--dest',required=True,help='Isolated output file. Must not be the live DB_PATH.')
    args=parser.parse_args(argv)
    report=restore_backup(Path(args.backup),Path(args.dest))
    print(f"恢复完成 {report['dest']}")
    print(f"integrity_check={report['integrity']} products={report['products']} orders={report['orders']} paid_orders={report['paid_orders']}")
    print('一致性：PASS')
    print('未覆盖活动库：'+report['live_untouched'])

if __name__=='__main__':
    main()
