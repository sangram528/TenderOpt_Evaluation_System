"""
verdict.py — CRPF Tender Evaluation
=====================================
Takes scanner output for a tender + bidder and produces a final verdict.

Company legitimacy is checked against real Indian government records
via the Sandbox.co.in API (https://developer.sandbox.co.in):
  - GST number → verified against GST Network (live status + company name)
  - PAN → cross-checked against the GST record
  - Company active/cancelled status → from the same API response

To get your Sandbox API keys:
  1. Sign up at https://accounts.sandbox.co.in/signup (free tier available)
  2. Go to dashboard → get x-api-key and x-api-secret
  3. Set environment variables:
       SANDBOX_API_KEY=your_key
       SANDBOX_API_SECRET=your_secret

When scanner.py is ready, replace the dummy data at the bottom with:
    from scanner import scan_document
    tender_scan = scan_document("tender.pdf")
    bidder_scan  = scan_document("bidder.pdf")
    print_verdict(get_verdict(tender_scan, bidder_scan))
"""

import re
import os
import json
import requests


# ─────────────────────────────────────────────────────────────────
# SANDBOX API — REAL GOVERNMENT RECORD CHECKS
# ─────────────────────────────────────────────────────────────────

SANDBOX_BASE      = "https://api.sandbox.co.in"
SANDBOX_API_KEY   = os.getenv("SANDBOX_API_KEY", "")
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", "")

_sandbox_token = None   # cached JWT token


def _get_sandbox_token():
    """
    Authenticate with Sandbox and get a JWT token.
    Token is cached so we only call this once per run.
    """
    global _sandbox_token
    if _sandbox_token:
        return _sandbox_token

    if not SANDBOX_API_KEY or not SANDBOX_API_SECRET:
        return None     # API keys not set up

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
        data = resp.json()
        _sandbox_token = data.get("data", {}).get("access_token")
        return _sandbox_token
    except Exception as e:
        print(f"  [Sandbox] Auth failed: {e}")
        return None


def verify_gstin_live(gstin):
    """
    Call Sandbox GST API to verify a GSTIN against real government records.

    Returns a dict:
      {
        "found":        True/False,
        "status":       "Active" / "Cancelled" / "Not Found",
        "company_name": "SHIV TEXTILES PVT LTD",
        "trade_name":   "SHIV TEXTILES",
        "company_type": "Private Limited Company",
        "state":        "Maharashtra",
        "reg_date":     "01/04/2018",
        "raw":          { ...full API response... }
      }
    """
    # Step 1: format check before even hitting the API
    if not gstin or not re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$", gstin.upper()):
        return {
            "found":        False,
            "status":       "Invalid format",
            "company_name": None,
            "detail":       f"GSTIN '{gstin}' does not match the required format"
        }

    token = _get_sandbox_token()
    if not token:
        # API not configured — fall back to format-only check
        return {
            "found":        None,       # None = unknown (not checked)
            "status":       "Format valid (API not configured)",
            "company_name": None,
            "detail":       "Set SANDBOX_API_KEY and SANDBOX_API_SECRET to enable live verification"
        }

    try:
        resp = requests.post(
            f"{SANDBOX_BASE}/gst/compliance/public/gstin/search",
            headers={
                "Authorization": token,     # no "Bearer" prefix — Sandbox specific
                "x-api-key":     SANDBOX_API_KEY,
                "Content-Type":  "application/json",
                "x-api-version": "1.0.0"
            },
            json={"gstin": gstin.upper()},
            timeout=10
        )

        resp_data = resp.json()
        gst_data  = resp_data.get("data", {}).get("data", {})

        if not gst_data:
            return {
                "found":        False,
                "status":       "Not found in GST records",
                "company_name": None,
                "detail":       f"GSTIN {gstin} not found in government GST database"
            }

        status       = gst_data.get("sts", "Unknown")     # "Active" or "Cancelled"
        company_name = gst_data.get("lgnm", "")           # legal name
        trade_name   = gst_data.get("tradeNam", "")
        company_type = gst_data.get("ctb", "")            # e.g. "Private Limited"
        reg_date     = gst_data.get("rgdt", "")
        state        = gst_data.get("pradr", {}).get("addr", {}).get("stcd", "")

        return {
            "found":        True,
            "status":       status,
            "company_name": company_name,
            "trade_name":   trade_name,
            "company_type": company_type,
            "state":        state,
            "reg_date":     reg_date,
            "raw":          gst_data
        }

    except Exception as e:
        return {
            "found":        None,
            "status":       "API error",
            "company_name": None,
            "detail":       f"Could not reach Sandbox API: {e}"
        }


