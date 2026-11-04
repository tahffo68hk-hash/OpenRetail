#!/usr/bin/env python3
"""Read-only deployment preflight. --init-demo is the only path that creates a database."""
from pathlib import Path
import argparse
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from openretail.config import Settings
from openretail.database import Database

def database_path(cfg:Settings)->Path:
    path=Path(cfg.db_path)
    if not path.is_absolute():path=(ROOT/path).resolve()
    return path

def open_readonly(path:Path):
    if not path.is_file():
        raise FileNotFoundError(path)
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    return conn

def schema_ready(path:Path)->bool:
    with open_readonly(path) as conn:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='store_settings'").fetchone() is not None

def run_doctor(cfg:Settings,init_demo:bool=False)->str:
    cfg.validate()
    path=database_path(cfg)
    if init_demo:
        if cfg.profile!='demo':
            raise SystemExit('拒绝初始化：--init-demo 只允许 APP_MODE=demo，不会创建或覆盖预发/正式库')
        if path.exists() and not path.is_file():
            raise SystemExit(f'拒绝初始化：数据库路径不是文件: {path}')
        if path.is_file() and path.stat().st_size>0 and schema_ready(path):
            raise SystemExit(f'拒绝初始化：数据库已存在，不会覆盖 {path}')
        Database(str(path)).init(demo=True)
        action='演示初始化'
    else:
        action='只读'
        if not path.is_file():
            raise SystemExit('数据库不存在。演示环境需要显式执行: python scripts/doctor.py --init-demo')
    if not schema_ready(path):
        raise SystemExit('数据库没有业务表。检查保持只读，未创建数据。')
    with open_readonly(path) as conn:
        check=conn.execute('PRAGMA quick_check').fetchone()[0]
        modes=[row['value'] for row in conn.execute("SELECT value FROM store_settings WHERE key='mode'")]
    lines=[
        '配置检验：PASS',
        '检查模式：'+action,
        '数据库检查：'+check,
        '数据源：SQLite 单实例，不支持多进程写入或网络文件系统',
        '应用模式：'+cfg.app_mode,
        '配置档：'+cfg.profile,
        '营业模式：'+','.join(modes),
        '真实支付：'+cfg.payment_provider,
        '门禁控制：禁止（现场验收前）',
        '无人营业验收：NOT_APPROVED（代码无法代替现场验收）',
    ]
    return '\n'.join(lines)

def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only OpenRetail preflight')
    parser.add_argument('--init-demo',action='store_true',help='Create a missing demo database. Refuses staging, production, and any existing business database.')
    args=parser.parse_args(argv)
    try:
        print(run_doctor(Settings(),args.init_demo))
    except RuntimeError as exc:
        raise SystemExit('配置错误：'+str(exc)) from exc

if __name__=='__main__':
    main()
