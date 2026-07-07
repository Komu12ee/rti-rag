# Chhattisgarh Finance Department Circular Scraper

A Python pipeline to scrape, download, and enrich PDF circulars from the Chhattisgarh Finance Department website.

**Source:** https://finance.cg.gov.in/vitt_nirdesh/subject.asp?subject=1

## Overview

The scraper is organized in three stages:

### Stage 1: Discovery (`scrape_index.py`)
- Fetches the listing page(s) and detects pagination
- Extracts metadata: serial number, title (Hindi), date, PDF URL
- Saves an index to `output/index.json`
- Handles SSL self-signed certificates automatically

### Stage 2: Download (`download_pdfs.py`)
- Downloads all PDFs from the index
- Implements resume support (skips already downloaded files)
- Includes retry logic (up to 3 retries on connection errors)
- Polite delays between requests (1-2 seconds random)
- Logs all download attempts to `output/download_log.csv`

### Stage 3: Enrichment (`enrich_metadata.py`)
- Extracts PDF metadata for each downloaded file:
  - **Page count** (via PyPDF2)
  - **Language detection** (Hindi/English/Mixed via langdetect)
  - **File size** in KB
- Saves enriched records to `output/index_enriched.json`

## Installation

1. Install Python 3.8 or higher
2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run each stage in order:

```bash
# Stage 1: Discover and index circulars
python scrape_index.py

# Stage 2: Download PDFs (with resume support)
python download_pdfs.py

# Stage 3: Enrich metadata (optional)
python enrich_metadata.py
```

Each script can be run independently and is self-contained.

## Output Structure

```
output/
  index.json              # Original index with URLs and filenames
  index_enriched.json     # Enriched index with PDF metadata
  download_log.csv        # Download attempt log
  pdfs/
    001_2024-03-15.pdf
    002_2024-05-10.pdf
    ...
```

## Index Format

### index.json (Stage 1 output)
```json
{
  "total_records": 42,
  "records": [
    {
      "serial": "1",
      "title": "विषय शीर्षक...",
      "date": "15/03/2024",
      "pdf_url": "https://...",
      "filename": "001_2024-03-15.pdf"
    },
    ...
  ]
}
```

### download_log.csv (Stage 2 output)
```
serial,title,pdf_url,filename,status,error_message,file_size_kb,timestamp
1,विषय शीर्षक,https://...,001_2024-03-15.pdf,ok,,245.3,2024-05-15T10:30:45.123456
2,विषय शीर्षक,https://...,002_2024-05-10.pdf,ok,,180.5,2024-05-15T10:32:12.654321
```

### index_enriched.json (Stage 3 output)
```json
{
  "total_records": 42,
  "records": [
    {
      "serial": "1",
      "title": "विषय शीर्षक...",
      "date": "15/03/2024",
      "pdf_url": "https://...",
      "filename": "001_2024-03-15.pdf",
      "page_count": 12,
      "language": "hi",
      "file_size_kb": 245.3,
      "enriched": true
    },
    ...
  ]
}
```

## Features

- ✅ **SSL Support**: Handles self-signed certificates with `verify=False`
- ✅ **Pagination Detection**: Automatically detects and follows "Next" links
- ✅ **Resume Support**: Skip already downloaded files (resume from interruption)
- ✅ **Retry Logic**: Up to 3 retries on connection errors or server errors
- ✅ **Polite Scraping**: 1-2 second delays between requests
- ✅ **Unicode Support**: Handles Hindi text correctly (UTF-8 or Windows-1252)
- ✅ **Progress Bars**: Real-time progress with tqdm
- ✅ **Logging**: Comprehensive CSV logs of all download attempts
- ✅ **Metadata Extraction**: Page count, language detection, file size

## Configuration

Edit the `Configuration` section in each script to modify:
- `BASE_URL`: Base URL for URL resolution
- `OUTPUT_DIR`: Output directory for files and logs
- `HEADERS`: Custom User-Agent header
- `REQUEST_TIMEOUT`: Timeout for requests (seconds)
- `DELAY_MIN` / `DELAY_MAX`: Delay between requests (seconds)
- `MAX_RETRIES`: Maximum retry attempts

## Requirements

- `requests` - HTTP library for fetching pages
- `beautifulsoup4` - HTML parsing
- `lxml` - Fast HTML parser for BeautifulSoup
- `tqdm` - Progress bars
- `PyPDF2` - PDF page count extraction (optional)
- `langdetect` - Language detection (optional)

Optional dependencies can be omitted, but Stage 3 will have limited functionality.

## Troubleshooting

### SSL Certificate Verification Failed
The scripts automatically disable SSL verification. If you still get errors, ensure `verify=False` is set in the requests.

### No Records Found
1. Check if the website structure has changed
2. Inspect the page manually to identify the table structure
3. The scraper expects a `<table>` with rows containing serial, title, date, and PDF link

### Language Detection Not Working
Install `langdetect`: `pip install langdetect`

### Page Count Not Extracted
Install `PyPDF2`: `pip install PyPDF2`

## Notes

- The scraper respects server resources with polite delays between requests
- Encoding is automatically detected from response headers
- Hindi text is preserved as-is in the index files
- Downloaded PDFs are named using sanitized serial + date (SERIAL_YYYY-MM-DD.pdf)
- All timestamps are in ISO format

## License

Use responsibly and ensure you have permission to scrape the target website.
