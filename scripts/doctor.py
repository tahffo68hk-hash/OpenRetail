#!/usr/bin/env python3
"""Offline deployment preflight; outputs no credential values."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from openretail.config import Settings
from openretail.database import Database
cfg=Settings()
try:cfg.validate()
except RuntimeError as exc:raise SystemExit('配置错误：'+str(exc))
with Database(cfg.db_path).connect() as c:
    check=c.execute('PRAGMA quick_check').fetchone()[0]
    modes=[x['value'] for x in c.execute("SELECT value FROM store_settings WHERE key='mode'")]
print('配置检验：PASS')
print('数据库检查：'+check)
print('数据源：SQLite 单实例，不支持多进程写入或网络文件系统')
print('应用模式：'+cfg.app_mode)
print('营业模式：'+','.join(modes))
print('真实支付：'+cfg.payment_provider)
print('门禁控制：禁止（现场验收前）')
print('无人营业验收：NOT_APPROVED（代码无法代替现场验收）')