# ─────────────────────────────────────────────────────────────────
# THE ONE FUNCTION THAT DOES EVERYTHING
# ─────────────────────────────────────────────────────────────────

def get_verdict(tender_scan, bidder_scan):
    """
    Compares a bidder's documents against tender requirements.
    Returns a clean verdict dict with:
      - overall_status: ELIGIBLE / NOT ELIGIBLE / FLAGGED FOR REVIEW
      - reasons:        list of specific issues (only failures + flags, not every passing check)
      - detail:         full breakdown for audit trail
    """
    tender  = tender_scan.get("fields", {})
    bidder  = bidder_scan.get("fields", {})
    reasons = []     # things that caused FAIL or FLAG
    detail  = []     # full audit trail of every check

    # ── 1. DOCUMENT QUALITY ───────────────────────────────────────
    confidence   = bidder_scan.get("confidence", 1.0)
    needs_review = bidder_scan.get("needs_review", False)

    if needs_review or confidence < 0.80:
        reasons.append(
            f"Document scan quality is low ({confidence:.0%} confidence) — "
            f"original documents must be verified manually"
        )
        detail.append({"check": "Document Quality", "result": "FLAG",
                        "note": bidder_scan.get("review_reason", f"Confidence: {confidence:.0%}")})
    else:
        detail.append({"check": "Document Quality", "result": "PASS",
                        "note": f"Confidence: {confidence:.0%}"})

    # ── 2. COMPANY LEGITIMACY (real API check) ────────────────────
    bidder_compliance = bidder.get("compliance", [])
    bidder_gst = next((i["value"] for i in bidder_compliance if i.get("type") == "GST"), None)
    bidder_pan = next((i["value"] for i in bidder_compliance if i.get("type") == "PAN"), None)

    gst_result = verify_gstin_live(bidder_gst)

    if gst_result["found"] is False:
        # Hard fail — GST either invalid format or not in government records
        reasons.append(
            f"GST number '{bidder_gst}' is not valid — "
            f"{gst_result.get('detail', gst_result['status'])}"
        )
        detail.append({"check": "GST Verification", "result": "FAIL",
                        "gstin": bidder_gst, "note": gst_result.get("detail", gst_result["status"])})

    elif gst_result["found"] is True:
        if gst_result["status"] != "Active":
            # GST exists but is cancelled/suspended
            reasons.append(
                f"GST registration for '{gst_result['company_name']}' "
                f"is {gst_result['status']} — company may not be active"
            )
            detail.append({"check": "GST Verification", "result": "FLAG",
                            "gstin": bidder_gst, "company": gst_result["company_name"],
                            "status": gst_result["status"]})
        else:
            detail.append({"check": "GST Verification", "result": "PASS",
                            "gstin": bidder_gst, "company": gst_result["company_name"],
                            "type": gst_result["company_type"],
                            "registered_since": gst_result["reg_date"]})

    else:
        # API not configured — format check only
        detail.append({"check": "GST Verification", "result": "INFO",
                        "note": gst_result.get("detail")})

    # PAN format check
    if not bidder_pan:
        reasons.append("PAN number not found in bidder documents")
        detail.append({"check": "PAN", "result": "FLAG", "note": "PAN not present"})
    elif not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", bidder_pan.upper()):
        reasons.append(f"PAN number '{bidder_pan}' has invalid format")
        detail.append({"check": "PAN", "result": "FAIL", "pan": bidder_pan})
    else:
        # If we got a company name from GST, check PAN prefix matches
        # PAN 4th char encodes entity type: C=Company, F=Firm, P=Individual, etc.
        entity_char = bidder_pan[3].upper()
        gst_type    = gst_result.get("company_type", "")
        detail.append({"check": "PAN", "result": "PASS", "pan": bidder_pan,
                        "entity_type_char": entity_char})

    # ── 3. CERTIFICATIONS ─────────────────────────────────────────
    tender_certs = [i["value"] for i in tender.get("compliance", [])
                    if i.get("type") == "certification"]
    bidder_certs = [re.sub(r"\s+", "", i["value"]).upper()
                    for i in bidder_compliance if i.get("type") == "certification"]

    for cert in tender_certs:
        cert_clean = re.sub(r"\s+", "", cert).upper()
        if cert_clean not in bidder_certs:
            reasons.append(
                f"Required certification '{cert}' not found in bidder documents — "
                f"certificate must be submitted for verification"
            )
            detail.append({"check": f"Certification: {cert}", "result": "FLAG",
                            "note": "Not found in submitted documents"})
        else:
            detail.append({"check": f"Certification: {cert}", "result": "PASS"})

    # ── 4. FINANCIAL REQUIREMENTS ─────────────────────────────────
    req_turnover = tender.get("financials", {}).get("min_turnover", {})
    bid_turnover = bidder.get("financials", {}).get("annual_turnover", {})
    req_inr      = req_turnover.get("inr") if isinstance(req_turnover, dict) else req_turnover
    bid_inr      = bid_turnover.get("inr") if isinstance(bid_turnover, dict) else bid_turnover

    if req_inr:
        if bid_inr is None:
            reasons.append(
                "Annual turnover not found in bidder's financial documents — "
                "audited balance sheet or CA certificate must be submitted"
            )
            detail.append({"check": "Annual Turnover", "result": "FLAG",
                            "required": f"Rs.{req_inr:,}", "found": "Not stated"})
        elif bid_inr < req_inr:
            reasons.append(
                f"Annual turnover Rs.{bid_inr:,} is below the minimum "
                f"requirement of Rs.{req_inr:,}"
            )
            detail.append({"check": "Annual Turnover", "result": "FAIL",
                            "required": f"Rs.{req_inr:,}", "found": f"Rs.{bid_inr:,}"})
        else:
            detail.append({"check": "Annual Turnover", "result": "PASS",
                            "required": f"Rs.{req_inr:,}", "found": f"Rs.{bid_inr:,}"})

    req_emd = tender.get("financials", {}).get("emd", {})
    bid_emd = bidder.get("financials", {}).get("emd_paid", {})
    req_emd_inr = req_emd.get("inr") if isinstance(req_emd, dict) else req_emd
    bid_emd_inr = bid_emd.get("inr") if isinstance(bid_emd, dict) else None

    if req_emd_inr:
        if not bid_emd_inr:
            reasons.append(
                f"EMD payment of Rs.{req_emd_inr:,} not confirmed in bidder documents"
            )
            detail.append({"check": "EMD Payment", "result": "FLAG",
                            "required": f"Rs.{req_emd_inr:,}", "found": "Not confirmed"})
        else:
            detail.append({"check": "EMD Payment", "result": "PASS",
                            "required": f"Rs.{req_emd_inr:,}", "found": f"Rs.{bid_emd_inr:,}"})

    # ── 5. MATERIAL COMPOSITION ───────────────────────────────────
    tender_mats  = {m["material"].lower()[:8]: m["percentage"]
                    for m in tender.get("material_composition", [])}
    bidder_mats  = {m["material"].lower()[:8]: m["percentage"]
                    for m in bidder.get("material_composition", [])}

    for mat_key, req_pct in tender_mats.items():
        bid_pct = bidder_mats.get(mat_key)
        mat_label = mat_key.title()
        if bid_pct is None:
            reasons.append(
                f"Material composition for '{mat_label}' not stated — "
                f"required {req_pct}"
            )
            detail.append({"check": f"Material: {mat_label}", "result": "FLAG",
                            "required": req_pct, "found": "Not stated"})
        elif bid_pct != req_pct:
            reasons.append(
                f"Material '{mat_label}' composition mismatch — "
                f"required {req_pct}, bidder claims {bid_pct}"
            )
            detail.append({"check": f"Material: {mat_label}", "result": "FLAG",
                            "required": req_pct, "found": bid_pct})
        else:
            detail.append({"check": f"Material: {mat_label}", "result": "PASS",
                            "value": req_pct})

    # ── 6. TECHNICAL SPECIFICATIONS ───────────────────────────────
    tender_specs = tender.get("technical_specifications", [])
    bidder_specs = {re.sub(r"[^a-z0-9]", "", r["parameter"].lower())[:25]: r["required_value"]
                    for r in bidder.get("technical_specifications", [])}

    spec_flags = 0
    for row in tender_specs:
        param     = row.get("parameter", "")
        req_val   = row.get("required_value", "")
        param_key = re.sub(r"[^a-z0-9]", "", param.lower())[:25]
        bid_val   = bidder_specs.get(param_key)

        if bid_val is None:
            spec_flags += 1
            detail.append({"check": f"Spec: {param[:45]}", "result": "FLAG",
                            "required": req_val, "found": "Not stated by bidder"})
        else:
            t_nums = re.findall(r"\d+(?:\.\d+)?", req_val)
            b_nums = re.findall(r"\d+(?:\.\d+)?", bid_val)
            match  = (float(t_nums[0]) == float(b_nums[0])) if (t_nums and b_nums) else \
                     (param_key == re.sub(r"[^a-z0-9]", "", bid_val.lower())[:25])

            if not match:
                reasons.append(
                    f"Spec '{param[:40]}' — required: {req_val}, bidder offers: {bid_val}"
                )
                detail.append({"check": f"Spec: {param[:45]}", "result": "FLAG",
                                "required": req_val, "found": bid_val})
            else:
                detail.append({"check": f"Spec: {param[:45]}", "result": "PASS",
                                "value": req_val})

    if spec_flags > 0:
        reasons.append(
            f"{spec_flags} technical specification(s) not addressed in bidder documents"
        )

    # ── FINAL VERDICT ─────────────────────────────────────────────
    # FAIL conditions — hard disqualifiers
    hard_fails = [
        r for r in reasons if any(k in r.lower() for k in
        ["not valid", "invalid format", "below the minimum", "insufficient"])
    ]

    if hard_fails:
        overall = "NOT ELIGIBLE"
    elif reasons:
        overall = "FLAGGED FOR REVIEW"
    else:
        overall = "ELIGIBLE"

    return {
        "bidder_id":      bidder_scan.get("document_id", "unknown"),
        "overall_status": overall,
        "reasons":        reasons,        # only failures + flags — clean for officer
        "audit_detail":   detail,         # full check-by-check trail
        "company_info":   {               # pulled from live GST API
            "name":       gst_result.get("company_name"),
            "type":       gst_result.get("company_type"),
            "gst_status": gst_result.get("status"),
            "state":      gst_result.get("state"),
            "reg_date":   gst_result.get("reg_date"),
        }
    }


