from fastapi import FastAPI, HTTPException
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import redis
import json
from typing import List, Dict, Optional
import time

app = FastAPI(title="Thai Stock Dividend API")

# Redis configuration
redis_client = redis.Redis(host='redis', port=6379, db=0)
CACHE_EXPIRY = 300  # 5 minutes in seconds

def scrape_dividends(symbol: str) -> List[Dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Navigate to the Settrade page
            url = f"https://www.settrade.com/th/equities/quote/{symbol}/rights-benefits"
            page.goto(url)
            
            # Wait for the table to load
            page.wait_for_selector('table.table-info', timeout=10000)
            
            # Get the page content
            content = page.content()
            
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
            browser.close()

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
        dividends = scrape_dividends(symbol)
        
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
    uvicorn.run(app, host="0.0.0.0", port=8000) 