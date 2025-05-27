import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json
from bs4 import BeautifulSoup
import re

class SETXDScraper:
    def __init__(self):
        self.base_url = "https://www.set.or.th"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'th-TH,th;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_xd_calendar_data(self, year=None, month=None):
        """
        ดึงข้อมูล XD จากปฏิทิน SET
        """
        if year is None:
            year = datetime.now().year
        if month is None:
            month = datetime.now().month
            
        try:
            # URL สำหรับ API ของปฏิทิน (อาจจะต้องปรับตาม structure จริงของเว็บ)
            calendar_url = f"{self.base_url}/th/market/stock-calendar/x-calendar"
            
            # Parameters สำหรับเรียกข้อมูลเดือนที่ต้องการ
            params = {
                'year': year,
                'month': month
            }
            
            print(f"กำลังดึงข้อมูล XD สำหรับ {month}/{year}...")
            response = self.session.get(calendar_url, params=params, timeout=10)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # ค้นหาข้อมูล XD ในปฏิทิน
            xd_data = self.parse_xd_data(soup, year, month)
            
            time.sleep(1)  # หน่วงเวลาเพื่อไม่ให้เซิร์ฟเวอร์โหลดหนัก
            
            return xd_data
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            return []
        except Exception as e:
            print(f"Error parsing data: {e}")
            return []
    
    def parse_xd_data(self, soup, year, month):
        """
        แปลงข้อมูล HTML เป็นข้อมูล XD
        """
        xd_events = []
        
        # ค้นหา elements ที่มีข้อมูล XD
        # (ต้องปรับ selector ตาม structure จริงของเว็บ)
        calendar_cells = soup.find_all(['td', 'div'], class_=re.compile('calendar|day|event'))
        
        for cell in calendar_cells:
            # ค้นหาข้อความที่มี "XD" หรือ "เงินปันผล"
            text = cell.get_text(strip=True)
            
            if 'XD' in text or 'เงินปันผล' in text or 'ปันผล' in text:
                # Extract วันที่
                date_match = re.search(r'\d{1,2}', text)
                if date_match:
                    day = int(date_match.group())
                    
                    # Extract ชื่อหุ้น
                    stock_match = re.search(r'([A-Z]{2,5})', text)
                    stock_symbol = stock_match.group(1) if stock_match else 'Unknown'
                    
                    # Extract อัตราเงินปันผล
                    dividend_match = re.search(r'(\d+\.?\d*)\s*บาท', text)
                    dividend_rate = float(dividend_match.group(1)) if dividend_match else 0.0
                    
                    xd_date = datetime(year, month, day).strftime('%Y-%m-%d')
                    
                    xd_events.append({
                        'date': xd_date,
                        'symbol': stock_symbol,
                        'dividend_rate': dividend_rate,
                        'event_type': 'XD',
                        'raw_text': text
                    })
        
        return xd_events
    
    def get_xd_data_range(self, start_date, end_date):
        """
        ดึงข้อมูล XD ในช่วงวันที่ที่กำหนด
        """
        all_xd_data = []
        current_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
        
        while current_date <= end_date_obj:
            year = current_date.year
            month = current_date.month
            
            month_data = self.get_xd_calendar_data(year, month)
            all_xd_data.extend(month_data)
            
            # ไปเดือนถัดไป
            if month == 12:
                current_date = datetime(year + 1, 1, 1)
            else:
                current_date = datetime(year, month + 1, 1)
        
        # กรองข้อมูลให้อยู่ในช่วงวันที่ที่ต้องการ
        filtered_data = [
            item for item in all_xd_data 
            if start_date <= item['date'] <= end_date
        ]
        
        return filtered_data
    
    def save_to_excel(self, data, filename='xd_calendar.xlsx'):
        """
        บันทึกข้อมูลลง Excel
        """
        if not data:
            print("ไม่มีข้อมูลให้บันทึก")
            return
        
        df = pd.DataFrame(data)
        df = df.sort_values('date')
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='XD_Calendar', index=False)
        
        print(f"บันทึกข้อมูลแล้วที่ {filename}")
        print(f"จำนวนรายการ: {len(data)} รายการ")
    
    def save_to_csv(self, data, filename='xd_calendar.csv'):
        """
        บันทึกข้อมูลลง CSV
        """
        if not data:
            print("ไม่มีข้อมูลให้บันทึก")
            return
        
        df = pd.DataFrame(data)
        df = df.sort_values('date')
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        
        print(f"บันทึกข้อมูลแล้วที่ {filename}")
        print(f"จำนวนรายการ: {len(data)} รายการ")

def main():
    """
    ตัวอย่างการใช้งาน
    """
    scraper = SETXDScraper()
    
    # ตัวอย่าง 1: ดึงข้อมูลเดือนปัจจุบัน
    print("=== ดึงข้อมูล XD เดือนปัจจุบัน ===")
    current_data = scraper.get_xd_calendar_data()
    
    if current_data:
        print("ข้อมูล XD ที่พบ:")
        for item in current_data:
            print(f"วันที่: {item['date']}, หุ้น: {item['symbol']}, "
                  f"เงินปันผล: {item['dividend_rate']} บาท")
    else:
        print("ไม่พบข้อมูล XD")
    
    # ตัวอย่าง 2: ดึงข้อมูลช่วงวันที่ที่กำหนด
    print("\n=== ดึงข้อมูล XD ช่วง 3 เดือนข้างหน้า ===")
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
    
    range_data = scraper.get_xd_data_range(start_date, end_date)
    
    if range_data:
        print(f"พบข้อมูล XD {len(range_data)} รายการ")
        
        # บันทึกลง Excel และ CSV
        scraper.save_to_excel(range_data, 'xd_calendar_3months.xlsx')
        scraper.save_to_csv(range_data, 'xd_calendar_3months.csv')
        
        # แสดงข้อมูลบางส่วน
        print("\nตัวอย่างข้อมูล 5 รายการแรก:")
        for item in range_data[:5]:
            print(f"วันที่: {item['date']}, หุ้น: {item['symbol']}, "
                  f"เงินปันผล: {item['dividend_rate']} บาท")
    else:
        print("ไม่พบข้อมูล XD ในช่วงนี้")

# Alternative approach ใช้ API ตรงๆ (ถ้ามี)
def scrape_xd_api_approach():
    """
    วิธีการทางเลือกโดยใช้ API โดยตรง (ถ้า SET มี API เปิด)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'th-TH,th;q=0.9,en;q=0.8',
        'Referer': 'https://www.set.or.th/th/market/stock-calendar/x-calendar'
    }
    
    # ลองหา API endpoint สำหรับปฏิทิน
    api_urls = [
        'https://www.set.or.th/api/set/calendar/xd',
        'https://www.set.or.th/api/calendar/dividend',
        'https://api.set.or.th/set/calendar/xd'
    ]
    
    for url in api_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                print(f"พบ API ที่ใช้งานได้: {url}")
                data = response.json()
                print("ตัวอย่างข้อมูล:", json.dumps(data, indent=2, ensure_ascii=False))
                return data
        except:
            continue
    
    print("ไม่พบ API ที่ใช้งานได้")
    return None
