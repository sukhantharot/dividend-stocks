from fastapi import FastAPI, HTTPException, Query
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

async def scrape_dividends(symbol: str) -> List[Dict]:
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
            # Navigate to Google Finance
            url = f"https://www.google.com/finance/quote/{symbol}:BKK"
            await page.goto(url, timeout=30000)
            
            # Wait for the main content to be visible
            await page.wait_for_selector('body', state='visible', timeout=10000)
            
            # Check if stock exists
            try:
                await page.wait_for_selector('h1', timeout=10000)
            except PlaywrightTimeoutError:
                raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
            
            # Wait for dividend data
            try:
                # Wait for the dividend section
                await page.wait_for_selector('div[data-test="dividend-yield"]', timeout=10000)
                
                # Get the page content
                content = await page.content()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find dividend yield
                dividend_yield = soup.select_one('div[data-test="dividend-yield"]')
                if not dividend_yield:
                    return []  # Return empty list if no dividend data
                
                # Extract dividend data
                dividends = []
                dividend_value = dividend_yield.text.strip()
                
                if dividend_value and dividend_value != '-':
                    # Get current price
                    price_element = soup.select_one('div[data-test="current-price"]')
                    current_price = price_element.text.strip() if price_element else '0'
                    
                    # Calculate dividend per share
                    try:
                        price = float(current_price.replace('฿', '').replace(',', ''))
                        yield_percent = float(dividend_value.replace('%', ''))
                        dividend_per_share = (price * yield_percent) / 100
                        
                        dividend = {
                            'date': time.strftime('%Y-%m-%d'),
                            'type': 'เงินปันผล',
                            'value': f'{dividend_per_share:.2f}',
                            'yield': dividend_value,
                            'price': current_price
                        }
                        dividends.append(dividend)
                    except (ValueError, ZeroDivisionError):
                        pass
                
                return dividends
                
            except PlaywrightTimeoutError:
                return []  # Return empty list if no dividend data
            
        except HTTPException as e:
            raise e
        except PlaywrightTimeoutError as e:
            raise HTTPException(status_code=500, detail=f"Timeout while scraping: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error while scraping: {str(e)}")
        finally:
            await context.close()
            await browser.close()

@app.get("/dividends", response_model=DividendResponse, summary="Get latest dividend from Google Finance", description="ดึงข้อมูลปันผลล่าสุดของหุ้นจาก Google Finance (scrape ใหม่ทุกครั้ง)")
async def get_dividends(symbol: str = Query(..., description="Stock symbol, e.g. BANPU")) -> dict:
    # Convert symbol to lowercase
    symbol = symbol.lower()
    
    # Check cache first
    cached_data = redis_client.get(f"dividend:{symbol}")
    if cached_data:
        return json.loads(cached_data)
    
    try:
        # Scrape new data
        dividends = await scrape_dividends(symbol)
        
        # Prepare response
        response = {
            "symbol": symbol,
            "dividends": dividends,
            "timestamp": time.time()
        }
        
        # Cache the result
        redis_client.setex(
            f"dividend:{symbol}",
            CACHE_EXPIRY,
            json.dumps(response)
        )
        
        return response
        
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dividend data: {str(e)}")


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
    # 1. Check MongoDB for recent data unless force=1
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
    # 2. Scrape new data
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
                dividend = {
                    'symbol': symbol_upper,
                    'year': cols[0],
                    'quarter': cols[1],
                    'yield_percent': cols[2],
                    'amount': cols[3],
                    'xd_date': cols[4],
                    'pay_date': cols[5],
                    'type': cols[6],
                    'scraped_at': now.timestamp()
                }
                dividends.append(dividend)
            # 3. Insert only new records
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
            if new_dividends:
                dividends_collection.insert_many(new_dividends)
            # Return all records for this symbol
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv('API_HOST', '0.0.0.0'),
        port=int(os.getenv('API_PORT', 8000))
    ) 