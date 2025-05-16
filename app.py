from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
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
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            # Navigate to the Settrade page
            url = f"https://www.settrade.com/th/equities/quote/{symbol}/rights-benefits"
            await page.goto(url)
            
            # Wait for the table to load
            await page.wait_for_selector('table.table-info', timeout=10000)
            
            # Get the page content
            content = await page.content()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find the dividend table
            table = soup.find('table', {'class': 'table-info'})
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
            
            return dividends
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
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