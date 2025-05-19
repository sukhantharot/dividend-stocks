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


@app.get("/dividends-panphor")        
async def get_dividends_panphor(symbol: str) -> Dict:
    url = f"https://aio.panphol.com/stock/{symbol.upper()}/dividend"
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
                    'year': cols[0],
                    'quarter': cols[1],
                    'yield_percent': cols[2],
                    'amount': cols[3],
                    'xd_date': cols[4],
                    'pay_date': cols[5],
                    'type': cols[6],
                }
                dividends.append(dividend)
            return {
                'symbol': symbol.upper(),
                'dividends': dividends,
                'timestamp': time.time()
            }
        except PlaywrightTimeoutError as e:
            raise HTTPException(status_code=500, detail=f"Timeout while scraping: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error while scraping: {str(e)}")
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv('API_HOST', '0.0.0.0'),
        port=int(os.getenv('API_PORT', 8000))
    ) 