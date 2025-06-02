import asyncio
from playwright.async_api import async_playwright
import re

async def close_modal_if_exists(page):
    try:
        # รอ modal สั้น ๆ ถ้ามี
        modal = await page.query_selector('#cboxWrapper')
        if modal:
            visible = await modal.is_visible()
            if visible:
                print("พบ modal สมัครสมาชิก กำลังปิด...")
                close_btn = await page.query_selector('#cboxClose')
                if close_btn:
                    await close_btn.click()
                    # รอ modal หายไป
                    await page.wait_for_selector('#cboxWrapper', state='detached', timeout=5000)
                    print("ปิด modal เรียบร้อย")
                else:
                    print("ไม่พบปุ่มปิด modal")
            else:
                print("modal มีใน DOM แต่ยังไม่แสดง ไม่ต้องปิด")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดขณะปิด modal: {e}")

async def main():
    base_url = "https://www.greataupair.com/fastfind.cfm/careType/housekeeper/countryList/200"
    display_rows = 45
    page_num = 1
    total_counted = 0
    current_count = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        while True:
            url = f"{base_url}/page/{page_num}/displayRows/{display_rows}"
            print(f"กำลังโหลด: {url}")
            try:
                await page.goto(url, timeout=30000)
            except Exception as e:
                print(f"เกิด error ขณะโหลด {url}: {e}")
                print("รอ 2 วินาทีแล้วลองใหม่...")
                await asyncio.sleep(2)
                continue  # กลับไปโหลดหน้าเดิมใหม่

            await close_modal_if_exists(page)
            try:
                await page.wait_for_selector("#searchResultsHeader > div.resultsNumbers", timeout=20000)
                results_text = await page.inner_text("#searchResultsHeader > div.resultsNumbers")
                print(f"results_text: {results_text}")  # debug ดูข้อความจริง
                match = re.search(r"of ([\d,]+) out of ([\d,]+)", results_text)
                if match:
                    current_count = int(match.group(1).replace(",", ""))
                    print(f"จำนวนโปรไฟล์ที่ค้นหาได้: {current_count}")
                else:
                    print("ไม่พบข้อมูลจำนวนโปรไฟล์")
                    break
            except Exception:
                print(f"ไม่พบ selector หรือโหลดหน้าไม่สำเร็จที่ {url}")
                print("URL ปัจจุบัน:", page.url)
                await asyncio.sleep(2)
                continue  # กลับไปโหลดหน้าเดิมใหม่

            try:
                await page.wait_for_selector('#searchList > div.searchResult', timeout=20000)
                profiles = await page.query_selector_all('#searchList > div.searchResult')
            except Exception:
                print(f"ไม่พบ searchResult ที่ {url}")
                await asyncio.sleep(2)
                continue  # กลับไปโหลดหน้าเดิมใหม่

            count_this_page = len(profiles)
            print(f"หน้า {page_num}: {count_this_page} โปรไฟล์")
            total_counted += count_this_page

            if count_this_page < display_rows:
                break
            page_num += 1

        print(f"รวมโปรไฟล์ที่นับได้จากทุกหน้า: {total_counted}")
        if current_count is not None:
            print(f"จำนวนที่ระบบแสดง: {current_count}")
            if total_counted == current_count:
                print('✔️ จำนวนตรงกัน')
            else:
                print('❌ จำนวนไม่ตรงกัน')
        else:
            print("ไม่สามารถดึงจำนวนที่ระบบแสดงได้")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
