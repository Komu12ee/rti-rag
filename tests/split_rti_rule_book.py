"""
Split rti-rule-book.pdf into individual legal documents using the printed-page
ranges in its contents/index pages.

Install:
    pip install pypdf

Run:
    python split_rti_by_index.py

Edit INPUT_PDF if your PDF is stored elsewhere.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from pypdf import PdfReader, PdfWriter

# ---------------------------------------------------------------------
# INPUT / OUTPUT
# ---------------------------------------------------------------------
INPUT_PDF = Path(r"rti-rule-book.pdf")
OUTPUT_DIR = Path("rti_rule_book_split")

# In this PDF:
# printed page 1 of the RTI Act is PDF physical page 13.
# pypdf uses zero-based page indices, so printed page 1 == index 12.
FIRST_PRINTED_PAGE_PDF_INDEX = 12

# Set False only if you do not want the initial cover/messages/contents file.
EXPORT_FRONT_MATTER = True

# ---------------------------------------------------------------------
# (serial_no, safe_filename, descriptive_title, printed_start, printed_end)
#
# Ranges were transcribed from the Contents / Index pages of rti-rule-book.pdf.
# Some entries intentionally overlap because the index places several
# notifications or directions on the same printed page.
# ---------------------------------------------------------------------
ITEMS = [
    (1,  "right_to_information_act_2005", "Right to Information Act, 2005", 1, 48),
    (2,  "rti_terms_of_office_rules_2019", "RTI Terms of Office, Salaries and Allowances Rules, 2019", 49, 56),

    (3,  "cg_state_information_commission_constitution", "Notification: Constitution of Chhattisgarh State Information Commission", 57, 58),
    (4,  "cg_rti_application_submission_rules_2009", "Chhattisgarh RTI (Application Submission) Rules, 2009", 59, 60),
    (5,  "application_submission_rules_notification_2009", "Notification: RTI Application Submission Rules, 2009", 61, 64),
    (6,  "transfer_of_rti_application_between_public_authorities", "Disposal of RTI applications involving another public authority", 65, 65),
    (7,  "guidelines_for_designated_cpio", "Guidelines for officers designated as Central Public Information Officers", 65, 65),
    (8,  "clarification_on_meaning_of_information", "Clarification: meaning of information under RTI Act", 66, 67),

    (9,  "cg_rti_appeal_rules_2006", "Chhattisgarh RTI (Appeal) Rules, 2006", 68, 76),
    (10, "appeal_rules_amendment_23_may_2006", "Amendment: RTI Appeal Rules, 2006 (23 May 2006)", 76, 77),
    (11, "appeal_rules_amendment_04_nov_2011", "Amendment: RTI Appeal Rules, 2006 (04 November 2011)", 78, 79),
    (12, "first_appeal_disposal_procedure_2006", "Procedure for disposal of First Appeal cases (20 December 2006)", 80, 84),
    (13, "first_appeal_time_limit_2007", "Disposal of First Appeals within time limit (20 July 2007)", 85, 85),
    (14, "request_disposal_and_appeal_hearing_2010", "Disposal of requests and hearing of appeals within prescribed time (22 December 2010)", 85, 87),
    (15, "first_appeal_disposal_time_limit_2013", "First Appeal disposal within time limit (29 April 2013)", 88, 88),
    (16, "faa_procedure_and_appeal_disposal_2014", "Procedure by First Appellate Authority and appeal disposal (31 October 2014)", 88, 90),
    (17, "pio_faa_information_supply_and_first_appeal_2015", "Directions for PIO/FAA on supply of information and First Appeal disposal (17 April 2015)", 90, 92),
    (18, "pio_reply_and_first_appeal_order_instructions", "Instructions for PIO reply and First Appeal order", 92, 92),
    (19, "appeal_guidance_12_april_2006", "Guidance regarding appeal matters (12 April 2006)", 93, 93),

    (20, "display_names_and_designations_of_officers_2006", "Display of names and designations of appointed officers (13 April 2006)", 94, 94),
    (21, "appeal_form_must_show_pio_faa_details_2011", "Appeal form: mention PIO/FAA name, designation and address (30 December 2011)", 94, 95),
    (22, "pio_faa_details_in_reply_and_order_2015", "Mention PIO/FAA name and designation in reply and orders (11 August 2015)", 95, 96),
    (23, "display_board_of_rti_officers", "Display board of appointed RTI officers", 96, 96),

    (24, "cg_rti_fee_and_value_rules_2005", "Chhattisgarh Gazette: RTI Fees and Value Regulation Rules, 2005", 97, 98),
    (25, "fee_rules_non_judicial_stamp_amendment_2021", "Rule 3 amendment: non-judicial stamp / e-stamp (06 January 2021)", 99, 99),
    (26, "fee_value_regulation_rules_amendment_2006", "Notification: amendment to Fees and Value Regulation Rules, 2005", 100, 100),
    (27, "fee_rules_english_translation_amendment_2006", "Amendment: English translation of Fees and Value Regulation Rules, 2005", 100, 100),
    (28, "cg_rti_fee_value_regulation_rules_2005_amendment", "Amendment to Chhattisgarh RTI Fees and Value Regulation Rules, 2005", 101, 101),
    (29, "cg_rti_fee_and_charge_rules_2007_notification", "Notification: Chhattisgarh RTI Fees and Charges Rules, 2007", 102, 103),
    (30, "fee_and_charge_rules_amendment_2013", "Notification: amendment to Fees and Charges Rules (14 November 2013)", 104, 104),
    (31, "deletion_of_rule_4_fee_and_charge_rules_2013", "Deletion of Rule 4 of Chhattisgarh RTI Fees and Charges Rules, 2007", 104, 104),
    (32, "fees_and_charge_rules_2007_english", "Fees and Charge Rules, 2007 (12 October 2006)", 105, 105),
    (33, "amendment_rules_2006_fee_and_charge_2008", "Notification: Amendment Rules, 2006 (Fees and Charges, 10 July 2008)", 106, 106),
    (34, "fee_clarification_13_september_2007", "Clarification regarding fee (13 September 2007)", 107, 107),
    (35, "rti_fee_payment_by_indian_postal_order_2011", "Payment of RTI fee through Indian Postal Order (07 June 2011)", 107, 107),
    (36, "rti_fee_payment_by_indian_postal_order_2012", "Payment of RTI fee through Indian Postal Order (26 April 2012)", 108, 108),
    (37, "use_of_electronic_indian_postal_order_2014", "Use of Electronic Indian Postal Order (e-IPO) (22 October 2014)", 109, 109),
    (38, "e_ipi_electronic_indian_postal_order_launched", "e-IPI / Electronic Indian Postal Order was launched (12 August 2014)", 109, 109),
    (39, "electronic_indian_postal_order_launch_2013", "Electronic Indian Postal Order: launching of (22 March 2013)", 110, 110),
    (40, "electronic_indian_postal_order_extension_2014", "Electronic Indian Postal Order: extension to Indian citizens residing in India (15 February 2014)", 111, 111),

    (41, "section_7_3_fee_payment_scope_2010", "Fee payment under Section 7(3): scope (24 May 2010)", 112, 113),
    (42, "section_7_3_a_direction_2014", "Direction concerning Section 7(3)(a) (21 August 2014)", 114, 114),

    (43, "exemption_from_rti_provisions", "Exemption from provisions of the Act", 114, 115),
    (44, "clarification_on_exemption_from_rti_provisions_2022", "Clarification on exemption from provisions of RTI Act (16 June 2022)", 115, 116),

    (45, "effective_implementation_instruction_2006", "Instruction for effective implementation of the Act (25 March 2006)", 116, 117),
    (46, "effective_implementation_instruction_2011", "Effective implementation of the Act (19 August 2011)", 117, 118),
    (47, "strengthening_rti_implementation_2011", "Strengthening Implementation of the RTI Act, 2005 (18 May 2011)", 118, 119),
    (48, "proper_implementation_of_rti_provisions_2013", "Proper implementation of provisions of the Act (14 November 2013)", 119, 121),

    (49, "government_of_india_rti_manual_updated", "Updated Government of India RTI Manual / Guide", 121, 145),

    (50, "departmental_information_proactive_disclosure_2011", "Departmental information: proactive disclosure on the internet (18 November 2011)", 146, 146),
    (51, "section_4_suo_motu_disclosure_2015", "Proactive disclosure under Section 4 (14 August 2015)", 146, 147),
    (52, "implementation_suo_motu_disclosure_section_4_2015", "Implementation of Suo Motu Disclosure under Section 4 of RTI Act, 2005 (29 June 2015)", 147, 147),

    (53, "government_instructions_on_rti_act_preparation_2006", "Government instructions concerning preparation under RTI Act (16 September 2006)", 148, 148),
    (54, "section_19_8_a_records_availability_2014", "Section 19(8)(a): ensuring availability of records (11 February 2014)", 149, 149),

    (55, "sic_annual_report_recommendations_action_2010", "Action on recommendations sent by Chhattisgarh SIC under Section 25(3) (27 September 2010)", 149, 150),

    (56, "cg_sic_annual_report_2011_action", "Action on Chhattisgarh State Information Commission Annual Report, 2011", 150, 155),
    (57, "appointment_of_public_authority_officers_2005", "Appointment of officers under the Act (21 November 2005)", 155, 155),
    (58, "appointment_of_public_authority_2013", "Appointment of public authority under the Act (14 August 2013)", 156, 156),

    (59, "dr_celsa_pinto_vs_goa_state_information_commission", "Bombay High Court at Goa: Dr. Celsa Pinto v. Goa State Information Commission", 157, 157),
    (60, "bombay_high_court_goa_decision_3_april_2008", "Bombay High Court at Goa decision dated 03 April 2008", 157, 158),
    (61, "high_court_observations_sections_2_and_3", "High Court observations concerning Sections 2 and 3", 158, 158),
    (62, "supreme_court_cbse_vs_aditya_bandopadhyay", "Supreme Court: CBSE v. Aditya Bandopadhyay", 159, 161),
    (63, "disclosure_of_personal_information_under_rti", "Disclosure of personal information under the RTI Act", 161, 161),
    (64, "submissions_of_respondent_and_third_party", "Submissions of respondent and third party", 162, 163),

    (65, "maintenance_of_register_under_rti_2005", "Maintenance of register under the Act (25 October 2005)", 164, 164),
    (66, "review_of_rti_implementation_progress_2005", "Review of progress of RTI Act implementation (07 November 2005)", 165, 165),
    (67, "confidential_character_roll_entries_2013", "Entries in confidential character rolls of government servants (14 August 2013)", 165, 166),
    (68, "validity_of_ration_card_2011", "Validity of ration card (27 June 2011)", 166, 167),
    (69, "cg_government_circular_416_th_668_2011", "Chhattisgarh Government Circular No. 416/TH-668/2011/1-13", 167, 168),
    (70, "proper_implementation_rti_act_2022", "Proper implementation of provisions of RTI Act (10 May 2022)", 168, 170),
    (71, "section_4_1_b_departmental_information_upload_2020", "Section 4(1)(b): upload departmental information on website (13 March 2020)", 171, 171),
    (72, "section_7_8_reason_for_rejection_2019", "Section 7(8): communicate reasons for rejection (18 July 2019)", 171, 172),
    (73, "money_order_fee_deposit_2021", "Deposit of RTI fee received by money order (16 July 2021)", 172, 172),
    (74, "chief_information_commissioner_chairmanship_meeting_2018", "Meeting chaired by Chief Information Commissioner, Chhattisgarh SIC (08 October 2018)", 172, 174),
    (75, "postal_order_rti_fee_2019", "RTI fee paid through Postal Order (26 September 2019)", 174, 175),
    (76, "information_requested_under_rti_2024", "Information requested under RTI Act (09 July 2024)", 175, 175),
    (77, "supply_information_under_rti_2024", "Supply of information under RTI Act (09 July 2024)", 175, 176),

    (78, "important_guidelines_for_pios_and_faas", "Important guidelines for Public Information Officers and First Appellate Authorities", 177, 179),
    (79, "form_1_rti_application", "Form 1: RTI Application Form", 180, 180),
    (80, "form_2_first_appeal_application", "Form 2: First Appeal Application Form", 181, 182),
    (81, "form_3_second_appeal_application", "Form 3: Second Appeal Application to Chhattisgarh SIC", 183, 185),
]


def safe_name(value: str) -> str:
    """Keep filenames safe on Windows, Linux and macOS."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("_")


