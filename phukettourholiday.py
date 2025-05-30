import os
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)
import re
import csv
from datetime import datetime


class PhuketTour:
    def __init__(self, headless=True):
        self.base_url = "https://www.phukettourholiday.com"
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        self.tours_data = []  # เพิ่มตัวแปรสำหรับเก็บข้อมูลทัวร์

    async def setup_browser(self):
        """
        ตั้งค่า Playwright Browser
        """
        try:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--ignore-certificate-errors",
                ],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            )
            self.page = await self.context.new_page()
            print("เปิด Browser สำเร็จ")
        except Exception as e:
            print(f"Error setting up browser: {e}")

    async def click_tour_button(self):
        """
        คลิกปุ่มทัวร์ที่ระบุ
        """
        try:
            print("กำลังเข้าถึงหน้าเว็บ")
            await self.page.goto(self.base_url)
            print("กำลังรอการโหลดข้อมูล")

            # คลิกที่เมนูทัวร์ภูเก็ต (เลือกปุ่มที่มี class show-submenu-mega)
            tour_menu = self.page.locator("#header_1").get_by_role(
                "link", name="ทัวร์ภูเก็ต", exact=True
            )
            await tour_menu.click()
            print("คลิกเมนูทัวร์ภูเก็ตสำเร็จ")
            await self.page.wait_for_timeout(500)
            # คลิกปุ่มทัวร์ภูเก็ตทั้งหมด
            tour_button_locator = self.page.get_by_role("link", name="ทัวร์ภูเก็ต ทั้งหมด")
            print("กำลังคลิกปุ่มทัวร์")
            await tour_button_locator.click(timeout=20000)
            print("คลิกปุ่มทัวร์สำเร็จ")

            await self.page.wait_for_timeout(2000)
            print("กำลังรอการโหลดข้อมูล")
            await self.extract_tour_list()
        except Exception as e:
            print(f"Error clicking tour button: {e}")

    async def click_phangnga_tour_button(self):
        """
        คลิกปุ่มทัวร์พังงา
        """
        try:
            print("กำลังเข้าถึงหน้าเว็บ")
            await self.page.goto(self.base_url)
            print("กำลังรอการโหลดข้อมูล")

            # คลิกที่เมนูทัวร์พังงา
            tour_menu = self.page.locator("#header_1").get_by_role(
                "link", name="ทัวร์พังงา", exact=True
            )
            await tour_menu.click()
            print("คลิกเมนูทัวร์พังงาสำเร็จ")
            await self.page.wait_for_timeout(500)
            # คลิกปุ่มทัวร์พังงาทั้งหมด
            tour_button_locator = self.page.get_by_role("link", name="ทัวร์พังงา ทั้งหมด")
            print("กำลังคลิกปุ่มทัวร์")
            await tour_button_locator.click(timeout=20000)
            print("คลิกปุ่มทัวร์สำเร็จ")

            await self.page.wait_for_timeout(2000)
            print("กำลังรอการโหลดข้อมูล")
            await self.extract_tour_list()
        except Exception as e:
            print(f"Error clicking Phang Nga tour button: {e}")

    async def click_krabi_tour_button(self):
        """
        คลิกปุ่มทัวร์กระบี่
        """
        try:
            print("กำลังเข้าถึงหน้าเว็บ")
            await self.page.goto(self.base_url)
            print("กำลังรอการโหลดข้อมูล")

            # คลิกที่เมนูทัวร์กระบี่
            tour_menu = self.page.locator("#header_1").get_by_role(
                "link", name="ทัวร์กระบี่", exact=True
            )
            await tour_menu.click()
            print("คลิกเมนูทัวร์กระบี่สำเร็จ")
            await self.page.wait_for_timeout(500)
            # คลิกปุ่มทัวร์กระบี่ทั้งหมด
            tour_button_locator = self.page.get_by_role("link", name="ทัวร์กระบี่ ทั้งหมด")
            print("กำลังคลิกปุ่มทัวร์")
            await tour_button_locator.click(timeout=20000)
            print("คลิกปุ่มทัวร์สำเร็จ")

            await self.page.wait_for_timeout(2000)
            print("กำลังรอการโหลดข้อมูล")
            await self.extract_tour_list()
        except Exception as e:
            print(f"Error clicking Krabi tour button: {e}")

    async def extract_tour_list(self):
        """
        ดึงข้อมูลทัวร์จาก container .row
        """
        try:
            print("กำลังดึงข้อมูลทัวร์จากหน้า")
            rows = await self.page.query_selector_all(".container .row")
            for row in rows:
                await self.extract_type1_tours(row)
                await self.extract_type2_tours(row)
        except Exception as e:
            print(f"Error extracting tour list: {e}")

    async def extract_type1_tours(self, row):
        """
        ดึงข้อมูลทัวร์แบบ 1: col-md-4 col-sm-6 wow fadeIn animated animated
        """
        tours = await row.query_selector_all(
            "div.col-md-4.col-sm-6.wow.fadeIn.animated.animated"
        )
        print("กำลังดึงข้อมูลทัวร์แบบ 1")
        for tour in tours:  # tour ในที่นี้คือ ElementHandle ของแต่ละ tour item
            # 1. ดึงข้อความจาก Ribbon
            ribbon_span_element = await tour.query_selector(".ribbon span")
            ribbon_text = (
                await ribbon_span_element.inner_text() if ribbon_span_element else ""
            )

            # 2. ดึงข้อความจาก Price Grid
            price_grid_element = await tour.query_selector(".price_grid")
            # ใช้ text_content() เพื่อให้ได้ข้อความทั้งหมดรวมถึงที่อยู่ใน <sup> และตัดช่องว่าง
            price_text = (
                await price_grid_element.text_content() if price_grid_element else ""
            ).strip()

            # ดึงข้อมูล img_container และส่วนที่เกี่ยวข้อง
            img_container = await tour.query_selector(".img_container")
            if img_container:
                a_element = await img_container.query_selector("a")
                if a_element:
                    link = await a_element.get_attribute("href") or ""
                    # 3. ดึง attribute 'title' ของแท็ก <a>
                    link_title_attr = await a_element.get_attribute("title") or ""

                    img_element = await a_element.query_selector("img")  # img อยู่ใน a
                    if img_element:
                        img_src = await img_element.get_attribute("src") or ""
                        # 4. ดึง attribute 'alt' ของแท็ก <img>
                        img_alt_text = await img_element.get_attribute("alt") or ""
                    else:
                        img_src = ""
                        img_alt_text = ""
                else:
                    link = ""
                    link_title_attr = ""
                    img_src = ""
                    img_alt_text = ""
            else:
                link = ""
                link_title_attr = ""
                img_src = ""
                img_alt_text = ""

            # ดึงข้อมูล short_info และส่วนที่เกี่ยวข้อง
            short_info = await tour.query_selector(".short_info")
            if short_info:
                h3 = await short_info.query_selector("h3")
                title_from_h3 = (
                    await h3.inner_text() if h3 else ""
                )  # เปลี่ยนชื่อตัวแปรเล็กน้อยเพื่อความชัดเจน

                em = await short_info.query_selector("em")
                desc = await em.inner_text() if em else ""

                p = await short_info.query_selector("p")
                detail = (await p.inner_text() if p else "").strip()
            else:
                title_from_h3 = ""
                desc = ""
                detail = ""

            # เก็บข้อมูลทัวร์
            tour_data = {
                "type": "type1",
                "title": title_from_h3 or link_title_attr,
                "description": desc,
                "details": detail,
                "price": price_text,
                "link": link,
                "image_url": img_src,
                "image_alt": img_alt_text,
                "ribbon": ribbon_text,
            }
            self.tours_data.append(tour_data)

            # แสดงผลข้อมูลที่ดึงมาได้ทั้งหมด
            print(
                f"[แบบปรับปรุง]\n"
                f"ชื่อ (จาก H3): {title_from_h3}\n"
                f"ชื่อ (จาก Link Title): {link_title_attr}\n"
                f"คำอธิบาย (em): {desc}\n"
                f"รายละเอียด (p): {detail}\n"
                f"ลิงก์ (href): {link}\n"
                f"รูป (src): {img_src}\n"
                f"คำอธิบายรูป (alt): {img_alt_text}\n"
                f"ริบบอน: {ribbon_text}\n"
                f"ราคา: {price_text}\n---"
            )

    async def extract_type2_tours(self, row):
        """
        ดึงข้อมูลทัวร์แบบ 2: col-md-3 col-xs-6 wow fadeIn animated animated
        """
        tours = await row.query_selector_all(
            "div.col-md-3.col-xs-6.wow.fadeIn.animated.animated"
        )
        print("กำลังดึงข้อมูลทัวร์แบบ 2")
        for tour in tours:
            # ดึงข้อมูลรูปภาพและลิงก์ (ส่วนนี้ดูเหมือนจะทำงานได้ดี)
            img_container = await tour.query_selector(".img_container")
            a_img_link_element = (
                await img_container.query_selector("a") if img_container else None
            )
            link_from_img = (
                await a_img_link_element.get_attribute("href")
                if a_img_link_element
                else ""
            )

            img_element = (
                await img_container.query_selector("img") if img_container else None
            )  # หรือ await a_img_link_element.query_selector("img") if a_img_link_element else None
            img_src = await img_element.get_attribute("src") if img_element else ""
            img_alt = await img_element.get_attribute("alt") if img_element else ""
            img_title_attr = (
                await img_element.get_attribute("title") if img_element else ""
            )  # title attribute ของ img

            # ดึงข้อมูล title และ price จาก center
            center_element = await tour.query_selector("center")

            # กำหนดค่าเริ่มต้นสำหรับข้อมูลที่จะดึงในส่วนนี้
            actual_title = ""
            title_link_from_h4a = ""
            title_attr_from_h4a = ""  # title attribute จาก <a> ใน h4
            price_display = ""

            if center_element:
                # --- ดึง Title ---
                title_h4 = await center_element.query_selector(
                    "h4.h-text2"
                )  # h4 แรกที่มี class h-text2
                if title_h4:
                    title_a_in_h4 = await title_h4.query_selector("a")
                    if title_a_in_h4:
                        # พยายามดึง inner_text จาก <a>
                        text_from_a = await title_a_in_h4.inner_text()
                        text_from_a = text_from_a.strip() if text_from_a else ""

                        title_link_from_h4a = (
                            await title_a_in_h4.get_attribute("href") or ""
                        )
                        title_attr_from_h4a = (
                            await title_a_in_h4.get_attribute("title") or ""
                        )

                        if text_from_a:  # ถ้า inner_text ของ <a> มีค่า ให้ใช้ค่านั้น
                            actual_title = text_from_a
                        else:  # ถ้า inner_text ของ <a> ว่าง ให้ใช้ title attribute ของ <a> แทน
                            actual_title = title_attr_from_h4a
                    else:
                        # ถ้าไม่มี <a> ใน h4 ให้ใช้ inner_text ของ h4 โดยตรง
                        h4_direct_text = await title_h4.inner_text()
                        actual_title = h4_direct_text.strip() if h4_direct_text else ""

                # --- ดึง Price ---
                price_h4 = await center_element.query_selector("h4.h-text2.red")
                if price_h4:
                    # ใช้ text_content() เพื่อความแม่นยำในการดึงข้อความที่มี elements ซ้อนกัน
                    full_price_text = await price_h4.text_content()
                    if full_price_text:
                        cleaned_price_text = full_price_text.strip()
                        # ลบคำว่า "ราคา" (ถ้ามี) และตัดช่องว่างอีกครั้ง
                        price_display = cleaned_price_text.replace("ราคา", "").strip()
                        # ตัวอย่างการใช้ regex เพื่อดึงเฉพาะตัวเลข (ถ้าต้องการ)
                        # match = re.search(r'([\d,]+)', price_display)
                        # if match:
                        #     price_display = match.group(1)
                    # else price_display remains ""

            # เก็บข้อมูลทัวร์
            tour_data = {
                "type": "type2",
                "title": actual_title,
                "price": price_display,
                "link": link_from_img,
                "title_link": title_link_from_h4a,
                "image_url": img_src,
                "image_alt": img_alt,
                "image_title": img_title_attr,
            }
            self.tours_data.append(tour_data)

            print(
                f"[แบบ2] ชื่อ: {actual_title}\n"
                f"ชื่อ (title attr ของลิงก์ชื่อเรื่อง): {title_attr_from_h4a}\n"
                f"ราคา: {price_display}\n"
                f"ลิงก์ (รูป): {link_from_img}\n"
                f"ลิงก์ (ชื่อเรื่อง): {title_link_from_h4a}\n"
                f"รูป (src): {img_src}\n"
                f"รูป (alt): {img_alt}\n"
                f"รูป (title attr ของรูป): {img_title_attr}\n---"
            )

    def export_to_csv(self, filename=None):
        """
        Export ข้อมูลทัวร์เป็นไฟล์ CSV
        """
        if not filename:
            # สร้างชื่อไฟล์จากวันที่และเวลา
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"phuket_tours_{timestamp}.csv"

        # กำหนด fieldnames สำหรับ CSV
        fieldnames = [
            "type",
            "title",
            "description",
            "details",
            "price",
            "link",
            "title_link",
            "image_url",
            "image_alt",
            "image_title",
            "ribbon",
        ]

        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for tour in self.tours_data:
                    # เติมค่า default สำหรับ field ที่ไม่มีในข้อมูล
                    row = {field: "" for field in fieldnames}
                    row.update(tour)
                    writer.writerow(row)
            print(f"บันทึกข้อมูลลงไฟล์ {filename} สำเร็จ")
            return filename
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการบันทึกไฟล์ CSV: {e}")
            return None

    async def close(self):
        """
        ปิด Browser และปิด Playwright
        """
        if self.browser:
            await self.browser.close()
            print("ปิด Browser สำเร็จ")


async def main():
    scraper = PhuketTour(headless=False)
    try:
        await scraper.setup_browser()
        
        # ดึงข้อมูลทัวร์ภูเก็ต
        print("\n=== เริ่มดึงข้อมูลทัวร์ภูเก็ต ===")
        await scraper.click_tour_button()
        
        # ดึงข้อมูลทัวร์พังงา
        print("\n=== เริ่มดึงข้อมูลทัวร์พังงา ===")
        await scraper.click_phangnga_tour_button()
        
        # ดึงข้อมูลทัวร์กระบี่
        print("\n=== เริ่มดึงข้อมูลทัวร์กระบี่ ===")
        await scraper.click_krabi_tour_button()
        
        # Export ข้อมูลเป็น CSV
        csv_file = scraper.export_to_csv()
        if csv_file:
            print(f"ข้อมูลถูกบันทึกลงในไฟล์: {csv_file}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await scraper.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
