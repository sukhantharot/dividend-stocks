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
            
            # Wait for the main content to be visible
            await page.wait_for_selector('body', state='visible', timeout=10000)
            
            # Wait for the stock name to be visible (indicates page is loaded)
            try:
                await page.wait_for_selector('h1', timeout=10000)
            except PlaywrightTimeoutError:
                raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
            
            # Check if we're on the right page
            page_title = await page.title()
            if 'ไม่พบข้อมูล' in page_title or 'Not Found' in page_title:
                raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
            
            # Wait for the dividend table to load
            try:
                # First try to find the table container
                await page.wait_for_selector('div.table-responsive', timeout=10000)
                
                # Then wait for the actual table
                await page.wait_for_selector('div.table-responsive table', timeout=10000)
                
                # Wait a bit more for any dynamic content
                await page.wait_for_timeout(2000)
                
            except PlaywrightTimeoutError:
                # If table not found, check if there's any dividend data
                content = await page.content()
                if 'ไม่มีข้อมูล' in content or 'No data' in content:
                    return []  # Return empty list if no dividend data
                raise HTTPException(status_code=500, detail="Could not find dividend table")
            
            # Get the page content
            content = await page.content()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find the dividend table
            table = soup.select_one('div.table-responsive table')
            if not table:
                return []  # Return empty list if no table found
            
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