"""
scanner.py — Government Tender Document Scanner
================================================
Usage:
    python scanner.py tender.pdf
    python scanner.py tender3.pdf
"""

import os
import sys
import json

import fitz          # PyMuPDF
import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv
import pytesseract

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# For scanned PDFs, OCR only this many pages.
# Indian government tenders always put the NIT header, EMD, cost and deadline
# in the first 3–5 pages — no need to OCR the entire document.
MAX_OCR_PAGES = 5

# Total characters sent to the LLM
LLM_TEXT_CHARS = 8000


# =========================================================
# STEP 1 — DOCUMENT IDENTIFIER
# =========================================================

class DocumentIdentifier:

    def identify(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.lower().rsplit(".", 1)[-1]

        if ext in ["jpg", "jpeg", "png", "tiff", "bmp", "webp"]:
            return {
                "file_type":   "image",
                "pdf_type":    None,
                "total_pages": 1,
                "text_pages":  0,
                "image_pages": 1,
                "ocr_required": True,
            }

        if ext != "pdf":
            raise ValueError(f"Unsupported file format: .{ext}")

        doc = fitz.open(file_path)
        total_pages = len(doc)
        text_pages = image_pages = 0

        for page in doc:
            text = page.get_text("text")
            if text and len(text.strip()) > 50:
                text_pages += 1
            else:
                image_pages += 1

        doc.close()

        if image_pages == total_pages:
            pdf_type, ocr_required = "SCANNED_PDF", True
        elif text_pages == total_pages:
            pdf_type, ocr_required = "TEXT_PDF", False
        else:
            pdf_type, ocr_required = "MIXED_PDF", True

        return {
            "file_type":   "pdf",
            "pdf_type":    pdf_type,
            "total_pages": total_pages,
            "text_pages":  text_pages,
            "image_pages": image_pages,
            "ocr_required": ocr_required,
        }


# =========================================================
# STEP 2 — UNIFIED TEXT EXTRACTION
# =========================================================

class UnifiedExtractor:
    """
    Extracts text from PDFs and images.

    KEY FIX — scanned PDFs:
      Previously every page was OCR'd. A 47-page scanned PDF took 10+ minutes.
      Now OCR is capped at MAX_OCR_PAGES (default 5). All critical tender
      metadata (NIT number, issuing authority, EMD, estimated cost, deadline)
      appears in the first 3–5 pages of any Indian government tender.
    """

    def extract(self, file_path: str, max_ocr_pages: int = MAX_OCR_PAGES) -> dict:
        ext = file_path.lower().rsplit(".", 1)[-1]
        if ext in ["jpg", "jpeg", "png", "tiff", "bmp", "webp"]:
            return self._extract_image(file_path)
        return self._extract_pdf(file_path, max_ocr_pages)

    # ── PDF ──────────────────────────────────────────────────────────────────

    def _extract_pdf(self, file_path: str, max_ocr_pages: int) -> dict:
        doc = fitz.open(file_path)
        full_text = ""
        tables    = []
        headings  = []
        ocr_count = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text").strip()

            if len(text) < 50:
                # Scanned page — OCR it, but respect the cap
                if ocr_count >= max_ocr_pages:
                    continue          # skip — not needed for metadata
                text = self._ocr_page(page)
                ocr_count += 1

            full_text += "\n" + text

            # Basic table detection
            for block in page.get_text("blocks"):
                block_text = block[4]
                if ("\t" in block_text or "  " in block_text) and \
                   len(block_text.split()) > 5:
                    tables.append(block_text.strip())

            # Heading detection (all-caps lines)
            for line in text.split("\n"):
                line = line.strip()
                if line.isupper() and len(line) > 5:
                    headings.append(line)

        doc.close()

        return {
            "raw_text": full_text.strip(),
            "tables":   tables,
            "headings": list(dict.fromkeys(headings)),   # dedup, keep order
        }

    # ── Image ─────────────────────────────────────────────────────────────────

    def _extract_image(self, file_path: str) -> dict:
        img  = Image.open(file_path).convert("RGB")
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        text = pytesseract.image_to_string(gray)
        return {"raw_text": text.strip(), "tables": [], "headings": []}

    # ── OCR one fitz page ────────────────────────────────────────────────────

    @staticmethod
    def _ocr_page(page) -> str:
        pix  = page.get_pixmap(dpi=300)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        return pytesseract.image_to_string(gray)


# =========================================================
# STEP 3a — DOCUMENT TYPE DETECTION (local, instant)
# =========================================================

def detect_document_type(text: str) -> str:
    """
    Classify the tender document so the LLM gets a type-appropriate prompt.
    Returns: "civil_works" | "procurement" | "spec_document" | "generic"
    """
    t = text[:10000].lower()

    civil_signals = [
        "schedule of tender", "amount of nit", "name of work",
        "place of work", "e-tender enquiry no", "contract cell",
        "commandant (engineer)", "notice inviting e-tender",
        "nit/estimated cost", "time allowed for completion",
        "e.m.d. (in inr)",
    ]
    procurement_signals = [
        "open tender enquiry", "proc-v", "directorate general, crpf",
        "description of articles", "delivery period",
        "performance security deposit", "schedule to tender no",
        "two bid system", "commercial bid",
    ]
    spec_signals = [
        "qrs/specifications", "test method", "specification/parameter",
        "fibre identification", "fabric weight", "colour fastness",
        "trial directives", "firing mode",
        "applicability- these specifications", "salient features",
        "colour fastness to rubbing",
    ]

    c = sum(1 for s in civil_signals       if s in t)
    p = sum(1 for s in procurement_signals if s in t)
    s = sum(1 for s in spec_signals        if s in t)

    # Pure spec doc: clear spec signals, no invitation signals
    if s >= 2 and c == 0 and p == 0:
        return "spec_document"

    mx = max(c, p, s)
    if mx == 0:
        return "generic"
    if c >= p and c == mx:
        return "civil_works"
    if p == mx:
        return "procurement"
    if s >= 2:
        return "spec_document"
    return "generic"


# =========================================================
# STEP 3b — LLM STRUCTURED EXTRACTION
# =========================================================

from groq import Groq


# ── JSON schemas per document type ───────────────────────────────────────────

_SCHEMAS = {
    "civil_works": """{
  "issuing_authority": "",
  "tender_reference":  "",
  "date_of_issue":     "",
  "submission_deadline": "",
  "opening_date":      "",
  "estimated_cost":    "",
  "emd_amount":        "",
  "work_name":         "",
  "location":          "",
  "completion_period": "",
  "eligibility":       []
}""",

    "procurement": """{
  "issuing_authority": "",
  "tender_reference":  "",
  "date_of_issue":     "",
  "submission_deadline": "",
  "opening_date":      "",
  "store_name":        "",
  "quantity":          "",
  "emd_amount":        "",
  "delivery_period":   "",
  "consignee":         "",
  "warranty":          "",
  "eligibility":       []
}""",

    "spec_document": """{
  "item_name":               "",
  "issuing_body":            "",
  "tender_reference":        "",
  "fibre_composition":       "",
  "fabric_weight":           "",
  "key_performance_specs":   {},
  "approved_brands":         [],
  "packaging":               {}
}""",

    "generic": """{
  "issuing_authority": "",
  "tender_reference":  "",
  "opening_date":      "",
  "submission_deadline": "",
  "budget":            "",
  "store_name":        "",
  "quantity":          "",
  "eligibility":       [],
  "materials_required": []
}""",
}

# ── System instructions per document type ────────────────────────────────────

_INSTRUCTIONS = {
    "civil_works": (
        "You are analysing a civil-works / NIT tender issued by an Indian "
        "government department. Extract the schedule-of-tender fields listed "
        "in the schema. Write null for any field not present — never guess."
    ),
    "procurement": (
        "You are analysing a goods/equipment procurement tender issued by a "
        "central government body (e.g. CRPF). Extract store name, quantity, "
        "EMD, delivery period and consignee. Write null for absent fields."
    ),
    "spec_document": (
        "You are analysing a technical specification / QR document for a "
        "government-procured item (garment, weapon, equipment, etc.). "
        "This is NOT a tender invitation — do NOT look for submission deadlines "
        "or budgets. Extract item specs, key performance parameters and "
        "approved brands. Write null for fields that are not in the document."
    ),
    "generic": (
        "You are analysing a government tender document. Extract all available "
        "fields from the schema. Write null for any field not found."
    ),
}


class LLMExtractor:

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not set. Add it to your .env file:\n"
                "  GROQ_API_KEY=gsk_..."
            )
        self.client = Groq(api_key=api_key)
        self.model  = "llama-3.1-8b-instant"

    def _build_text_window(self, text: str) -> str:
        """
        KEY FIX — smarter text window for the LLM.

        The old approach took the first 6000 chars. For a spec document that
        starts with a materials table, this gave the LLM zero context about
        what the item is, returning empty fields.

        New approach: head + middle sample + tail, totalling LLM_TEXT_CHARS.
        This covers:
          • The NIT / header block (always at the top)
          • The schedule-of-tender table (usually page 3, i.e. the middle)
          • Warranty / completion terms (sometimes at the end)
        """
        n = len(text)
        if n <= LLM_TEXT_CHARS:
            return text

        head   = text[:5000]
        mid_s  = max(5000, n // 2 - 750)
        middle = text[mid_s: mid_s + 1500]
        tail   = text[max(0, n - 1500):]
        return head + "\n[...]\n" + middle + "\n[...]\n" + tail

    def extract(self, document_text: str, doc_type: str = "generic") -> dict:
        schema      = _SCHEMAS[doc_type]
        instruction = _INSTRUCTIONS[doc_type]
        window      = self._build_text_window(document_text)

        system_msg = (
            instruction
            + "\nReturn STRICT JSON only — no markdown fences, no explanation."
        )
        user_msg = (
            f"Extract structured information from this tender document.\n\n"
            f"Required JSON schema:\n{schema}\n\n"
            f"Tender Document Text:\n"
            f"----------------\n{window}\n----------------"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(content)
        except Exception:
            return {"error": "Failed to parse LLM output", "raw_output": content}


# =========================================================
# STEP 4 — OUTPUT DISPLAY
# =========================================================

class JSONOutputFormatter:

    def display(self, structured_output):
        print("\n==============================")
        print("FINAL STRUCTURED OUTPUT")
        print("==============================\n")

        if not structured_output:
            print("No structured output generated.")
            return

        if isinstance(structured_output, dict):
            print(json.dumps(structured_output, indent=4, ensure_ascii=False))
        else:
            try:
                print(json.dumps(json.loads(structured_output), indent=4,
                                 ensure_ascii=False))
            except Exception:
                print("Could not parse JSON.\n", structured_output)


# =========================================================
# RUNNER HELPERS
# =========================================================

def run_step1(file_path: str) -> dict:
    identifier = DocumentIdentifier()
    doc_info   = identifier.identify(file_path)
    print("\n[STEP 1 RESULT]")
    print("Document Type:", doc_info)
    return doc_info


def run_step2(file_path: str) -> dict:
    extractor = UnifiedExtractor()
    data      = extractor.extract(file_path)
    print("\n[STEP 2 RESULT]")
    print(f"Extracted text length : {len(data['raw_text'])} chars")
    print(f"Tables detected       : {len(data['tables'])}")
    print(f"Headings detected     : {len(data['headings'])}")
    return data


def run_step3(text: str, doc_type: str = "generic") -> dict:
    extractor = LLMExtractor()
    result    = extractor.extract(text, doc_type)
    print("\n[STEP 3 RESULT — Structured Output]\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


# =========================================================
# MAIN
# =========================================================

def main(file_path: str):

    # Step 1 — identify document
    doc_info = run_step1(file_path)

    # Warn about OCR cap upfront so the user isn't confused
    if doc_info.get("pdf_type") == "SCANNED_PDF":
        print(
            f"\n[INFO] Scanned PDF — {doc_info['total_pages']} total pages. "
            f"OCR limited to first {MAX_OCR_PAGES} pages for speed. "
            "All key tender metadata appears in the opening pages."
        )

    # Step 2 — extract text
    extraction_data = run_step2(file_path)
    raw_text        = extraction_data["raw_text"]

    if not raw_text.strip():
        print("\n[ERROR] No text could be extracted from this document.")
        return

    # Step 3a — detect document type (local, instant, no API call)
    doc_type = detect_document_type(raw_text)
    print(f"\n[INFO] Document type detected: {doc_type}")

    # Step 3b — LLM structured extraction with type-aware prompt
    structured_output = run_step3(raw_text, doc_type)

    # Step 4 — display
    JSONOutputFormatter().display(structured_output)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scanner.py <file_path>")
        sys.exit(1)

    main(sys.argv[1])