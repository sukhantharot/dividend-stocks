import os
import pandas as pd
from datetime import datetime, timedelta, UTC
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re
from pymongo import MongoClient

# ปิด warnings ที่ไม่จำเป็น
import warnings
warnings.filterwarnings('ignore')

MONGO_URI = os.getenv('MONGO_URI', os.getenv('MONGO_URL'))
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['dividend_db']
dividends_collection = db['dividends']

THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12
}

class SETXDScraper:
    def __init__(self, headless=True):
        self.base_url = "https://www.set.or.th"
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
    
    async def setup_browser(self):
        """
        ตั้งค่า Playwright Browser
        """
        try:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            self.page = await self.context.new_page()
            print("เปิด Browser สำเร็จ")
        except Exception as e:
            print(f"Error setting up browser: {e}")
    
    def insert_dividends_to_mongo(self, xd_data):
        """
        เพิ่มข้อมูล XD ลง MongoDB โดยตรวจสอบข้อมูลซ้ำ
        """
        if xd_data:
            for dividend in xd_data:
                exists = dividends_collection.find_one({
                    'symbol': dividend['symbol'],
                    'year': dividend['year'],
                    'amount': dividend['amount'],
                    'xd_date': dividend['xd_date'],
                    'type': dividend['type'],
                    'pay_date_utc': dividend['pay_date_utc']
                })
                if not exists:
                    dividends_collection.insert_one(dividend)
                    print(f"Inserted {dividend['symbol']} {dividend['xd_date']}")
                else:
                    print(f"Skipped {dividend['symbol']} {dividend['xd_date']} (already exists)")

    async def get_xd_calendar_data(self, year=None, month=None):
        """
        ดึงข้อมูล XD จากปฏิทิน SET ด้วย Playwright
        """
        if not self.page:
            await self.setup_browser()
            
        if year is None:
            year = datetime.now().year
        if month is None:
            month = datetime.now().month
            
        try:
            calendar_url = f"{self.base_url}/th/market/stock-calendar/x-calendar"
            print(f"กำลังโหลดหน้าเว็บ: {calendar_url}")
            
            await self.page.goto(calendar_url, wait_until='networkidle')
            
            # ลองหาและคลิกปุ่มเปลี่ยนเดือน/ปี (ถ้ามี)
            await self.navigate_to_month(year, month)
            
            # รอให้ข้อมูลโหลด
            await self.page.wait_for_timeout(3000)
            
            # ดึงข้อมูล XD
            xd_data = await self.parse_xd_from_page(year, month)
            
            # เรียกฟังก์ชันใหม่สำหรับ insert
            self.insert_dividends_to_mongo(xd_data)
            return xd_data
            
        except PlaywrightTimeoutError:
            print("Timeout: หน้าเว็บโหลดช้าเกินไป")
            return []
        except Exception as e:
            print(f"Error: {e}")
            return []
    
    async def navigate_to_month(self, target_year, target_month):
        """
        นำทางไปยังเดือน/ปีที่ต้องการ (ใช้ selector ที่ตรงกับหน้าเว็บจริง)
        """
        try:
            # แปลงเดือนเป็นชื่อไทย
            month_th = [k for k, v in THAI_MONTHS.items() if v == target_month][0]
            # หา tab/button ที่ตรงกับเดือนและปี
            buttons = await self.page.query_selector_all('.month-item')
            found = False
            for btn in buttons:
                label_month = await btn.query_selector('.label-month')
                label_year = await btn.query_selector('.label-year')
                if not label_month or not label_year:
                    continue
                month_text = (await label_month.text_content()).strip()
                year_text = (await label_year.text_content()).strip()
                if month_text == month_th and year_text == str(target_year + 543):  # ปีไทย
                    await btn.click()
                    await self.page.wait_for_timeout(1500)
                    found = True
                    print(f'Clicked tab for {month_text} {year_text}')
                    break
            if not found:
                print(f'ไม่พบ tab สำหรับ {month_th} {target_year + 543}')
        except Exception as e:
            print(f"ไม่สามารถนำทางไปยัง {target_month}/{target_year}: {e}")
    
    async def parse_xd_from_page(self, year, month):
        """
        แปลงข้อมูล HTML เป็นข้อมูล XD (เฉพาะหุ้น XD จริง)
        """
        xd_events = []
        processed_symbols = set()  # เก็บ symbol ที่เคยประมวลผลแล้ว
        
        # หา div ที่มี class x-symbol
        x_symbol_divs = await self.page.query_selector_all(".x-symbol")
        for div in x_symbol_divs:
            try:
                # ดึงข้อมูลทั้งหมดในรอบเดียวด้วย evaluate
                data = await div.evaluate('''(el) => {
                    const xdBadge = el.querySelector('.x-type.xd-font-color');
                    if (!xdBadge || xdBadge.textContent.trim().toUpperCase() !== 'XD') return null;
                    const symbolElem = el.querySelector('.badge-x-calendar');
                    const dropdown = el.querySelector('.dropdown-menu');
                    if (!symbolElem || !dropdown) return null;
                    return {
                        symbol: symbolElem.textContent.trim(),
                        html: dropdown.innerHTML
                    };
                }''')
                if not data:
                    continue
                symbol = data['symbol']
                html = data['html']
                # ข้ามถ้าเคยประมวลผลแล้ว
                if symbol in processed_symbols:
                    continue
                processed_symbols.add(symbol)
                print(f"Processing {symbol}...")
                def extract(label):
                    m = re.search(
                        rf'<div class="col-12 text-start">\s*{label}\s*</div>\s*<div class="col-12 text-start">(?:<span>)?([^<]+)',
                        html, re.DOTALL)
                    return m.group(1).strip() if m else ""
                # ดึงข้อมูลที่จำเป็น
                xd_date = extract("วันขึ้นเครื่องหมาย")
                pay_date = extract("วันจ่ายปันผล")
                amount = extract("เงินปันผล \\(บาท/หุ้น\\)").replace("บาท", "").strip()
                type_ = extract("ประเภท") or "เงินปันผล"
                round_period = extract("รอบผลประกอบการ")
                if not xd_date or not pay_date:
                    print(f"Skipping {symbol} - Missing dates")
                    continue
                def normalize_date_thai(date_str):
                    months = {"ม.ค.": "01", "ก.พ.": "02", "มี.ค.": "03", "เม.ย.": "04", "พ.ค.": "05", "มิ.ย.": "06",
                              "ก.ค.": "07", "ส.ค.": "08", "ก.ย.": "09", "ต.ค.": "10", "พ.ย.": "11", "ธ.ค.": "12"}
                    m = re.match(r"(\d{1,2}) (\S+) (\d{4})", date_str)
                    if m:
                        d, mth, y = m.groups()
                        return f"{d.zfill(2)}/{months.get(mth, '01')}/{str(int(y)%100).zfill(2)}", y
                    return date_str, ""
                xd_date_fmt, year_full = normalize_date_thai(xd_date)
                pay_date_fmt, _ = normalize_date_thai(pay_date)
                def to_datetime_obj(date_str):
                    try:
                        d, m, y = date_str.split('/')
                        y = int(y)
                        if y < 100:
                            y += 2500  # สมมติรับปีเป็น 2 หลัก -> พ.ศ.
                        if y > 2200:
                            y -= 543  # แปลง พ.ศ. -> ค.ศ.
                        dt = datetime(int(y), int(m), int(d), tzinfo=UTC)
                        if dt.year < datetime.now(UTC).year - 1:
                            return None
                        return dt
                    except Exception:
                        return None
                dividend = {
                    'symbol': symbol,
                    'year': year_full,
                    'quarter': "",  # TODO: หา logic เพิ่มเติม
                    'yield_percent': "",  # TODO: คำนวณจาก amount
                    'amount': amount,
                    'xd_date': xd_date_fmt,
                    'pay_date': pay_date_fmt,
                    'type': type_,
                    'scraped_at': datetime.now(UTC).timestamp(),
                    'xd_date_utc': to_datetime_obj(xd_date_fmt),
                    'pay_date_utc': to_datetime_obj(pay_date_fmt),
                    'round_period': round_period
                }
                xd_events.append(dividend)
                print(f"Added {symbol}: {xd_date_fmt} -> {pay_date_fmt} ({amount} บาท)")
            except Exception as e:
                print(f"Error processing symbol: {str(e)}")
                continue
        return xd_events
    
    async def close(self):
        """
        ปิด Browser
        """
        if self.browser:
            await self.browser.close()
            print("ปิด Browser แล้ว")

    async def get_next_month_xd(self):
        now = datetime.now()
        year = now.year
        month = now.month
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year
        return await self.get_xd_calendar_data(next_year, next_month)

async def main():
    scraper = SETXDScraper(headless=False)
    try:
        months_to_fetch = 7  # จำนวนเดือนที่ต้องการดึงต่อเนื่อง
        now = datetime.now()
        y, m = now.year, now.month
        for i in range(months_to_fetch):
            print(f"\n=== ดึงข้อมูล XD เดือนที่ {m}/{y} ===")
            data = await scraper.get_xd_calendar_data(y, m)
            if data:
                print(f"พบข้อมูล XD {len(data)} รายการ")
            else:
                print("ไม่พบข้อมูล XD")
            # เดือนไปข้างหน้า
            if m == 12:
                m = 1
                y += 1
            else:
                m += 1
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await scraper.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())