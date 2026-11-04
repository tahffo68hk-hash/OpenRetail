"""Lossless-enough normalized CSV import, including common OSPOS export labels.
This is NOT a version-guaranteed OSPOS API or bidirectional sync.
"""
import csv
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ALIASES={
 'barcode':['barcode','item_number','item code','sku','item_code','条码','商品条码'],
 'name':['name','item_name','商品名称','product_name'],
 'price':['unit_price','price','retail_price','售价','standard_rate'],
 'stock':['quantity','stock','qty','库存','quantity_in_stock'],
}
class ImportErrorDetail(ValueError):pass

def parse_catalog(content:bytes):
    if len(content)>2_000_000:raise ImportErrorDetail('CSV exceeds 2 MB')
    try:
        source=content.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise ImportErrorDetail('CSV must be UTF-8 or UTF-8 BOM') from e
    reader=csv.DictReader(io.StringIO(source))
    if not reader.fieldnames: raise ImportErrorDetail('CSV has no header')
    headers={h.strip().lower():h for h in reader.fieldnames if h}
    mapping={}
    for key,candidates in ALIASES.items():
        matched=next((headers[c] for c in candidates if c in headers),None)
        if not matched:raise ImportErrorDetail(f'Missing CSV column {key}, choices: {candidates}')
        mapping[key]=matched
    items=[];seen=set()
    for index,row in enumerate(reader,start=2):
        try:
            code=(row.get(mapping['barcode']) or '').strip()
            name=(row.get(mapping['name']) or '').strip()
            if not code or len(code)>64 or not name or len(name)>120:raise ValueError('invalid barcode/name')
            if code in seen:raise ValueError('duplicate barcode')
            seen.add(code)
            # Decimal prevents float drift; round to cents explicitly.
            cents=int((Decimal((row.get(mapping['price']) or '').strip())*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            stock_text=(row.get(mapping['stock']) or '').strip()
            stock=int(stock_text)
            if cents<0 or cents>100_000_000 or stock<0 or stock>1_000_000:
                raise ValueError('price or stock out of bounds')
            items.append({'barcode':code,'name':name,'price_cents':cents,'stock':stock})
        except (ValueError,InvalidOperation) as e:
            raise ImportErrorDetail(f'CSV row {index}: {str(e)}') from e
        if len(items)>5000:raise ImportErrorDetail('CSV must have <=5000 products')
    if not items:raise ImportErrorDetail('CSV has no products')
    return items