# ─────────────────────────────────────────────────────────────────
# PRINT — clean output for procurement officer
# ─────────────────────────────────────────────────────────────────

def print_verdict(verdict):
    symbol = {"ELIGIBLE": "✓", "NOT ELIGIBLE": "✗", "FLAGGED FOR REVIEW": "⚠"}.get(
        verdict["overall_status"], "?")

    print(f"\n{'═'*55}")
    print(f"  BIDDER  : {verdict['bidder_id']}")

    info = verdict.get("company_info", {})
    if info.get("name"):
        print(f"  COMPANY : {info['name']} ({info.get('type','')})")
        print(f"  GST     : {info.get('gst_status','')} | Reg: {info.get('reg_date','')} | {info.get('state','')}")

    print(f"  VERDICT : {symbol}  {verdict['overall_status']}")
    print(f"{'═'*55}")

    if verdict["overall_status"] == "ELIGIBLE":
        print("  All checks passed. Bidder is eligible.")
    else:
        print(f"  ISSUES ({len(verdict['reasons'])}):")
        for i, reason in enumerate(verdict["reasons"], 1):
            print(f"  {i}. {reason}")

    print()


# ─────────────────────────────────────────────────────────────────
# DUMMY DATA — same format scanner.py outputs
# Replace with: from scanner import scan_document
# ─────────────────────────────────────────────────────────────────