def printed_page_to_pdf_index(printed_page: int) -> int:
    """Convert printed book page to zero-based page index in this PDF."""
    return FIRST_PRINTED_PAGE_PDF_INDEX + (printed_page - 1)


def write_pdf(reader: PdfReader, start_idx: int, end_idx: int, destination: Path) -> None:
    writer = PdfWriter()
    for page_idx in range(start_idx, end_idx + 1):
        writer.add_page(reader.pages[page_idx])
    with destination.open("wb") as out_file:
        writer.write(out_file)


def main() -> None:
    if not INPUT_PDF.exists():
        raise FileNotFoundError(
            f"Cannot find: {INPUT_PDF.resolve()}\n"
            "Put this script in the same folder as rti-rule-book.pdf, "
            "or change INPUT_PDF at the top of the script."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(INPUT_PDF))
    total_pages = len(reader.pages)

    manifest_rows = []

    # Export cover, messages and contents pages separately.
    if EXPORT_FRONT_MATTER:
        front_path = OUTPUT_DIR / "00_front_matter_cover_messages_contents.pdf"
        write_pdf(reader, 0, FIRST_PRINTED_PAGE_PDF_INDEX - 1, front_path)
        manifest_rows.append({
            "serial_no": "00",
            "title": "Front matter: cover, messages and contents",
            "printed_page_start": "",
            "printed_page_end": "",
            "pdf_page_start": 1,
            "pdf_page_end": FIRST_PRINTED_PAGE_PDF_INDEX,
            "file_name": front_path.name,
        })

    for serial_no, slug, title, printed_start, printed_end in ITEMS:
        start_idx = printed_page_to_pdf_index(printed_start)
        end_idx = printed_page_to_pdf_index(printed_end)

        if start_idx < 0 or end_idx >= total_pages:
            print(
                f"SKIPPED {serial_no:02d}: {title} | "
                f"requested PDF pages {start_idx + 1}-{end_idx + 1}, "
                f"but PDF has only {total_pages} pages."
            )
            continue

        filename = f"{serial_no:02d}_{safe_name(slug)}_printed_{printed_start:03d}-{printed_end:03d}.pdf"
        destination = OUTPUT_DIR / filename

        write_pdf(reader, start_idx, end_idx, destination)

        manifest_rows.append({
            "serial_no": serial_no,
            "title": title,
            "printed_page_start": printed_start,
            "printed_page_end": printed_end,
            "pdf_page_start": start_idx + 1,  # human-readable, 1-based
            "pdf_page_end": end_idx + 1,
            "file_name": filename,
        })

        print(
            f"[{serial_no:02d}] {title}\n"
            f"     printed pages {printed_start}-{printed_end} | "
            f"PDF pages {start_idx + 1}-{end_idx + 1}\n"
            f"     -> {destination}"
        )

    manifest_path = OUTPUT_DIR / "split_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        fieldnames = [
            "serial_no",
            "title",
            "printed_page_start",
            "printed_page_end",
            "pdf_page_start",
            "pdf_page_end",
            "file_name",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\nDone. Created files in: {OUTPUT_DIR.resolve()}")
    print(f"Manifest: {manifest_path.resolve()}")


if __name__ == "__main__":
    main()
