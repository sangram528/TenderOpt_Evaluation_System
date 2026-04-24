import os
import re
import cv2
import json
import numpy as np
import pdfplumber
import pytesseract
from pathlib import Path
from typing import Dict, Any, List

class TenderScanner:
    def __init__(self):
        self.auth_keywords = ["Commandant", "DIGP", "Office of the", "Headquarters", "CRPF"]
        # Key headers we expect to see in a CRPF material table
        self.mat_headers = ["item", "description", "material", "specification", "qty", "quantity", "unit"]

    def extract_from_pdf(self, file_path: str) -> Dict[str, Any]:
        all_text = ""
        materials = []
        
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # 1. Extract Text for Metadata
                all_text += (page.extract_text() or "") + "\n"
                
                # 2. Extract Tables for Materials (This is the fix)
                tables = page.extract_tables()
                for table in tables:
                    # Clean the table: remove None values and empty strings
                    cleaned_table = [[str(cell).strip() for cell in row if cell] for row in table]
                    
                    # Check if this table looks like a material list
                    if any(any(h in str(cell).lower() for h in self.mat_headers) for row in cleaned_table for cell in row):
                        for row in cleaned_table:
                            # Skip header rows
                            if any(h in "".join(row).lower() for h in ["sl no", "part no", "s.no"]):
                                continue
                            
                            # Logic: If a row has a name and a number, it's likely a material
                            # We look for a string (item) and a digit (quantity)
                            nums = [item for item in row if re.search(r'\d+', item)]
                            text_items = [item for item in row if len(item) > 3 and not re.search(r'^\d+$', item)]
                            
                            if text_items and nums:
                                materials.append({
                                    "item": text_items[0],
                                    "quantity": nums[0],
                                    "details": " ".join(text_items[1:]) if len(text_items) > 1 else "N/A"
                                })

        return self.parse_essentials(all_text, materials)

    def parse_essentials(self, text: str, materials: List[Dict]) -> Dict[str, Any]:
        # Authority Extraction
        auth = next((line.strip() for line in text.split('\n')[:15] if any(k in line for k in self.auth_keywords)), "CRPF Authority")
        
        # Date & Time (Looking for 10/05/2026 or 10-05-2026 + optional Hrs)
        date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*([\d]{4}\s*Hrs)?', text, re.I)
        
        # Budget
        budget = re.search(r"(?:Estimated Cost|NIT|Value).*?(?:Rs\.?|₹)\s*([\d,]+\.?\d*)", text, re.I)

        return {
            "issuing_authority": auth,
            "opening_date": f"{date_match.group(1)} {date_match.group(2) or ''}".strip() if date_match else "Not Found",
            "budget": budget.group(1).replace(',', '') if budget else "0.00",
            "materials_required": materials  # No more summary!
        }

# ─────────────────────────────────────────────────────────────────
# EXECUTION
# ─────────────────────────────────────────────────────────────────

def run_scanner():
    import sys
    if len(sys.argv) < 2:
        print("[!] Error: Provide a file.")
        return

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"[!] Error: {file_path} not found.")
        return

    print(f"[*] Analyzing Documents...")
    
    try:
        scanner = TenderScanner()
        # Note: If image-based, you'd call a different OCR path, 
        # but for tender.pdf, pdfplumber's table logic is king.
        final_data = scanner.extract_from_pdf(file_path)

        print("\n" + json.dumps(final_data, indent=2))
        print("\n[*] Scan Complete.")

    except Exception as e:
        print(f"[!] Error: {str(e)}")

if __name__ == "__main__":
    run_scanner()