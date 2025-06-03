import asyncio
from playwright.async_api import async_playwright
import re
import requests
import csv
import os
import urllib.parse

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

async def download_image(url, filename):
    try:
        # สร้างโฟลเดอร์ image ถ้ายังไม่มี
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code == 200 and r.content:
            with open(filename, 'wb') as f:
                f.write(r.content)
            print(f"ดาวน์โหลดรูปภาพสำเร็จ: {filename}")
        else:
            print(f"ดาวน์โหลดรูปภาพไม่สำเร็จ: {url} (status: {r.status_code}, size: {len(r.content)} bytes)")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดขณะดาวน์โหลดรูปภาพ: {e}")

async def extract_profile_data(page, profile_url):
    # ดึง profileLocatorId
    profile_id = await page.get_attribute('form#shareProfileForm input[name="profileLocatorId"]', 'value')
    print(f"profileLocatorId: {profile_id}")

    # ดึงรูปภาพ
    img_tag = await page.query_selector('.profilePic img')
    image_filename = ""
    if img_tag:
        img_url = await img_tag.get_attribute('src')
        print(f"img_url: {img_url}")  # debug
        if img_url and profile_id:
            # ถ้า img_url เป็น relative path ให้แปลงเป็น absolute
            if img_url.startswith("/"):
                img_url = urllib.parse.urljoin("https://www.greataupair.com", img_url)
            image_filename = f"image/{profile_id}.jpg"
            await download_image(img_url, image_filename)

    # ดึง Service
    services = []
    nav = await page.query_selector_all('#profile_type_nav a')
    for a in nav:
        text = (await a.inner_text()).strip()
        services.append(text)
    print("Service:", services)

    # ดึง Qualifications และ Personal
    columns = await page.query_selector_all('#profileOverview ul.column')
    personal, qualifications = [], []
    for col in columns:
        h4 = await col.query_selector('h4')
        if h4:
            h4_text = (await h4.inner_text()).strip().lower()
            items = [await (await li.get_property('textContent')).json_value() for li in await col.query_selector_all('li')]
            items = [i.strip() for i in items if i.strip()]
            if 'personal' in h4_text:
                personal = items
            elif 'qualification' in h4_text:
                qualifications = items
    print("Personal:", personal)
    print("Qualifications:", qualifications)

    return {
        "profileLocatorId": profile_id,
        "profile_url": profile_url,
        "services": "; ".join(services),
        "qualifications": "; ".join(qualifications),
        "personal": "; ".join(personal),
        "image_filename": image_filename
    }

async def main():
    base_url = "https://www.greataupair.com/fastfind.cfm/careType/housekeeper/countryList/200"
    display_rows = 45
    page_num = 1
    total_counted = 0
    current_count = None
    seen_ids = set()
    csv_filename = "profiles.csv"
    write_header = not os.path.exists(csv_filename)
    with open(csv_filename, "a", newline='', encoding="utf-8") as csv_file:
        csv_writer = csv.writer(csv_file)
        if write_header:
            csv_writer.writerow(["profileLocatorId", "profile_url", "services", "qualifications", "personal", "image_filename"])

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
                    count_this_page = 0
                    for profile in profiles:
                        try:
                            a_tag = await profile.query_selector('.searchResultPic .shadow a')
                            if a_tag:
                                href = await a_tag.get_attribute('href')
                                print(f"href ที่ดึงได้: {href}")
                                if href:
                                    profile_url = f"https://www.greataupair.com{href}"
                                    print(f"จะเปิดโปรไฟล์: {profile_url}")
                                    new_tab = await browser.new_page()
                                    try:
                                        response = await new_tab.goto(profile_url)
                                        print(f"Status code: {response.status if response else 'N/A'}")
                                        await new_tab.wait_for_load_state('networkidle')
                                        profile_data = await extract_profile_data(new_tab, profile_url)
                                        profile_id = profile_data["profileLocatorId"]
                                        if not profile_id:
                                            print(f"ไม่พบ profileLocatorId สำหรับ {profile_url} -- ข้ามการบันทึก")
                                        elif profile_id not in seen_ids:
                                            csv_writer.writerow([
                                                profile_data["profileLocatorId"],
                                                profile_data["profile_url"],
                                                profile_data["services"],
                                                profile_data["qualifications"],
                                                profile_data["personal"],
                                                profile_data["image_filename"]
                                            ])
                                            seen_ids.add(profile_id)
                                        else:
                                            print(f"ข้าม profile ซ้ำ: {profile_id}")
                                    except Exception as e:
                                        print(f"เกิดข้อผิดพลาดขณะเปิดโปรไฟล์: {e}")
                                    await new_tab.close()
                                else:
                                    print("ไม่พบ href ใน a_tag")
                            else:
                                print("ไม่พบ a_tag ใน profile นี้")
                            count_this_page += 1
                        except Exception as e:
                            print(f"เกิดข้อผิดพลาดกับโปรไฟล์นี้: {e}")
                    print(f"หน้า {page_num}: {count_this_page} โปรไฟล์")
                    total_counted += count_this_page

                    if count_this_page < display_rows:
                        break
                    page_num += 1
                except Exception:
                    print(f"ไม่พบ searchResult ที่ {url}")
                    await asyncio.sleep(2)
                    # INCREMENT page_num to avoid infinite loop
                    page_num += 1
                    continue  # ไปหน้าถัดไป

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
