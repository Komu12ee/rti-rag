"""
STAGE 1: Discovery - Scrape the Chhattisgarh Finance Department circular listing
Fetches all pages and extracts metadata (serial, title, date, pdf_url)
Saves to output/index.json
"""

import requests
import json
import time
from pathlib import Path
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning
from tqdm import tqdm
import re

# Suppress InsecureRequestWarning for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "https://finance.cg.gov.in"
LISTING_URL = f"{BASE_URL}/vitt_nirdesh/subject.asp?subject=1"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "index.json"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Request configuration
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
REQUEST_TIMEOUT = 10
DELAY_BETWEEN_REQUESTS = 1

# ── Utility Functions ─────────────────────────────────────────────────────────
def sanitize_filename(title: str, date: str = None, serial: str = None) -> str:
    """
    Sanitize a filename from title and optional date/serial.
    Format: SERIAL_DATE.pdf or SERIAL.pdf
    """
    # Use serial as prefix if available
    prefix = serial.replace('/', '_').strip() if serial else ""
    
    if date:
        # Try to parse and format date as YYYY-MM-DD
        try:
            # Try dd/mm/yyyy format
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
        
        if prefix:
            filename = f"{prefix}_{date_str}.pdf"
        else:
            filename = f"{date_str}.pdf"
    else:
        filename = f"{prefix}.pdf" if prefix else "document.pdf"
    
    # Remove problematic characters
    filename = re.sub(r'[<>:"|?*]', '', filename)
    filename = re.sub(r'\s+', '_', filename)
    
    return filename.strip('_')


def resolve_url(url: str) -> str:
    """
    Resolve relative URLs to absolute URLs.
    """
    if url.startswith('http://') or url.startswith('https://'):
        return url
    if url.startswith('/'):
        return f"{BASE_URL}{url}"
    # Relative URL - resolve from base
    return f"{BASE_URL}/vitt_nirdesh/{url}"


def fetch_page(url: str, page_num: int = 1) -> tuple[BeautifulSoup | None, int]:
    """
    Fetch a single page and return parsed HTML.
    Returns (soup, status_code) or (None, status_code) on error.
    """
    try:
        print(f"Fetching page {page_num}: {url}")
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False  # SSL verification disabled for self-signed certs
        )
        response.raise_for_status()
        
        # Detect and set encoding
        if response.encoding is None or response.encoding.lower() == 'utf-8':
            # Try to detect from meta tags
            if 'charset' in response.headers.get('content-type', ''):
                pass  # requests already handled it
        
        soup = BeautifulSoup(response.content, 'lxml')
        return soup, response.status_code
    
    except requests.RequestException as e:
        print(f"  ❌ Error fetching page {page_num}: {e}")
        return None, None


def extract_records(soup: BeautifulSoup) -> list[dict]:
    """
    Extract records from a page.
    Expects a table with columns: Serial, Title, Date, PDF Link
    """
    records = []
    
    if soup is None:
        return records
    
    # Try to find the main table
    table = soup.find('table', {'class': ['table', 'content-table']}) or soup.find('table')
    
    if not table:
        print("  ⚠️  No table found on page")
        return records
    
    rows = table.find_all('tr')
    print(f"  Found {len(rows)} rows in table")
    
    # Skip header row (if it exists)
    start_idx = 1 if len(rows) > 0 and rows[0].find('th') else 0
    
    for idx, row in enumerate(rows[start_idx:], start=1):
        cells = row.find_all(['td', 'th'])
        
        if len(cells) < 3:
            continue
        
        try:
            # Extract basic info
            serial = cells[0].get_text(strip=True) if len(cells) > 0 else ""
            title = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            date = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            
            # Look for PDF link in any cell
            pdf_url = None
            pdf_link = None
            
            # Check all cells for links
            for cell in cells:
                link = cell.find('a', href=True)
                if link:
                    href = link.get('href', '')
                    if href.lower().endswith('.pdf') or 'pdf' in href.lower():
                        pdf_link = link
                        pdf_url = resolve_url(href)
                        break
            
            # If no direct PDF link, check for download icons or specific patterns
            if not pdf_url:
                link = row.find('a', href=True)
                if link:
                    href = link.get('href', '')
                    if href and 'subject' not in href.lower():  # Avoid navigation links
                        pdf_url = resolve_url(href)
            
            if not pdf_url:
                print(f"  ⚠️  Row {idx}: No PDF link found for '{title[:40]}...'")
                continue
            
            # Sanitize filename
            filename = sanitize_filename(title, date, serial)
            
            record = {
                'serial': serial,
                'title': title,
                'date': date,
                'pdf_url': pdf_url,
                'filename': filename
            }
            
            records.append(record)
            print(f"  ✓ Record {idx}: {serial} | {title[:50]}... | {date}")
        
        except Exception as e:
            print(f"  ❌ Error parsing row {idx}: {e}")
            continue
    
    return records


