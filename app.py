from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.encoders import jsonable_encoder
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import redis
import json
from typing import List, Dict, Optional
import time
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta, UTC
import json as pyjson
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

app = FastAPI(title="Thai Stock Dividend API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis configuration from environment variables
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'redis'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=int(os.getenv('REDIS_DB', 0)),
    username=os.getenv('REDIS_USERNAME', 'default'),
    password=os.getenv('REDIS_PASSWORD', None)
)
CACHE_EXPIRY = int(os.getenv('CACHE_EXPIRY', 300))  # 5 minutes in seconds

MONGO_URI = os.getenv('MONGO_URI', os.getenv('MONGO_URL'))
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['dividend_db']
dividends_collection = db['dividends']
SYMBOLS_COLLECTION = db['symbols']

class DividendRecord(BaseModel):
    symbol: str = Field(..., example="BANPU")
    year: str = Field(..., example="2567")
    quarter: str = Field(..., example="2")
    yield_percent: str = Field(..., example="3.05")
    amount: str = Field(..., example="0.18")
    xd_date: str = Field(..., example="10/09/67")
    pay_date: str = Field(..., example="26/09/67")
    type: str = Field(..., example="เงินปันผล")
    scraped_at: float = Field(..., example=1718000000)

class DividendResponse(BaseModel):
    symbol: str
    dividends: list[DividendRecord]
    timestamp: float

class SummaryItem(BaseModel):
    symbol: str
    latest_dividend: DividendRecord

class SummaryResponse(BaseModel):
    summary: list[SummaryItem]
    year: str
    timestamp: float

def normalize_soon_date(xd_date: str, pay_date: str) -> Optional[datetime]:
    def parse(dstr):
        try:
            d, m, y = dstr.split('/')
            y = int(y)
            if y < 100:
                y += 2500           # สมมติรับปีเป็น 2 หลัก -> พ.ศ.
            if y > 2200:            # แปลง พ.ศ. -> ค.ศ.
                y -= 543
            when = datetime(y, int(m), int(d), tzinfo=UTC)

            # กรองปีเก่าออก
            if when.year < datetime.now(UTC).year - 1:
                return None
            return when
        except Exception:
            return None

    xd, pay = parse(xd_date), parse(pay_date)
    if xd and pay:
        return xd if xd < pay else pay
    return xd or pay


@app.get(
    "/dividends-panphor",
    response_model=DividendResponse,
    summary="Get dividend from Panphol.com (with MongoDB cache)",
    description="ดึงข้อมูลปันผลจาก https://aio.panphol.com/stock/{symbol}/dividend พร้อม cache ใน MongoDB"
)
async def get_dividends_panphor(
    symbol: str = Query(..., description="Stock symbol, e.g. BANPU"),
    force: int = Query(0, description="Force scraping if 1, otherwise use cache if data is recent")
) -> dict:
    symbol_upper = symbol.upper()
    now = datetime.now(UTC)
    one_month_ago = now - timedelta(days=30)
    if not force:
        recent_dividends = list(dividends_collection.find({
            'symbol': symbol_upper,
            'scraped_at': { '$gte': one_month_ago.timestamp() }
        }, {'_id': 0}))
        if recent_dividends:
            return {
                'symbol': symbol_upper,
                'dividends': recent_dividends,
                'timestamp': now.timestamp()
            }
    url = f"https://aio.panphol.com/stock/{symbol_upper}/dividend"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_selector('#basket', timeout=15000)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            table = soup.find('table', id='basket')
            if not table:
                raise HTTPException(status_code=404, detail='Dividend table not found')
            tbody = table.find('tbody')
            if not tbody:
                raise HTTPException(status_code=404, detail='No table body found')
            rows = tbody.find_all('tr')
            dividends = []
            for row in rows:
                cols = [col.get_text(strip=True) for col in row.find_all(['td', 'th'])]
                if len(cols) < 7:
                    continue
                soon_date = normalize_soon_date(cols[4], cols[5])
                dividend = {
                    'symbol': symbol_upper,
                    'year': cols[0],
                    'quarter': cols[1],
                    'yield_percent': cols[2],
                    'amount': cols[3],
                    'xd_date': cols[4],
                    'pay_date': cols[5],
                    'type': cols[6],
                    'scraped_at': now.timestamp(),
                    'soon_date': soon_date
                }
                dividends.append(dividend)
            new_dividends = []
            for d in dividends:
                exists = dividends_collection.find_one({
                    'symbol': d['symbol'],
                    'year': d['year'],
                    'quarter': d['quarter'],
                    'xd_date': d['xd_date'],
                    'amount': d['amount'],
                    'type': d['type']
                })
                if not exists:
                    new_dividends.append(d)
                else:
                    # Update soon_date if missing or different
                    if 'soon_date' not in exists or exists['soon_date'] != d['soon_date']:
                        dividends_collection.update_one(
                            {'_id': exists['_id']},
                            {'$set': {'soon_date': d['soon_date']}}
                        )
            if new_dividends:
                dividends_collection.insert_many(new_dividends)
            all_dividends = list(dividends_collection.find({'symbol': symbol_upper}, {'_id': 0}))
            return {
                'symbol': symbol_upper,
                'dividends': all_dividends,
                'timestamp': now.timestamp()
            }
        except PlaywrightTimeoutError as e:
            raise HTTPException(status_code=500, detail=f"Timeout while scraping: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error while scraping: {str(e)}")
        finally:
            await context.close()
            await browser.close()

