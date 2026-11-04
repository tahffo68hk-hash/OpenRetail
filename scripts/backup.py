#!/usr/bin/env python3
"""Hot SQLite backup using official online backup API; never copies only WAL base file."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import sqlite3
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
parser=argparse.ArgumentParser()
parser.add_argument('--dest-dir',default=str(ROOT/'backups'))
args=parser.parse_args()
src=Path(os.environ.get('DB_PATH',str(ROOT/'data/openretail.sqlite3')))
if not src.is_absolute():src=ROOT/src
if not src.exists():raise SystemExit(f'找不到数据库: {src}')
folder=Path(args.dest_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
dst=folder/f'openretail-{stamp}.sqlite3'
if dst.exists():raise SystemExit('备份文件已存在，拒绝覆盖')
with sqlite3.connect(src) as conn, sqlite3.connect(dst) as target:
    conn.backup(target)
    check=target.execute('PRAGMA integrity_check').fetchone()[0]
if check!='ok':
    dst.unlink(missing_ok=True);raise SystemExit('备份完整性检查失败')
try:dst.chmod(0o600)
except OSError:pass
print(f'备份完成 {dst} ({dst.stat().st_size} bytes), integrity_check=ok')
