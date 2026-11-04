#!/usr/bin/env python3
"""Set password verifier in git-ignored .env. No raw password is saved."""
from pathlib import Path
import getpass
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from openretail.security import password_hash
path=ROOT/'.env'
if not path.exists():raise SystemExit('先运行 python scripts/init_env.py')
a=getpass.getpass('请输入管理员新密码（至少14位）: ')
b=getpass.getpass('请再输入一次: ')
if a!=b:raise SystemExit('两次输入不一致')
ph=password_hash(a)
lines=path.read_text(encoding='utf-8').splitlines()
lines=[line for line in lines if not line.startswith('ADMIN_PASSWORD_HASH=')]
lines.append('ADMIN_PASSWORD_HASH='+ph)
path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
try:os.chmod(path,0o600)
except OSError:pass
print('已写入 ADMIN_PASSWORD_HASH（不保存明文密码）。请重启服务。')
