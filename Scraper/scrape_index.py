"""
STAGE 1: Discovery - Scrape the Chhattisgarh GAD Department document listing
Uses Selenium to handle ASP.NET pagination (pages 2-8 require real browser)
Saves to output/index.json
"""

import json
import time
import re
from pathlib import Path
from bs4 import BeautifulSoup

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "https://gad.cg.gov.in"
LISTING_URL = f"{BASE_URL}/document_view_categorywise.aspx?category=6Hrvp8Kw32Apdcbe7MlPlg=="
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "index.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DELAY_BETWEEN_PAGES = 2  # seconds between page clicks
MAX_RECORDS = 30         # set to None to scrape all records

# ── Utility Functions ─────────────────────────────────────────────────────────
def sanitize_filename(title: str, date: str = None, serial: str = None) -> str:
    prefix = serial.replace('/', '_').strip() if serial else ""

    if date:
        try:
            if '/' in date:
                parts = date.split('/')
                if len(parts) == 3:
                    d, m, y = parts
                    date_str = f"{y}-{m:0>2}-{d:0>2}"
                else:
                    date_str = date.replace('/', '-')
            else:
                date_str = date
        except:
            date_str = date.replace('/', '-')

        filename = f"{prefix}_{date_str}.pdf" if prefix else f"{date_str}.pdf"
    else:
        filename = f"{prefix}.pdf" if prefix else "document.pdf"

    filename = re.sub(r'[<>:"|?*]', '', filename)
    filename = re.sub(r'\s+', '_', filename)
    return filename.strip('_')


def resolve_url(href: str) -> str:
    if href.startswith('http://') or href.startswith('https://'):
        return href
    if href.startswith('/'):
        return f"{BASE_URL}{href}"
    return f"{BASE_URL}/{href}"


def extract_records_from_html(html: str, serial_offset: int = 0) -> list:
    """Parse records from page HTML using BeautifulSoup."""
    records = []
    soup = BeautifulSoup(html, 'lxml')

    download_links = soup.find_all('a', id=re.compile(r'hl_download'))

    if not download_links:
        print("  ⚠️  No download links found on this page")
        return records

    for idx, link in enumerate(download_links, start=1):
        try:
            href = link.get('href', '')
            if not href:
                continue

            pdf_url = resolve_url(href)
            title = link.get_text(strip=True)

            row = link.find_parent('tr')
            cells = row.find_all('td') if row else []

            year = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            date = cells[2].get_text(strip=True) if len(cells) > 2 else ""

            serial = str(serial_offset + idx)
            filename = sanitize_filename(title, date, serial)

            record = {
                'serial': serial,
                'title': title,
                'year': year,
                'date': date,
                'pdf_url': pdf_url,
                'filename': filename
            }

            records.append(record)
            print(f"  ✓ Record {serial}: {title[:60]} | {year} | {date}")

        except Exception as e:
            print(f"  ❌ Error parsing record {idx}: {e}")
            continue

    return records


def scrape_with_selenium() -> list:
    """
    Use Selenium (real Chrome browser) to scrape all pages including
    ASP.NET postback pagination.
    """
    all_records = []

    # Chrome options — runs visibly so you can see it working
    options = Options()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    print("Starting Chrome browser...")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    try:
        print(f"Opening: {LISTING_URL}\n")
        driver.get(LISTING_URL)
        time.sleep(3)  # Let page fully load

        page_num = 1

        while True:
            print(f"Scraping page {page_num}...")

            # Get current page HTML and extract records
            html = driver.page_source
            records = extract_records_from_html(html, serial_offset=len(all_records))
            all_records.extend(records)

            # Stop if we have reached the record limit
            if MAX_RECORDS and len(all_records) >= MAX_RECORDS:
                all_records = all_records[:MAX_RECORDS]
                print(f"  ✅ Reached 30 record limit — stopping.")
                break

            print(f"  ✅ Page {page_num}: {len(records)} records (total: {len(all_records)})\n")

            # Look for next page link in pagination
            # Pagination row has class cssPager; find links that are NOT current page (bold/span)
            try:
                soup = BeautifulSoup(html, 'lxml')
                pager_row = soup.find('tr', {'class': 'cssPager'})

                if not pager_row:
                    print("No more pages found.")
                    break

                # Find all page links (not spans — spans are the current page)
                page_links = pager_row.find_all('a', href=True)

                # Find link for next page number
                next_page_num = page_num + 1
                next_link = None
                for link in page_links:
                    if link.get_text(strip=True) == str(next_page_num):
                        next_link = link
                        break

                if not next_link:
                    print(f"No link found for page {next_page_num} — all pages done.")
                    break

                # Click the page number link in the real browser
                print(f"Clicking page {next_page_num}...")
                page_elements = driver.find_elements(
                    By.XPATH,
                    f"//tr[contains(@class,'cssPager')]//a[text()='{next_page_num}']"
                )

                if not page_elements:
                    print(f"Could not find clickable link for page {next_page_num}")
                    break

                page_elements[0].click()
                time.sleep(DELAY_BETWEEN_PAGES)  # Wait for postback to complete
                page_num += 1

            except Exception as e:
                print(f"  ❌ Pagination error on page {page_num}: {e}")
                break

    finally:
        driver.quit()
        print("Browser closed.")

    return all_records


def save_index(records: list):
    output_data = {
        'total_records': len(records),
        'records': records
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Index saved to {OUTPUT_FILE}")
    print(f"   Total records: {len(records)}")


def main():
    print("\n" + "="*80)
    print("STAGE 1: DISCOVERY - Scrape GAD Chhattisgarh Document Listing")
    print("="*80 + "\n")

    if not HAS_SELENIUM:
        print("❌ Selenium not installed. Run:")
        print("   pip install selenium")
        print("   Chrome browser must also be installed.")
        exit(1)

    print(f"Source URL: {LISTING_URL}")
    print(f"Output file: {OUTPUT_FILE}\n")
    print("NOTE: A Chrome browser window will open — do not close it.\n")

    all_records = scrape_with_selenium()

    print("\n" + "="*80)
    print("SCRAPING SUMMARY")
    print("="*80)
    print(f"Total records found: {len(all_records)}")

    if all_records:
        save_index(all_records)
    else:
        print("⚠️  No records found!")

    print("\nNext step: python download_pdfs.py")


if __name__ == '__main__':
    main()