def detect_pagination(soup: BeautifulSoup, current_url: str) -> list[str]:
    """
    Detect pagination links and return list of URLs to fetch.
    Looks for: Next button, page links, query parameters
    """
    next_urls = []
    
    if soup is None:
        return next_urls
    
    # Look for "Next" or "अगला" links
    next_link = soup.find('a', string=re.compile(r'Next|अगला|next', re.IGNORECASE))
    
    if next_link and next_link.get('href'):
        next_url = resolve_url(next_link['href'])
        next_urls.append(next_url)
        return next_urls
    
    # Look for page number links (pagination widget)
    pagination = soup.find('div', {'class': ['pagination', 'pager']})
    
    if pagination:
        page_links = pagination.find_all('a', href=True)
        for link in page_links:
            href = link.get('href', '')
            if href and 'page' in href.lower() or 'id' in href.lower():
                page_url = resolve_url(href)
                if page_url not in next_urls and page_url != current_url:
                    next_urls.append(page_url)
    
    return next_urls


def scrape_all_pages() -> list[dict]:
    """
    Scrape all pages of the listing and collect records.
    """
    all_records = []
    visited_urls = set()
    urls_to_visit = [LISTING_URL]
    page_num = 1
    
    while urls_to_visit:
        current_url = urls_to_visit.pop(0)
        
        if current_url in visited_urls:
            continue
        
        visited_urls.add(current_url)
        
        # Fetch page
        soup, status = fetch_page(current_url, page_num)
        
        if status != 200:
            print(f"  Skipping page {page_num} due to error")
            page_num += 1
            continue
        
        # Extract records
        records = extract_records(soup)
        all_records.extend(records)
        print(f"  ✅ Page {page_num}: {len(records)} records extracted (total: {len(all_records)})\n")
        
        # Detect next pages
        next_urls = detect_pagination(soup, current_url)
        for next_url in next_urls:
            if next_url not in visited_urls:
                urls_to_visit.append(next_url)
        
        # Polite delay
        time.sleep(DELAY_BETWEEN_REQUESTS)
        page_num += 1
    
    return all_records


def save_index(records: list[dict]):
    """
    Save index to JSON file.
    """
    output_data = {
        'total_records': len(records),
        'records': records
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Index saved to {OUTPUT_FILE}")
    print(f"   Total records: {len(records)}")


def main():
    """
    Main execution flow.
    """
    print("\n" + "="*80)
    print("STAGE 1: DISCOVERY - Scrape Chhattisgarh Finance Circular Listing")
    print("="*80 + "\n")
    
    print(f"Source URL: {LISTING_URL}")
    print(f"Output file: {OUTPUT_FILE}\n")
    
    # Scrape all pages
    all_records = scrape_all_pages()
    
    # Summary
    print("\n" + "="*80)
    print("SCRAPING SUMMARY")
    print("="*80)
    print(f"Total records found: {len(all_records)}")
    
    if all_records:
        # Save index
        save_index(all_records)
    else:
        print("⚠️  No records found!")
    
    print("\nNext step: python download_pdfs.py")


if __name__ == '__main__':
    main()
