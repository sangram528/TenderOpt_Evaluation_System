"""
Document Scanner - CRPF Tender Evaluation
==========================================
Takes any document (PDF, scanned, photo) and returns clean text + structured data.

Install:
    pip install pdfplumber pymupdf pillow opencv-python-headless pytesseract langdetect python-docx

For Azure OCR (optional but recommended):
    pip install azure-ai-documentintelligence azure-core
    Set env vars: AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY
"""

import os
import re
import json
import cv2
import numpy as np
import pdfplumber
import pytesseract

from PIL import Image
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# STEP 1 — FIGURE OUT WHAT TYPE OF DOCUMENT THIS IS
# ─────────────────────────────────────────────────────────────────

def get_document_type(file_path):
    """
    Look at the file and decide what it is.
    Returns one of: "digital_pdf", "scanned_pdf", "photo", "word"
    """
    ext = Path(file_path).suffix.lower()

    # Word document
    if ext in (".docx", ".doc"):
        return "word"

    # Photo / image
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        return "photo"

    # PDF — but is it a real digital PDF or a scanned one?
    if ext == ".pdf":
        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""

        # If we got very little text, it's probably a scanned PDF
        if len(text.strip()) < 100:
            return "scanned_pdf"
        else:
            return "digital_pdf"

    return "unknown"


# ─────────────────────────────────────────────────────────────────
# STEP 2 — CLEAN UP THE IMAGE BEFORE OCR (scans + photos only)
# ─────────────────────────────────────────────────────────────────

def clean_image(image):
    """
    Takes a raw scanned/photo image and cleans it up for better OCR.
    Returns the cleaned image.

    What it does:
    - Converts to grayscale
    - Upscales if too small (low DPI)
    - Straightens if rotated
    - Fixes uneven lighting
    - Removes noise/grain
    """

    # Convert to grayscale
    if len(image.shape) == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Upscale if image is too small (low resolution scans)
    height, width = image.shape
    if width < 1700:  # anything below ~200 DPI on A4
        scale = 2.0
        image = cv2.resize(image, (int(width * scale), int(height * scale)),
                           interpolation=cv2.INTER_LANCZOS4)
        print("  → Upscaled image for better OCR")

    # Straighten the image (deskew)
    image = straighten_image(image)

    # Fix uneven lighting (handles shadows, dark corners)
    image = cv2.adaptiveThreshold(
        image, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 10
    )

    # Remove noise
    image = cv2.fastNlMeansDenoising(image, h=10)

    return image


def straighten_image(image):
    """
    Detect if the page is slightly rotated and fix it.
    Uses Hough line detection to find the dominant angle.
    """
    edges = cv2.Canny(image, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

    if lines is None:
        return image  # no lines found, nothing to fix

    # Collect angles from detected lines
    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        angle = np.degrees(theta) - 90
        if -45 < angle < 45:
            angles.append(angle)

    if not angles:
        return image

    rotation_angle = float(np.median(angles))

    # Only rotate if the skew is noticeable
    if abs(rotation_angle) < 0.5:
        return image

    print(f"  → Correcting {rotation_angle:.1f}° rotation")
    h, w = image.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, rotation_angle, 1.0)
    image = cv2.warpAffine(image, matrix, (w, h),
                           borderMode=cv2.BORDER_REPLICATE)
    return image


# ─────────────────────────────────────────────────────────────────
# STEP 3 — EXTRACT TEXT USING OCR
# ─────────────────────────────────────────────────────────────────

def extract_text_tesseract(image):
    """
    Run Tesseract OCR on a cleaned image.
    Returns (text, confidence_score between 0 and 1)
    """
    pil_image = Image.fromarray(image)

    # Get word-level data including confidence scores
    data = pytesseract.image_to_data(
        pil_image,
        lang="eng+hin",          # English + Hindi support
        config="--oem 1 --psm 6",  # LSTM engine, uniform text block
        output_type=pytesseract.Output.DICT
    )

    words = []
    confidences = []

    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = float(data["conf"][i])
        if word and conf > 0:
            words.append(word)
            confidences.append(conf / 100.0)  # convert 0-100 to 0-1

    text = " ".join(words)
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return text, avg_confidence