@app.get(
    "/dividends-summary",
    response_model=SummaryResponse,
    summary="Summary of all stocks' latest dividend in a year",
    description="สรุปหุ้นทั้งหมดใน set.json พร้อมข้อมูลปันผลล่าสุดของแต่ละหุ้นในปีที่เลือก"
)
async def get_dividends_summary(
    year: Optional[str] = Query(None, description="Year in BE (พ.ศ.), e.g. 2567")
) -> dict:
    # Load symbols from set.json
    with open("set.json", "r", encoding="utf-8") as f:
        symbols = pyjson.load(f)["symbols"]
    now = datetime.now(UTC)
    if year is None:
        current_year = str(now.year + 543)  # Thai year (พ.ศ.)
    else:
        current_year = str(year)
    summary = []
    for symbol in symbols:
        # Find all dividends for this symbol in the selected year
        records = list(dividends_collection.find({
            'symbol': symbol,
            'year': current_year
        }, {'_id': 0}))
        if not records:
            continue
        # Find the latest by month (from xd_date or pay_date)
        def extract_month(rec):
            # Try xd_date first, fallback to pay_date
            for key in ['xd_date', 'pay_date']:
                try:
                    # Expect format dd/mm/yy
                    parts = rec[key].split('/')
                    if len(parts) >= 2:
                        return int(parts[1])
                except Exception:
                    continue
            return 0
        latest = max(records, key=extract_month)
        summary.append({
            'symbol': symbol,
            'latest_dividend': latest
        })
    return {
        'summary': summary,
        'year': current_year,
        'timestamp': now.timestamp()
    }

@app.get("/symbols", summary="Get all stock symbols from set.json", description="ดึงรายชื่อหุ้นทั้งหมดจาก set.json")
async def get_symbols() -> dict:
    with open("set.json", "r", encoding="utf-8") as f:
        symbols = pyjson.load(f)["symbols"]
    return {"symbols": symbols}

@app.get("/dividends/soon", summary="Get stocks with upcoming XD or dividend payment date", description="แสดงหุ้นที่ใกล้จะขึ้น XD หรือจ่ายปันผล (อิงจาก soon_date >= วันนี้)")
async def get_dividends_soon() -> dict:
    today = datetime.now(UTC)

    cursor = dividends_collection.find(
        {
            "type": "เงินปันผล",
            "soon_date": {"$gte": today}
        }
    ).sort("soon_date", 1)

    docs = list(cursor)
    # แปลง datetime -> ISO‑8601 string ก่อนส่งกลับ
    soon_list = jsonable_encoder(docs)

    return {"soon": soon_list, "timestamp": today.timestamp()}

@app.get("/symbols/db", summary="Find all symbols in MongoDB", description="ดึง symbol ทั้งหมดจาก MongoDB")
async def get_symbols_db() -> dict:
    symbols = list(SYMBOLS_COLLECTION.find({}, {'_id': 0, 'symbol': 1}))
    return {"symbols": [s['symbol'] for s in symbols]}

@app.post("/symbols/db", summary="Insert many symbols to MongoDB (skip existing)", description="เพิ่ม symbol หลายตัว (ถ้ามีอยู่แล้วให้ข้าม)")
async def insert_symbols_db(data: dict = Body(..., example={"symbols": ["AAV", "BANPU"]})) -> dict:
    input_symbols = set([s.upper() for s in data.get('symbols', [])])
    existing = set([s['symbol'] for s in SYMBOLS_COLLECTION.find({'symbol': {'$in': list(input_symbols)}}, {'symbol': 1, '_id': 0})])
    to_insert = [{'symbol': s} for s in input_symbols if s not in existing]
    if to_insert:
        SYMBOLS_COLLECTION.insert_many(to_insert)
    return {"inserted": [s['symbol'] for s in to_insert], "skipped": list(existing)}

@app.delete("/symbols/db", summary="Delete many symbols from MongoDB", description="ลบ symbol หลายตัว (โดยใช้ชื่อ symbol ไม่ใช้ _id)")
async def delete_symbols_db(data: dict = Body(..., example={"symbols": ["AAV"]})) -> dict:
    del_symbols = [s.upper() for s in data.get('symbols', [])]
    result = SYMBOLS_COLLECTION.delete_many({'symbol': {'$in': del_symbols}})
    return {"deleted_count": result.deleted_count, "deleted_symbols": del_symbols}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv('API_HOST', '0.0.0.0'),
        port=int(os.getenv('API_PORT', 8000))
    ) 