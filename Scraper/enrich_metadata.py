"""
STAGE 3: Metadata Enrichment - Extract PDF metadata
Extracts page count, language detection, and file size
Saves enriched records to output/index_enriched.json
"""

import json
from pathlib import Path
from tqdm import tqdm
import os

# Try to import optional dependencies
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
    print("⚠️  PyPDF2 not installed - page count extraction will be skipped")
    print("   Install with: pip install PyPDF2\n")

try:
    from langdetect import detect, LangDetectException
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False
    print("⚠️  langdetect not installed - language detection will be skipped")
    print("   Install with: pip install langdetect\n")

# ── Configuration ─────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
INDEX_FILE = OUTPUT_DIR / "index.json"
ENRICHED_INDEX_FILE = OUTPUT_DIR / "index_enriched.json"
PDFS_DIR = OUTPUT_DIR / "pdfs"

# ── Utility Functions ─────────────────────────────────────────────────────────
def load_index() -> dict:
    """
    Load the original index from JSON file.
    """
    if not INDEX_FILE.exists():
        print(f"❌ Index file not found: {INDEX_FILE}")
        print("Please run scrape_index.py and download_pdfs.py first")
        exit(1)
    
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return data


def get_page_count(pdf_path: Path) -> int | None:
    """
    Extract page count from PDF.
    Returns None if extraction fails or PyPDF2 is not available.
    """
    if not HAS_PYPDF2:
        return None
    
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            return len(reader.pages)
    except Exception as e:
        return None


def detect_language(pdf_path: Path) -> str:
    """
    Detect language from PDF text (first 500 characters).
    Returns language code (hi, en, mixed, unknown).
    """
    if not HAS_LANGDETECT:
        return "unknown"
    
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            
            if not reader.pages:
                return "unknown"
            
            # Extract text from first page
            first_page = reader.pages[0]
            text = first_page.extract_text()[:500]
            
            if not text or len(text.strip()) < 10:
                return "unknown"
            
            # Detect language
            try:
                lang = detect(text)
                return lang
            except LangDetectException:
                return "unknown"
    
    except Exception as e:
        return "unknown"


def get_file_size_kb(pdf_path: Path) -> float:
    """
    Get file size in kilobytes.
    """
    try:
        return pdf_path.stat().st_size / 1024
    except:
        return 0


def enrich_records(records: list[dict]) -> list[dict]:
    """
    Enrich records with PDF metadata.
    """
    enriched = []
    
    with tqdm(total=len(records), desc="Enriching metadata", unit="file") as pbar:
        for record in records:
            filename = record.get('filename', '')
            pdf_path = PDFS_DIR / filename
            
            pbar.update(1)
            
            # Check if PDF exists
            if not pdf_path.exists():
                print(f"  ⚠️  PDF not found: {filename}")
                record['page_count'] = None
                record['language'] = "unknown"
                record['file_size_kb'] = 0
                record['enriched'] = False
                enriched.append(record)
                continue
            
            # Extract metadata
            page_count = get_page_count(pdf_path)
            language = detect_language(pdf_path)
            file_size_kb = get_file_size_kb(pdf_path)
            
            # Enrich record
            record['page_count'] = page_count
            record['language'] = language
            record['file_size_kb'] = round(file_size_kb, 2)
            record['enriched'] = True
            
            enriched.append(record)
            
            # Print summary
            info = f"{filename}"
            if page_count is not None:
                info += f" | {page_count} pages"
            if language != "unknown":
                info += f" | {language}"
            info += f" | {file_size_kb:.1f} KB"
            
            print(f"  ✓ {info}")
    
    return enriched


def save_enriched_index(records: list[dict]):
    """
    Save enriched index to JSON file.
    """
    output_data = {
        'total_records': len(records),
        'enriched_timestamp': Path.cwd().name,  # Just for reference
        'records': records
    }
    
    with open(ENRICHED_INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Enriched index saved to {ENRICHED_INDEX_FILE}")


def print_statistics(records: list[dict]):
    """
    Print enrichment statistics.
    """
    total = len(records)
    with_pages = sum(1 for r in records if r.get('page_count') is not None)
    with_language = sum(1 for r in records if r.get('language') != 'unknown')
    
    print("\nEnrichment Statistics:")
    print(f"  Total records: {total}")
    print(f"  With page count: {with_pages}")
    print(f"  With language detection: {with_language}")
    
    # Language breakdown
    languages = {}
    for record in records:
        lang = record.get('language', 'unknown')
        languages[lang] = languages.get(lang, 0) + 1
    
    if languages:
        print(f"\n  Language distribution:")
        for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
            print(f"    {lang}: {count}")
    
    # Page count statistics
    page_counts = [r.get('page_count') for r in records if r.get('page_count')]
    if page_counts:
        print(f"\n  Page count statistics:")
        print(f"    Min: {min(page_counts)}")
        print(f"    Max: {max(page_counts)}")
        print(f"    Avg: {sum(page_counts) / len(page_counts):.1f}")
    
    # File size statistics
    file_sizes = [r.get('file_size_kb', 0) for r in records]
    if file_sizes:
        total_size_mb = sum(file_sizes) / 1024
        print(f"\n  Total storage: {total_size_mb:.2f} MB")


def main():
    """
    Main execution flow.
    """
    print("\n" + "="*80)
    print("STAGE 3: ENRICHMENT - Extract PDF Metadata")
    print("="*80 + "\n")
    
    # Check dependencies
    if not HAS_PYPDF2 or not HAS_LANGDETECT:
        print("📋 Optional dependencies:")
        if not HAS_PYPDF2:
            print("  - PyPDF2 (for page count extraction)")
        if not HAS_LANGDETECT:
            print("  - langdetect (for language detection)")
        print()
    
    # Load index
    index = load_index()
    records = index.get('records', [])
    
    print(f"Loaded index with {len(records)} records")
    print(f"PDF directory: {PDFS_DIR}\n")
    
    # Check if PDFs have been downloaded
    pdf_files = list(PDFS_DIR.glob('*.pdf'))
    if not pdf_files:
        print("⚠️  No PDF files found in output/pdfs/")
        print("Please run download_pdfs.py first")
        exit(1)
    
    print(f"Found {len(pdf_files)} downloaded PDFs\n")
    
    # Enrich records
    enriched_records = enrich_records(records)
    
    # Save enriched index
    save_enriched_index(enriched_records)
    
    # Print statistics
    print_statistics(enriched_records)
    
    # Summary
    print("\n" + "="*80)
    print("ENRICHMENT COMPLETE")
    print("="*80)
    print(f"Enriched index: {ENRICHED_INDEX_FILE}")
    print(f"\n✅ Metadata enrichment pipeline completed!")


if __name__ == '__main__':
    main()
