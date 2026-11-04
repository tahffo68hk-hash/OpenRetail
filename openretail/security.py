"""Local operator authentication: PBKDF2 verifier and DB-backed opaque sessions."""
import base64
import hashlib
import hmac
import secrets
import time

ITERATIONS=520_000

def password_hash(password:str,salt:bytes|None=None)->str:
    if len(password)<14:raise ValueError('管理员密码至少14字符')
    salt=salt or secrets.token_bytes(20)
    derived=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(derived).decode()}'

def password_verify(password:str,encoded:str)->bool:
    try:
        alg,iterations,salt,expected=encoded.split('$')
        if alg!='pbkdf2_sha256' or not (100_000<=int(iterations)<=1_000_000):return False
        got=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.urlsafe_b64decode(salt),int(iterations))
        return hmac.compare_digest(got,base64.urlsafe_b64decode(expected))
    except (ValueError,TypeError,base64.binascii.Error):return False

def digest(value:str)->str:return hashlib.sha256(value.encode()).hexdigest()
def random_token()->str:return secrets.token_urlsafe(36)
def timestamp()->int:return int(time.time())