def extract_text_azure(file_path):
    """
    Run Azure Document Intelligence OCR.
    This is more powerful — handles stamps, tables, Hindi text better.
    Returns (text, confidence_score) or (None, None) if Azure not set up.
    """
    endpoint = os.getenv("AZURE_DOC_INTEL_ENDPOINT", "")
    key      = os.getenv("AZURE_DOC_INTEL_KEY", "")

    if not endpoint or not key:
        return None, None  # Azure not configured, that's fine

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        from azure.core.credentials import AzureKeyCredential

        client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))

        with open(file_path, "rb") as f:
            poller = client.begin_analyze_document(
                "prebuilt-read",
                body=f,
                content_type="application/octet-stream"
            )
        result = poller.result()

        all_text = ""
        all_confidences = []

        for page in result.pages:
            for word in (page.words or []):
                all_text += word.content + " "
                all_confidences.append(word.confidence or 0.0)

        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        return all_text.strip(), avg_confidence

    except Exception as e:
        print(f"  → Azure OCR failed: {e}")
        return None, None


def reconcile(azure_text, azure_conf, tesseract_text, tesseract_conf):
    """
    We ran two OCR engines. Now decide which result to trust.

    Rules:
    - Both worked and agree  → use Azure, high confidence
    - Both worked but differ → use Azure, flag for review
    - Only Azure worked      → use Azure
    - Only Tesseract worked  → use Tesseract, flag for review
    - Neither worked         → empty text, flag for review
    """
    has_azure      = azure_text is not None and len(azure_text.strip()) > 10
    has_tesseract  = tesseract_text is not None and len(tesseract_text.strip()) > 10

    if has_azure and has_tesseract:
        similarity = text_similarity(azure_text, tesseract_text)
        if similarity > 0.7:
            return azure_text, azure_conf, False, "azure+tesseract agreed"
        else:
            return azure_text, azure_conf * 0.85, True, "engines disagreed — flagged"

    elif has_azure:
        flagged = azure_conf < 0.80
        return azure_text, azure_conf, flagged, "azure only"

    elif has_tesseract:
        return tesseract_text, tesseract_conf, True, "tesseract only — flagged"

    else:
        return "", 0.0, True, "no text extracted — needs manual review"


