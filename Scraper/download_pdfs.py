"""
STAGE 2: Download - Fetch PDF files from the index
Implements resume support, retry logic, and polite delays
Logs all download attempts to output/download_log.csv
"""

import requests
import json
import csv
import time
import random
from pathlib import Path
from urllib3.exceptions import InsecureRequestWarning
from tqdm import tqdm
from datetime import datetime

# Suppress InsecureRequestWarning for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
INDEX_FILE = OUTPUT_DIR / "index.json"
PDFS_DIR = OUTPUT_DIR / "pdfs"
LOG_FILE = OUTPUT_DIR / "download_log.csv"

# Ensure output directories exist
PDFS_DIR.mkdir(parents=True, exist_ok=True)

# Request configuration
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
REQUEST_TIMEOUT = 15
DELAY_MIN = 1
DELAY_MAX = 2
MAX_RETRIES = 3

# ── Utility Functions ─────────────────────────────────────────────────────────
def load_index() -> dict:
    """
    Load the index from JSON file.
    """
    if not INDEX_FILE.exists():
        print(f"❌ Index file not found: {INDEX_FILE}")
        print("Please run scrape_index.py first")
        exit(1)
    
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return data


def initialize_log():
    """
    Initialize download log file with headers if it doesn't exist.
    """
    if LOG_FILE.exists():
        print(f"📝 Resuming downloads - appending to {LOG_FILE}\n")
        return
    
    with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'serial', 'title', 'pdf_url', 'filename', 
            'status', 'error_message', 'file_size_kb', 'timestamp'
        ])
    
    print(f"📝 Created download log: {LOG_FILE}\n")


def get_downloaded_files() -> set:
    """
    Get set of already downloaded filenames from log.
    """
    downloaded = set()
    
    if LOG_FILE.exists():
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('status') == 'ok':
                    downloaded.add(row.get('filename', ''))
    
    return downloaded


def log_download(serial: str, title: str, pdf_url: str, filename: str, 
                 status: str, error_msg: str = '', file_size_kb: float = 0):
    """
    Append a download attempt to the log file.
    """
    with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            serial, title, pdf_url, filename,
            status, error_msg, round(file_size_kb, 2),
            datetime.now().isoformat()
        ])


def download_pdf(pdf_url: str, output_path: Path, record: dict, 
                 retry_count: int = 0) -> tuple[bool, str]:
    """
    Download a single PDF file.
    Returns (success, error_message)
    """
    try:
        print(f"  Downloading: {pdf_url[:60]}...")
        
        response = requests.get(
            pdf_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False  # SSL verification disabled
        )
        
        if response.status_code == 200:
            # Write file
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            file_size_kb = output_path.stat().st_size / 1024
            print(f"    ✅ Downloaded ({file_size_kb:.1f} KB)")
            
            log_download(
                record['serial'], record['title'], pdf_url, 
                output_path.name, 'ok', '', file_size_kb
            )
            
            return True, ''
        
        else:
            error = f"HTTP {response.status_code}"
            print(f"    ❌ {error}")
            
            # Retry on server errors
            if response.status_code >= 500 and retry_count < MAX_RETRIES:
                print(f"    🔄 Retrying ({retry_count + 1}/{MAX_RETRIES})...")
                time.sleep(random.uniform(2, 4))
                return download_pdf(pdf_url, output_path, record, retry_count + 1)
            
            log_download(
                record['serial'], record['title'], pdf_url,
                output_path.name, 'failed', error
            )
            
            return False, error
    
    except requests.Timeout:
        error = "Request timeout"
        print(f"    ❌ {error}")
        
        if retry_count < MAX_RETRIES:
            print(f"    🔄 Retrying ({retry_count + 1}/{MAX_RETRIES})...")
            time.sleep(random.uniform(2, 4))
            return download_pdf(pdf_url, output_path, record, retry_count + 1)
        
        log_download(
            record['serial'], record['title'], pdf_url,
            output_path.name, 'failed', error
        )
        
        return False, error
    
    except requests.ConnectionError as e:
        error = f"Connection error: {str(e)[:50]}"
        print(f"    ❌ {error}")
        
        if retry_count < MAX_RETRIES:
            print(f"    🔄 Retrying ({retry_count + 1}/{MAX_RETRIES})...")
            time.sleep(random.uniform(2, 4))
            return download_pdf(pdf_url, output_path, record, retry_count + 1)
        
        log_download(
            record['serial'], record['title'], pdf_url,
            output_path.name, 'failed', error
        )
        
        return False, error
    
    except Exception as e:
        error = f"Unexpected error: {str(e)[:50]}"
        print(f"    ❌ {error}")
        
        log_download(
            record['serial'], record['title'], pdf_url,
            output_path.name, 'failed', error
        )
        
        return False, error


def main():
    """
    Main execution flow.
    """
    print("\n" + "="*80)
    print("STAGE 2: DOWNLOAD - Fetch PDFs from Circular Listing")
    print("="*80 + "\n")
    
    # Load index
    index = load_index()
    records = index.get('records', [])
    
    print(f"Loaded index with {len(records)} records")
    print(f"Output directory: {PDFS_DIR}\n")
    
    # Initialize log
    initialize_log()
    
    # Get already downloaded files for resume support
    already_downloaded = get_downloaded_files()
    
    if already_downloaded:
        print(f"📋 Already downloaded: {len(already_downloaded)} files\n")
    
    # Download PDFs
    successful = 0
    skipped = 0
    failed = 0
    
    with tqdm(total=len(records), desc="Downloading PDFs", unit="file") as pbar:
        for record in records:
            filename = record.get('filename', 'unknown.pdf')
            output_path = PDFS_DIR / filename
            
            pbar.update(1)
            
            # Skip already downloaded
            if filename in already_downloaded:
                print(f"⏭️  Skipping (already downloaded): {filename}")
                skipped += 1
                continue
            
            # Download
            success, error = download_pdf(record['pdf_url'], output_path, record)
            
            if success:
                successful += 1
            else:
                failed += 1
                # Clean up partial download
                if output_path.exists():
                    output_path.unlink()
            
            # Polite delay between requests
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    # Summary
    print("\n" + "="*80)
    print("DOWNLOAD SUMMARY")
    print("="*80)
    print(f"Successfully downloaded: {successful}")
    print(f"Skipped (already downloaded): {skipped}")
    print(f"Failed: {failed}")
    print(f"Total: {len(records)}")
    print(f"\nLog file: {LOG_FILE}")
    print(f"PDF directory: {PDFS_DIR}")
    
    if failed == 0 and successful + skipped == len(records):
        print("\n✅ All downloads completed successfully!")
    elif failed > 0:
        print(f"\n⚠️  {failed} download(s) failed - check log for details")
    
    print("\nNext step: python enrich_metadata.py")


if __name__ == '__main__':
    main()
