"""Single-node SQLite store. Transactional reservations and append-only movements.

V2 is deliberately single-node: BEGIN IMMEDIATE provides a serialized writer. Do not
scale to multiple SQLite replicas, mount on NFS, or bypass these write paths.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS products(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 barcode TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL,
 price_cents INTEGER NOT NULL CHECK(price_cents>=0),
 stock INTEGER NOT NULL CHECK(stock>=0),
 reserved_stock INTEGER NOT NULL DEFAULT 0 CHECK(reserved_stock>=0 AND reserved_stock<=stock),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS guest_sessions(
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 verified_identity_hash TEXT
);
CREATE TABLE IF NOT EXISTS store_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES guest_sessions(id),
 request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','PAYMENT_PENDING','PAID','EXPIRED','CANCELLED','PAYMENT_REVIEW','REFUNDED')),
 total_cents INTEGER NOT NULL CHECK(total_cents>=0),
 created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,paid_at INTEGER,
 payment_reference TEXT, UNIQUE(session_id,request_id)
);
CREATE TABLE IF NOT EXISTS order_lines(
 id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL REFERENCES orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id),barcode TEXT NOT NULL,
 name TEXT NOT NULL,unit_price_cents INTEGER NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0)
);
CREATE TABLE IF NOT EXISTS payments(
 id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),
 provider TEXT NOT NULL,verified INTEGER NOT NULL,created_at INTEGER NOT NULL,
 UNIQUE(provider,id)
);
CREATE TABLE IF NOT EXISTS door_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL REFERENCES guest_sessions(id),
 result TEXT NOT NULL,provider TEXT NOT NULL,detail TEXT NOT NULL,created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents(
 id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT NOT NULL UNIQUE,
 source TEXT NOT NULL,label TEXT NOT NULL,camera TEXT NOT NULL,event_type TEXT NOT NULL,created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,
 detail TEXT NOT NULL,created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_movements(
 id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL REFERENCES products(id),
 stock_delta INTEGER NOT NULL,reserved_delta INTEGER NOT NULL,reason TEXT NOT NULL,
 reference TEXT NOT NULL,created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_notifications(
 event_id TEXT PRIMARY KEY,provider TEXT NOT NULL,order_id TEXT NOT NULL,
 outcome TEXT NOT NULL,received_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS refunds(
 id TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
 provider TEXT NOT NULL,amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_sessions(
 token_hash TEXT PRIMARY KEY,csrf_hash TEXT NOT NULL,
 created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts(
 fingerprint TEXT PRIMARY KEY,failed INTEGER NOT NULL,blocked_until INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkout_invites(
 invite_hash TEXT PRIMARY KEY,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,consumed_at INTEGER
);
CREATE TABLE IF NOT EXISTS help_requests(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id TEXT,
 order_id TEXT,
 message TEXT NOT NULL,
 created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status_exp ON orders(status,expires_at);
CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id,created_at);
CREATE INDEX IF NOT EXISTS idx_stock_movement_product ON stock_movements(product_id,id);
'''
SEED = [
 ('6901234567892','瓶装饮用水 550ml',200,80),
 ('6921168509256','方便面 香辣味',450,36),
 ('6901028075862','抽纸家庭装',1290,32),
 ('6936983800013','洗手液 500ml',1590,20),
 ('6920907800002','牙刷 软毛',690,25),
 ('6954767400015','垃圾袋 30只',890,18),
 ('6903148045328','洗衣液 1kg',2590,16),
 ('6920459950014','笔记本 A5',650,40),
]

class Database:
    def __init__(self,path:str):
        self.path=path
        if path!=':memory:':Path(path).parent.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def connect(self):
        if self.path!=':memory:':
            target=Path(self.path)
            if target.exists() and not target.is_file():
                raise RuntimeError(f'数据库路径不是文件: {target}')
        conn=sqlite3.connect(self.path,timeout=8,isolation_level=None,check_same_thread=False)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=8000')
        try:yield conn
        finally:conn.close()

    @contextmanager
    def tx(self):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
                conn.execute('COMMIT')
            except BaseException:
                if conn.in_transaction:conn.execute('ROLLBACK')
                raise

    def init(self,demo:bool):
        # Upgrade V1 without deleting data. SQLite DDL must not overwrite reserved balances.
        with self.connect() as c:
            cols={x['name'] for x in c.execute('PRAGMA table_info(products)')}
            if cols and 'reserved_stock' not in cols:c.execute('ALTER TABLE products ADD COLUMN reserved_stock INTEGER NOT NULL DEFAULT 0')
            cols={x['name'] for x in c.execute('PRAGMA table_info(guest_sessions)')}
            if cols and 'verified_identity_hash' not in cols:c.execute('ALTER TABLE guest_sessions ADD COLUMN verified_identity_hash TEXT')
            cols={x['name'] for x in c.execute('PRAGMA table_info(orders)')}
            if cols and 'payment_reference' not in cols:c.execute('ALTER TABLE orders ADD COLUMN payment_reference TEXT')
            order_table=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
            if order_table and ('PAYMENT_PENDING' not in order_table['sql'] or 'REFUNDED' not in order_table['sql']):
                # Rebuild the CHECK constraint; preserve orders and existing foreign-key relations.
                c.execute('PRAGMA foreign_keys=OFF')
                try:
                    c.execute('BEGIN EXCLUSIVE')
                    c.execute('''CREATE TABLE orders_v2(
                      id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES guest_sessions(id),
                      request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
                      status TEXT NOT NULL CHECK(status IN ('PENDING','PAYMENT_PENDING','PAID','EXPIRED','CANCELLED','PAYMENT_REVIEW','REFUNDED')),
                      total_cents INTEGER NOT NULL CHECK(total_cents>=0),created_at INTEGER NOT NULL,
                      expires_at INTEGER NOT NULL,paid_at INTEGER,payment_reference TEXT,
                      UNIQUE(session_id,request_id))''')
                    c.execute('''INSERT INTO orders_v2(id,session_id,request_id,fingerprint,status,total_cents,created_at,expires_at,paid_at,payment_reference)
                                 SELECT id,session_id,request_id,fingerprint,status,total_cents,created_at,expires_at,paid_at,payment_reference FROM orders''')
                    c.execute('DROP TABLE orders')
                    c.execute('ALTER TABLE orders_v2 RENAME TO orders')
                    c.execute('COMMIT')
                except BaseException:
                    if c.in_transaction:c.execute('ROLLBACK')
                    raise
                finally:
                    c.execute('PRAGMA foreign_keys=ON')
                if c.execute('PRAGMA foreign_key_check').fetchone():
                    raise RuntimeError('V1 migration failed foreign key check; restore backup')
            c.executescript(SCHEMA)
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO store_settings(key,value) VALUES('mode','STAFFED')")
            if demo and not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
                c.executemany('INSERT INTO products(barcode,name,price_cents,stock) VALUES(?,?,?,?)',SEED)
            # SQLite in this repository is the inventory system of record. Products
            # that have never posted a movement get one opening row so later
            # sums can be reconciled. Rows that already have history are not rewritten.
            missing=c.execute('''SELECT id,stock,reserved_stock FROM products p
                WHERE NOT EXISTS (SELECT 1 FROM stock_movements m WHERE m.product_id=p.id)''').fetchall()
            for product in missing:
                Database.movement(c,product['id'],product['stock'],product['reserved_stock'],'OPENING_BALANCE','SQLITE_SOR')

    @staticmethod
    def audit(c,actor:str,action:str,detail:str):
        c.execute('INSERT INTO audit_events(actor,action,detail,created_at) VALUES(?,?,?,?)',
                  (actor,action,detail,int(time.time())))

    @staticmethod
    def movement(c,product_id:int,stock_delta:int,reserved_delta:int,reason:str,reference:str):
        c.execute('INSERT INTO stock_movements(product_id,stock_delta,reserved_delta,reason,reference,created_at) VALUES(?,?,?,?,?,?)',
                  (product_id,stock_delta,reserved_delta,reason,reference,int(time.time())))

    @staticmethod
    def release(c,order_id:str,reason:str):
        for item in c.execute('SELECT product_id,quantity FROM order_lines WHERE order_id=?',(order_id,)).fetchall():
            cur=c.execute('UPDATE products SET reserved_stock=reserved_stock-? WHERE id=? AND reserved_stock>=?',
                          (item['quantity'],item['product_id'],item['quantity']))
            if cur.rowcount!=1:raise RuntimeError('reservation invariant broken')
            Database.movement(c,item['product_id'],0,-item['quantity'],reason,order_id)

    @staticmethod
    def expire(c,timestamp:int)->int:
        """Release stock for local orders that cannot have taken real money.

        PENDING never reached a gateway. PAYMENT_PENDING is released only when
        payment_reference starts with mock: (the in-process sandbox). A WeChat
        PAYMENT_PENDING row stays reserved until provider query/close.
        """
        rows=c.execute('''SELECT id FROM orders WHERE expires_at<=? AND (
                            status='PENDING' OR (status='PAYMENT_PENDING' AND payment_reference LIKE 'mock:%')
                          )''',(timestamp,)).fetchall()
        for row in rows:
            Database.release(c,row['id'],'ORDER_EXPIRED')
            c.execute("UPDATE orders SET status='EXPIRED' WHERE id=?",(row['id'],))
        return len(rows)