def text_similarity(text_a, text_b):
    """
    Simple check: what fraction of words appear in both texts?
    Returns a score between 0 (nothing in common) and 1 (identical).
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    shared = words_a & words_b
    total  = words_a | words_b
    return len(shared) / len(total)


# ─────────────────────────────────────────────────────────────────
# STEP 4 — NORMALISE VALUES (currency, dates, entity names)
# ─────────────────────────────────────────────────────────────────

def normalise_currency(raw_text):
    """
    Convert any Indian money expression to a plain number.

    Examples:
        "Rs. 5,00,000"      → 500000
        "₹5 Lakhs"          → 500000
        "Five Crore Rupees" → 50000000
        "6.45Cr"            → 64500000
    """
    text = raw_text.lower().strip()

    # Remove currency symbols
    text = re.sub(r"(rs\.?|₹|inr|rupees?|/-)", " ", text).strip()

    # Handle short forms like "5cr", "12.5l", "3k"
    match = re.match(r"^([\d,]+\.?\d*)\s*(cr|crore|crores|l|lakh|lakhs|k|thousand)$", text)
    if match:
        number   = float(match.group(1).replace(",", ""))
        suffix   = match.group(2)
        multiply = {
            "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
            "l": 100_000,     "lakh": 100_000,      "lakhs": 100_000,
            "k": 1_000,       "thousand": 1_000,
        }
        return int(number * multiply[suffix])

    # Handle written-out numbers like "Five Crore"
    written = parse_written_number(text)
    if written:
        return written

    # Handle plain numbers with commas like "5,00,000"
    match = re.search(r"[\d,]+\.?\d*", text)
    if match:
        return int(float(match.group(0).replace(",", "")))

    return None  # couldn't parse


def parse_written_number(text):
    """
    Convert written numbers like "Five Crore Forty Five Lakhs" to an integer.
    """
    word_map = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90, "hundred": 100,
        "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000,
        "crore": 10_000_000, "crores": 10_000_000,
    }

    tokens = text.replace("-", " ").split()
    total   = 0
    current = 0

    for token in tokens:
        if token in word_map:
            n = word_map[token]
            if n == 100:
                current *= 100
            elif n >= 1000:
                total  += (current or 1) * n
                current = 0
            else:
                current += n

    total += current
    return total if total > 0 else None


def normalise_date(raw_text):
    """
    Convert any date format to YYYY-MM-DD.

    Examples:
        "01/04/2022"    → "2022-04-01"
        "1-Apr-22"      → "2022-04-01"
        "April 1 2022"  → "2022-04-01"
    """
    try:
        from dateutil import parser as dateparser
        parsed = dateparser.parse(raw_text.strip(), dayfirst=True)
        return parsed.strftime("%Y-%m-%d") if parsed else None
    except Exception:
        return None


def normalise_entity(raw_text):
    """
    Map common document label variations to a standard name.

    Examples:
        "GST No."  → "GST_REGISTRATION"
        "GSTIN"    → "GST_REGISTRATION"
        "Turnover" → "ANNUAL_TURNOVER"
    """
    mappings = {
        r"gst":              "GST_REGISTRATION",
        r"gstin":            "GST_REGISTRATION",
        r"pan":              "PAN_NUMBER",
        r"iso.?9001":        "ISO_9001",
        r"iso.?14001":       "ISO_14001",
        r"turn.?over":       "ANNUAL_TURNOVER",
        r"net.?worth":       "NET_WORTH",
        r"similar.?project": "SIMILAR_PROJECTS",
        r"similar.?work":    "SIMILAR_PROJECTS",
    }
    for pattern, standard_name in mappings.items():
        if re.search(pattern, raw_text, re.IGNORECASE):
            return standard_name

    # Fallback: just clean it up as UPPER_SNAKE_CASE
    return re.sub(r"\s+", "_", raw_text.strip()).upper()


# ─────────────────────────────────────────────────────────────────
# STEP 5 — EXTRACT SPECIFIC FIELDS FROM TEXT
# ─────────────────────────────────────────────────────────────────

def extract_fields(text):
    """
    Look through the extracted text and pull out common tender-related values.
    Returns a dict of found fields.
    """
    fields = {}

    # GST number (format: 22AAAAA0000A1Z5)
    gst = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]\b", text)
    if gst:
        fields["GST_REGISTRATION"] = gst.group(0)

    # PAN number (format: ABCDE1234F)
    pan = re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", text)
    if pan:
        fields["PAN_NUMBER"] = pan.group(0)

    # ISO certification
    iso = re.search(r"ISO\s*\d{4,5}(?::\d{4})?", text, re.IGNORECASE)
    if iso:
        fields["ISO_CERT"] = iso.group(0)

    # Turnover / revenue amount
    turnover = re.search(
        r"(?:turnover|revenue|annual)[^\d]{0,30}((?:rs\.?\s*|₹)?[\d,]+\.?\d*\s*(?:crore|lakh|cr|l)?)",
        text, re.IGNORECASE
    )
    if turnover:
        raw = turnover.group(1)
        normalised = normalise_currency(raw)
        fields["ANNUAL_TURNOVER"] = {
            "raw": raw,
            "normalised_inr": normalised
        }

    # Number of similar projects
    projects = re.search(
        r"(\d+)\s*(?:similar|comparable)?\s*(?:projects?|works?)", text, re.IGNORECASE
    )
    if projects:
        fields["SIMILAR_PROJECTS_COUNT"] = int(projects.group(1))

    # Dates (expiry, validity)
    dates = re.findall(
        r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b", text
    )
    if dates:
        fields["DATES_FOUND"] = [normalise_date(d) for d in dates if normalise_date(d)]

    return fields


# ─────────────────────────────────────────────────────────────────
# MAIN FUNCTION — scan any document
# ─────────────────────────────────────────────────────────────────

def scan_document(file_path):
    print(f"\nScanning: {file_path}")
    print("-" * 40)

    result = {
        "document_id":   Path(file_path).stem,
        "source_path":   file_path,
        "doc_type":      "",
        "text_preview":  "", # Store a short preview instead of the whole messy text
        "confidence":    0.0,
        "needs_review":  False,
        "review_reason": None,
        "fields":        {}
    }

    doc_type = get_document_type(file_path)
    result["doc_type"] = doc_type

    # ── Step 2 & 3: Deep Extraction (Every Page) ────────────────
    all_pages_clean_text = []
    
    if doc_type == "digital_pdf":
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                raw_text = page.extract_text() or ""
                # FILTER: If a line is just dots or underscores (blank form), ignore it
                for line in raw_text.split('\n'):
                    if not re.search(r"\.{3,}|_{3,}", line) and len(line.strip()) > 3:
                        all_pages_clean_text.append(line.strip())
        
        full_text = "\n".join(all_pages_clean_text)
        confidence = 0.99
        engine = "pdfplumber"

    elif doc_type in ("scanned_pdf", "photo"):
        # For OCR, we still clean and process as usual
        images = get_images_from_file(file_path, doc_type)
        if not images:
            result["needs_review"] = True
            result["review_reason"] = "Could not read images"
            return result
        
        # Process every image in the file
        ocr_results = []
        for img in images:
            cleaned = clean_image(img)
            # You can choose to run both or just Azure for speed
            t_text, _ = extract_text_tesseract(cleaned)
            ocr_results.append(t_text)
        
        full_text = "\n".join(ocr_results)
        confidence = 0.85 # Standard OCR confidence
        engine = "tesseract_ensemble"

    # ── Step 4: Intelligent Field Extraction ────────────────────
    # This is where we filter down to just the "Essentials"
    print("  Extracting essential fields...")
    
    # Define the 'Anchors' we care about across all tenders
    essential_data = {}
    
    # 1. Financials (Looks for Currency near keywords)
    money_pattern = r"(?:Rs\.?|₹|INR)\s*([\d,]+\.?\d*)"
    
    nit_match = re.search(r"(?:Amount of NIT|Estimated Cost).*?" + money_pattern, full_text, re.IGNORECASE)
    if nit_match:
        essential_data['estimated_cost'] = float(nit_match.group(1).replace(',', ''))

    emd_match = re.search(r"(?:EMD|Earnest Money).*?" + money_pattern, full_text, re.IGNORECASE)
    if emd_match:
        essential_data['emd_amount'] = float(emd_match.group(1).replace(',', ''))

    # 2. Statutory IDs (Regex for Indian PAN and GST)
    pan = re.search(r"\b[A-Z]{5}\d{4}[A-Z]{1}\b", full_text)
    gst = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b", full_text)
    
    if pan: essential_data['pan_number'] = pan.group(0)
    if gst: essential_data['gst_number'] = gst.group(0)

    # 3. Dates
    # Only keep dates that mention "Deadline", "Opening", or "Closing"
    dates = re.findall(r"(?:Deadline|Opening|Closing|Dated).*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", full_text, re.IGNORECASE)
    if dates:
        essential_data['critical_dates'] = list(set(dates))

    # ── Step 5: Final Packaging ─────────────────────────────────
    result["fields"] = essential_data
    result["confidence"] = confidence
    result["text_preview"] = full_text[:1000] # Save space in your JSON
    
    if not essential_data:
        result["needs_review"] = True
        result["review_reason"] = "No essential fields (GST, Cost, PAN) found. Document might be a blank template."

    print(f"  ✓ Found {len(essential_data)} essential fields")
    return result


def get_images_from_file(file_path, doc_type):
    """Convert a PDF or image file into a list of numpy arrays (one per page)."""
    images = []

    if doc_type == "photo":
        img = cv2.imread(file_path)
        if img is not None:
            images.append(img)

    elif doc_type == "scanned_pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            for page in doc:
                mat = fitz.Matrix(2.0, 2.0)  # zoom in for better resolution
                pix = page.get_pixmap(matrix=mat)
                arr = np.frombuffer(pix.samples, dtype=np.uint8)
                img = arr.reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                images.append(img)
            doc.close()
        except Exception as e:
            print(f"  Could not read PDF pages as images: {e}")

    return images


# ─────────────────────────────────────────────────────────────────
# RUN IT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        # No file given — just test the normalisation functions
        print("No file provided. Running normalisation tests...\n")

        test_values = [
            ("Rs. 5,00,000",        "currency"),
            ("₹5 Lakhs",            "currency"),
            ("Five Crore Rupees",   "currency"),
            ("6.45Cr",              "currency"),
            ("01/04/2022",          "date"),
            ("1-Apr-22",            "date"),
            ("March 31st 2025",     "date"),
        ]

        for raw, kind in test_values:
            if kind == "currency":
                result = normalise_currency(raw)
                print(f"  {raw:30} → ₹{result:,}")
            else:
                result = normalise_date(raw)
                print(f"  {raw:30} → {result}")

        print("\nAll tests done. To scan a document, run:")
        print("  python scanner.py path/to/document.pdf")

    else:
        # Scan the given file and print results
        output = scan_document(sys.argv[1])
        print("\n── RESULT ──────────────────────────────")
        print(json.dumps(output, indent=2, ensure_ascii=False))