from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import redis
import json
from typing import List, Dict, Optional
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Thai Stock Dividend API")

# Redis configuration from environment variables
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'redis'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=int(os.getenv('REDIS_DB', 0)),
    username=os.getenv('REDIS_USERNAME', 'default'),
    password=os.getenv('REDIS_PASSWORD', None)
)
CACHE_EXPIRY = int(os.getenv('CACHE_EXPIRY', 300))  # 5 minutes in seconds

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
            # Navigate to the Settrade page
            url = f"https://www.settrade.com/th/equities/quote/{symbol}/rights-benefits"
            
            # Set longer timeout for initial page load
            await page.goto(url, timeout=60000)
            
            # Wait for any loading indicators to disappear
            try:
                await page.wait_for_selector('.loading', state='hidden', timeout=10000)
            except PlaywrightTimeoutError:
                pass  # Ignore if no loading indicator found
            
            # Wait for the main content to be visible
            await page.wait_for_selector('body', state='visible', timeout=10000)
            
            # Try to find the dividend table with multiple selectors
            selectors = [
                'table.table-info',
                'div.table-responsive table',
                'table[class*="table"]'
            ]
            
            table_found = False
            for selector in selectors:
                try:
                    await page.wait_for_selector(selector, timeout=10000)
                    table_found = True
                    break
                except PlaywrightTimeoutError:
                    continue
            
            if not table_found:
                # Check if page has error message
                error_text = await page.text_content('body')
                if 'ไม่พบข้อมูล' in error_text or 'Not Found' in error_text:
                    raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
                raise HTTPException(status_code=500, detail="Dividend table not found")
            
            # Wait a bit for any dynamic content to load
            await page.wait_for_timeout(2000)
            
            # Get the page content
            content = await page.content()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Try different table selectors
            table = None
            for selector in selectors:
                table = soup.select_one(selector)
                if table:
                    break
            
            if not table:
                raise HTTPException(status_code=404, detail="Dividend table not found")
            
            # Extract dividend data
            dividends = []
            rows = table.find_all('tr')[1:]  # Skip header row
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    dividend = {
                        'date': cols[0].text.strip(),
                        'type': cols[1].text.strip(),
                        'value': cols[2].text.strip(),
                        'payment_date': cols[3].text.strip()
                    }
                    dividends.append(dividend)
            
            if not dividends:
                raise HTTPException(status_code=404, detail="No dividend data found")
            
            return dividends
            
        except HTTPException as e:
            raise e
        except PlaywrightTimeoutError as e:
            raise HTTPException(status_code=500, detail=f"Timeout while scraping: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error while scraping: {str(e)}")
        finally:
            await context.close()
            await browser.close()

@app.get("/dividends")
async def get_dividends(symbol: str) -> Dict:
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv('API_HOST', '0.0.0.0'),
        port=int(os.getenv('API_PORT', 8000))
    ) 