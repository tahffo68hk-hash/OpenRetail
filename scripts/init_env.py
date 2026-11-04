#!/usr/bin/env python3
"""Generate demo-only local secrets once. Never overwrite existing .env."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
dst=root/'.env'
if dst.exists():
    print('.env already exists; nothing changed.')
else:
    data=(root/'.env.example').read_text(encoding='utf-8')
    for placeholder in ['REPLACE_WITH_RANDOM_ADMIN_KEY','REPLACE_WITH_RANDOM_INTEGRATION_KEY','REPLACE_WITH_RANDOM_SECRET']:
        data=data.replace(placeholder,secrets.token_urlsafe(32))
    dst.write_text(data,encoding='utf-8')
    try:dst.chmod(0o600)
    except OSError:pass
    print('Created local .env with new random demo credentials; not stored in Git.')
