
import re
import os
import sys
import json
import requests


# ─────────────────────────────────────────────
# SANDBOX API — GST VERIFICATION
# ─────────────────────────────────────────────

SANDBOX_BASE       = "https://api.sandbox.co.in"
SANDBOX_API_KEY    = os.getenv("SANDBOX_API_KEY", "")
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", "")
_sandbox_token     = None


def _get_sandbox_token():
    global _sandbox_token
    if _sandbox_token:
        return _sandbox_token
    if not SANDBOX_API_KEY or not SANDBOX_API_SECRET:
        return None
    try:
        resp = requests.post(
            f"{SANDBOX_BASE}/authenticate",
            headers={
                "x-api-key":    SANDBOX_API_KEY,
                "x-api-secret": SANDBOX_API_SECRET,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        _sandbox_token = resp.json().get("data", {}).get("access_token")
        return _sandbox_token
    except Exception as e:
        print(f"  [Sandbox] Auth failed: {e}")
        return None


def verify_gstin(gstin):
    """
    Verify a GSTIN against government records via Sandbox API.
    Falls back to format-only check if API keys are not set.

    Returns dict with: found, status, company_name, company_type, state, reg_date
    """
    if not gstin:
        return {"found": False, "status": "Missing", "detail": "No GST number found in document"}

    # Format check first — always
    pattern = r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$"
    if not re.match(pattern, gstin.strip().upper()):
        return {
            "found":  False,
            "status": "Invalid format",
            "detail": f"'{gstin}' does not match GSTIN format (e.g. 27AAPFU0939F1ZV)"
        }

    # Live API check
    token = _get_sandbox_token()
    if not token:
        return {
            "found":        None,
            "status":       "Format valid",
            "company_name": None,
            "detail":       "API keys not set — format validated only. Set SANDBOX_API_KEY to enable live check."
        }

    try:
        resp = requests.post(
            f"{SANDBOX_BASE}/gst/compliance/public/gstin/search",
            headers={
                "Authorization": token,
                "x-api-key":     SANDBOX_API_KEY,
                "Content-Type":  "application/json",
                "x-api-version": "1.0.0"
            },
            json={"gstin": gstin.upper()},
            timeout=10
        )
        gst_data = resp.json().get("data", {}).get("data", {})

        if not gst_data:
            return {"found": False, "status": "Not found",
                    "detail": f"{gstin} not found in GST database"}

        return {
            "found":        True,
            "status":       gst_data.get("sts", "Unknown"),       # "Active" / "Cancelled"
            "company_name": gst_data.get("lgnm", ""),
            "company_type": gst_data.get("ctb", ""),
            "state":        gst_data.get("pradr", {}).get("addr", {}).get("stcd", ""),
            "reg_date":     gst_data.get("rgdt", ""),
        }
    except Exception as e:
        return {"found": None, "status": "API error", "detail": str(e)}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _normalize(text):
    """Lowercase, strip punctuation/spaces — for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _extract_numbers(text):
    """Pull all numbers out of a string."""
    return re.findall(r"\d+(?:\.\d+)?", str(text))


def _items_match(tender_item, bidder_item):
    """
    Check if a bidder item name matches a tender item name.
    Uses normalized substring matching so minor wording differences don't break it.
    e.g. "T-Shirt Round Neck" matches "Round Neck T-Shirt Disruptive"
    """
    t = _normalize(tender_item)
    b = _normalize(bidder_item)
    # Check if enough words overlap (at least 50% of tender words found in bidder)
    t_words = set(re.findall(r"[a-z0-9]{3,}", t))
    b_words = set(re.findall(r"[a-z0-9]{3,}", b))
    if not t_words:
        return False
    overlap = len(t_words & b_words) / len(t_words)
    return overlap >= 0.5


def _quantities_match(tender_qty, bidder_qty):
    """
    Compare quantities. Returns (match: bool, note: str)
    Bidder quantity must be >= tender quantity to be eligible.
    """
    t_nums = _extract_numbers(tender_qty)
    b_nums = _extract_numbers(bidder_qty)

    if not t_nums or not b_nums:
        return None, "Could not parse quantities for comparison"

    t = float(t_nums[0])
    b = float(b_nums[0])

    if b >= t:
        return True, f"Bidder offers {b_nums[0]}, required {t_nums[0]}"
    else:
        return False, f"Bidder offers {b_nums[0]}, required {t_nums[0]}"


# ─────────────────────────────────────────────
# EXTRACT GST FROM SCANNER OUTPUT
# ─────────────────────────────────────────────

def _find_gst_in_scan(scan_data):
    """
    Look for a GST number anywhere in the scanner output.
    Scanner doesn't explicitly label it, so we search all string values.
    """
    text = json.dumps(scan_data)
    match = re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b", text)
    return match.group(0) if match else None


def _find_pan_in_scan(scan_data):
    """Look for a PAN number anywhere in the scanner output."""
    text = json.dumps(scan_data)
    match = re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", text)
    return match.group(0) if match else None


# ─────────────────────────────────────────────
# MAIN VERDICT FUNCTION
# ─────────────────────────────────────────────

def get_verdict(tender_data, bidder_data, bidder_name="bidder"):
    """
    Compare bidder scan output against tender scan output.

    Both tender_data and bidder_data are the raw dicts returned by
    TenderScanner.extract_from_pdf() — no wrapper, no "fields" key.

    Returns:
      {
        "bidder_id":      str,
        "overall_status": "ELIGIBLE" | "NOT ELIGIBLE" | "FLAGGED FOR REVIEW",
        "reasons":        [str, ...],   # only issues — what went wrong
        "audit_detail":   [dict, ...],  # every check for audit trail
        "company_info":   dict          # from GST API
      }
    """
    reasons = []
    detail  = []

    tender_items = tender_data.get("materials_required", [])
    bidder_items  = bidder_data.get("materials_required", [])

    # ── 1. DOCUMENT QUALITY ───────────────────────────────────────
    # Scanner doesn't return a confidence score yet —
    # flag if materials list is completely empty (likely bad scan)
    if not bidder_items:
        reasons.append(
            "No materials or specifications could be extracted from bidder document — "
            "document may be unreadable or incorrectly formatted"
        )
        detail.append({
            "check":    "Document Readability",
            "result":   "FLAG",
            "required": "Readable document with specification data",
            "found":    "No data extracted"
        })
    else:
        detail.append({
            "check":    "Document Readability",
            "result":   "PASS",
            "required": "Readable document",
            "found":    f"{len(bidder_items)} item(s) extracted"
        })

    # ── 2. COMPANY LEGITIMACY — GST check ────────────────────────
    bidder_gst = _find_gst_in_scan(bidder_data)
    bidder_pan = _find_pan_in_scan(bidder_data)
    gst_result = verify_gstin(bidder_gst)

    if gst_result["found"] is False:
        reasons.append(
            f"GST verification failed — {gst_result.get('detail', gst_result['status'])}"
        )
        detail.append({
            "check":    "GST Verification",
            "result":   "FAIL",
            "required": "Valid active GSTIN",
            "found":    bidder_gst or "Not found",
            "note":     gst_result.get("detail", gst_result["status"])
        })
    elif gst_result["found"] is True:
        if gst_result["status"] != "Active":
            reasons.append(
                f"GST registration for '{gst_result.get('company_name', bidder_gst)}' "
                f"is {gst_result['status']} — company may not be active"
            )
            detail.append({
                "check":    "GST Verification",
                "result":   "FLAG",
                "required": "Active GSTIN",
                "found":    bidder_gst,
                "note":     f"Status: {gst_result['status']}"
            })
        else:
            detail.append({
                "check":    "GST Verification",
                "result":   "PASS",
                "required": "Active GSTIN",
                "found":    bidder_gst,
                "note":     f"{gst_result.get('company_name','')} — Active"
            })
    else:
        # API not configured — format was valid, note it
        detail.append({
            "check":    "GST Verification",
            "result":   "PASS",
            "required": "Valid GSTIN format",
            "found":    bidder_gst or "Not found",
            "note":     gst_result.get("detail", "Format validated only")
        })

    # PAN check
    if not bidder_pan:
        reasons.append("PAN number not found in bidder document")
        detail.append({
            "check": "PAN Number", "result": "FLAG",
            "required": "Valid PAN", "found": "Not found"
        })
    elif not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", bidder_pan.upper()):
        reasons.append(f"PAN number '{bidder_pan}' has invalid format")
        detail.append({
            "check": "PAN Number", "result": "FAIL",
            "required": "Valid PAN format", "found": bidder_pan
        })
    else:
        detail.append({
            "check": "PAN Number", "result": "PASS",
            "required": "Valid PAN", "found": bidder_pan
        })

    # ── 3. BUDGET / FINANCIAL CHECK ───────────────────────────────
    tender_budget = tender_data.get("budget", "0")
    bidder_budget = bidder_data.get("budget", "0")

    try:
        t_budget = float(str(tender_budget).replace(",", "")) if tender_budget != "0.00" else None
        b_budget = float(str(bidder_budget).replace(",", "")) if bidder_budget != "0.00" else None

        if t_budget and b_budget:
            if b_budget >= t_budget:
                detail.append({
                    "check":    "Budget / Financials",
                    "result":   "PASS",
                    "required": f"{tender_budget}",
                    "found":    f"{bidder_budget}"
                })
            else:
                reasons.append(
                    f"Bidder financials ({bidder_budget}) are below the tender value ({tender_budget})"
                )
                detail.append({
                    "check":    "Budget / Financials",
                    "result":   "FAIL",
                    "required": f"{tender_budget}",
                    "found":    f"{bidder_budget}"
                })
        else:
            detail.append({
                "check":  "Budget / Financials",
                "result": "FLAG",
                "required": str(tender_budget),
                "found":    str(bidder_budget) if bidder_budget else "Not stated",
                "note":   "Could not compare — value missing or unparseable"
            })
    except Exception:
        detail.append({
            "check": "Budget / Financials", "result": "FLAG",
            "note":  "Could not parse budget values"
        })

    # ── 4. MATERIALS / SPECIFICATIONS — the core comparison ───────
    if not tender_items:
        detail.append({
            "check":  "Materials Comparison",
            "result": "FLAG",
            "note":   "No materials extracted from tender — cannot compare"
        })
    else:
        unmatched_count = 0

        for t_item in tender_items:
            t_name = t_item.get("item", "")
            t_qty  = t_item.get("quantity", "")
            t_det  = t_item.get("details", "")

            if not t_name:
                continue

            # Find matching item in bidder's list
            matched_bidder_item = next(
                (b for b in bidder_items if _items_match(t_name, b.get("item", ""))),
                None
            )

            if matched_bidder_item is None:
                unmatched_count += 1
                detail.append({
                    "check":    f"Item: {t_name[:50]}",
                    "result":   "FLAG",
                    "required": f"qty: {t_qty} | {t_det}",
                    "found":    "Not found in bidder document"
                })
            else:
                b_qty  = matched_bidder_item.get("quantity", "")
                b_det  = matched_bidder_item.get("details", "")
                b_name = matched_bidder_item.get("item", "")

                # Compare quantities
                qty_match, qty_note = _quantities_match(t_qty, b_qty)

                if qty_match is False:
                    reasons.append(
                        f"Item '{t_name[:40]}' — quantity mismatch: {qty_note}"
                    )
                    detail.append({
                        "check":    f"Item: {t_name[:50]}",
                        "result":   "FAIL",
                        "required": f"qty: {t_qty}",
                        "found":    f"qty: {b_qty}",
                        "note":     qty_note
                    })
                elif qty_match is None:
                    detail.append({
                        "check":    f"Item: {t_name[:50]}",
                        "result":   "FLAG",
                        "required": f"qty: {t_qty} | {t_det}",
                        "found":    f"qty: {b_qty} | {b_det}",
                        "note":     qty_note
                    })
                else:
                    detail.append({
                        "check":    f"Item: {t_name[:50]}",
                        "result":   "PASS",
                        "required": f"qty: {t_qty}",
                        "found":    f"qty: {b_qty}",
                        "note":     qty_note
                    })

        if unmatched_count > 0:
            reasons.append(
                f"{unmatched_count} item(s) required by the tender were not found "
                f"in the bidder's submission"
            )

    # ── FINAL VERDICT ─────────────────────────────────────────────
    hard_fails = [r for r in reasons if any(k in r.lower() for k in
                  ["failed", "invalid", "below", "mismatch", "not found in bidder"])]

    if hard_fails:
        overall = "NOT ELIGIBLE"
    elif reasons:
        overall = "FLAGGED FOR REVIEW"
    else:
        overall = "ELIGIBLE"

    return {
        "bidder_id":      bidder_name,
        "overall_status": overall,
        "reasons":        reasons,
        "audit_detail":   detail,
        "company_info": {
            "name":       gst_result.get("company_name"),
            "type":       gst_result.get("company_type"),
            "gst_status": gst_result.get("status"),
            "state":      gst_result.get("state"),
            "reg_date":   gst_result.get("reg_date"),
        }
    }


# ─────────────────────────────────────────────
# PRINT
# ─────────────────────────────────────────────

def print_verdict(verdict):
    symbol = {"ELIGIBLE": "✓", "NOT ELIGIBLE": "✗", "FLAGGED FOR REVIEW": "⚠"}.get(
        verdict["overall_status"], "?")

    print(f"\n{'═'*55}")
    print(f"  BIDDER  : {verdict['bidder_id']}")

    info = verdict.get("company_info", {})
    if info.get("name"):
        print(f"  COMPANY : {info['name']} ({info.get('type','')})")
        print(f"  GST     : {info.get('gst_status','')} | {info.get('state','')} | Reg: {info.get('reg_date','')}")

    print(f"  VERDICT : {symbol}  {verdict['overall_status']}")
    print(f"{'═'*55}")

    if not verdict["reasons"]:
        print("  All checks passed. Bidder is eligible.")
    else:
        print(f"  ISSUES ({len(verdict['reasons'])}):")
        for i, r in enumerate(verdict["reasons"], 1):
            print(f"  {i}. {r}")
    print()


# ─────────────────────────────────────────────
# RUN — python verdict.py tender.pdf bidder.pdf
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python verdict.py <tender.pdf> <bidder.pdf>")
        print("\nRunning with dummy data instead...\n")

        # Dummy data matching scanner.py output format exactly
        DUMMY_TENDER = {
            "issuing_authority": "CRPF HQ New Delhi",
            "opening_date":      "15/05/2026",
            "budget":            "4200000",
            "materials_required": [
                {"item": "T-Shirt Half Sleeves Round Neck Disruptive Pattern", "quantity": "500",  "details": "92% Polyester 8% Lycra"},
                {"item": "Packaging Polybag Transparent",                       "quantity": "500",  "details": "35cm x 27cm"},
                {"item": "Cardboard Box Recycled",                              "quantity": "100",  "details": "300 gsm 26cm x 22cm"},
            ]
        }

        DUMMY_BIDDER_GOOD = {
            "issuing_authority": "N/A",
            "opening_date":      "N/A",
            "budget":            "5000000",
            "materials_required": [
                {"item": "T-Shirt Round Neck Disruptive Half Sleeve",  "quantity": "500",  "details": "92% Polyester 8% Lycra GSTIN:27AAPFU0939F1ZV PAN:AAPFU0939F"},
                {"item": "Transparent Polybag Packaging",              "quantity": "500",  "details": "35cm x 27cm"},
                {"item": "Recycled Cardboard Box",                     "quantity": "100",  "details": "300gsm"},
            ]
        }

        DUMMY_BIDDER_BAD = {
            "issuing_authority": "N/A",
            "opening_date":      "N/A",
            "budget":            "3000000",
            "materials_required": [
                {"item": "T-Shirt Round Neck",  "quantity": "300",  "details": "80% Polyester GSTIN:BADINVALID123"},
                # Missing other items
            ]
        }

        print("─"*55)
        print("  CRPF TENDER EVALUATION — VERDICT ENGINE")
        print("─"*55)
        print_verdict(get_verdict(DUMMY_TENDER, DUMMY_BIDDER_GOOD, "GoodBidder_Co"))
        print_verdict(get_verdict(DUMMY_TENDER, DUMMY_BIDDER_BAD,  "BadBidder_Co"))

    else:
        # Real usage — scan both files and compare
        from scanner import TenderScanner

        scanner     = TenderScanner()
        tender_data = scanner.extract_from_pdf(sys.argv[1])
        bidder_data  = scanner.extract_from_pdf(sys.argv[2])

        print(f"\nTender  : {sys.argv[1]}")
        print(f"Bidder  : {sys.argv[2]}\n")

        verdict = get_verdict(tender_data, bidder_data, bidder_name=sys.argv[2])
        print_verdict(verdict)

        # Full JSON output for audit
        print("\n── FULL AUDIT DETAIL " + "─"*35)
        print(json.dumps(verdict["audit_detail"], indent=2))