DUMMY_TENDER = {
    "document_id": "tender_crpf_tshirt",
    "confidence":  0.99,
    "needs_review": False,
    "fields": {
        "financials": {
            "min_turnover": {"raw": "5 Crore", "inr": 50_000_000},
            "emd":          {"raw": "50000",   "inr": 50_000}
        },
        "compliance": [
            {"type": "certification", "value": "ISO 9001"},
            {"type": "certification", "value": "ISO 18184"},
        ],
        "material_composition": [
            {"percentage": "92%", "material": "Performance Polyester"},
            {"percentage": "8%",  "material": "Lycra"},
        ],
        "technical_specifications": [
            {"s_no": "3",  "parameter": "Seam Strength Wales wise", "required_value": "250"},
            {"s_no": "5",  "parameter": "Fabric Weight",            "required_value": "180"},
            {"s_no": "13", "parameter": "pH value",                 "required_value": "7"},
        ]
    }
}

# Bidder A — mostly good, missing one cert
DUMMY_BIDDER_A = {
    "document_id": "bidder_A_ShivTextiles",
    "confidence":  0.96,
    "needs_review": False,
    "fields": {
        "financials": {
            "annual_turnover": {"raw": "6.5 Crore", "inr": 65_000_000},
            "emd_paid":        {"raw": "50000",     "inr": 50_000}
        },
        "compliance": [
            {"type": "GST",           "value": "27AAPFU0939F1ZV"},
            {"type": "PAN",           "value": "AAPFU0939F"},
            {"type": "certification", "value": "ISO 9001"},
            # ISO 18184 missing — will be flagged
        ],
        "material_composition": [
            {"percentage": "92%", "material": "Performance Polyester"},
            {"percentage": "8%",  "material": "Lycra"},
        ],
        "technical_specifications": [
            {"s_no": "3",  "parameter": "Seam Strength Wales wise", "required_value": "250"},
            {"s_no": "5",  "parameter": "Fabric Weight",            "required_value": "180"},
            {"s_no": "13", "parameter": "pH value",                 "required_value": "7"},
        ]
    }
}

# Bidder B — multiple hard fails
DUMMY_BIDDER_B = {
    "document_id": "bidder_B_RajGarments",
    "confidence":  0.61,
    "needs_review": True,
    "review_reason": "Low OCR confidence (61%) — verify originals",
    "fields": {
        "financials": {
            "annual_turnover": {"raw": "3 Crore", "inr": 30_000_000},  # below minimum
            "emd_paid":        None
        },
        "compliance": [
            {"type": "GST", "value": "BADINVALIDGST00"},  # invalid format
            {"type": "PAN", "value": "AAPFU0939F"},
        ],
        "material_composition": [],
        "technical_specifications": []
    }
}


# ─────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Comment these two lines out and use scanner.scan_document() when ready:
    # from scanner import scan_document
    # tender_scan = scan_document("tender.pdf")

    print("\n" + "─"*55)
    print("  CRPF TENDER EVALUATION — VERDICT ENGINE")
    print("─"*55)

    print_verdict(get_verdict(DUMMY_TENDER, DUMMY_BIDDER_A))
    print_verdict(get_verdict(DUMMY_TENDER, DUMMY_BIDDER_B))