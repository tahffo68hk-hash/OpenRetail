#!/usr/bin/env python3
"""Create entrance demo QR containing a URL (not an access credential).
pip install 'qrcode[pil]' ; python scripts/make_entry_qr.py https://localhost.example/
"""
from pathlib import Path
import sys

def main():
    if len(sys.argv)!=2 or not sys.argv[1].startswith(('https://','http://127.0.0.1','http://localhost')):
        raise SystemExit('Usage: python scripts/make_entry_qr.py https://YOUR-HTTPS-DEMO-URL/')
    import qrcode
    out=Path('entry-demo-qr.png')
    qrcode.make(sys.argv[1]).save(out)
    print(f'Created {out} -- URL only. App V1 does NOT verify customer identity.')
if __name__=='__main__':main()
