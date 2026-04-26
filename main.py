
import os
import sys
import json
import shutil
import tempfile
import uvicorn

from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

# Import our two modules
from scanner import TenderScanner
from verdict import get_verdict


# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────

app = FastAPI(title="CRPF Tender Evaluation API")

# Serve CSS, JS from project folder directly
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")

@app.get("/style.css")
def serve_css():
    return FileResponse("style.css", media_type="text/css")

@app.get("/app.js")
def serve_js():
    return FileResponse("app.js", media_type="application/javascript")


# ─────────────────────────────────────────────
# API ENDPOINT
# ─────────────────────────────────────────────

@app.post("/api/evaluate")
async def evaluate(
    tender: UploadFile = File(...),
    bidders: list[UploadFile] = File(...)
):
    """
    Receives:
      - tender  : one PDF file (the tender document)
      - bidders : one or more PDF files (bidder submissions)

    Returns:
      JSON in the exact format the frontend expects
    """

    # Use a temp folder so files are cleaned up automatically
    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Save uploaded files to disk ───────────────────────────
        tender_path = os.path.join(tmpdir, tender.filename)
        with open(tender_path, "wb") as f:
            shutil.copyfileobj(tender.file, f)

        bidder_paths = []
        for bidder_file in bidders:
            path = os.path.join(tmpdir, bidder_file.filename)
            with open(path, "wb") as f:
                shutil.copyfileobj(bidder_file.file, f)
            bidder_paths.append((bidder_file.filename, path))

        # ── Scan the tender ───────────────────────────────────────
        scanner = TenderScanner()

        try:
            tender_data = scanner.extract_from_pdf(tender_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not scan tender: {e}")

        # ── Scan each bidder + get verdict ────────────────────────
        bidder_results = []

        for bidder_name, bidder_path in bidder_paths:
            try:
                bidder_data = scanner.extract_from_pdf(bidder_path)
                verdict     = get_verdict(tender_data, bidder_data, bidder_name=bidder_name)
                bidder_results.append(verdict)

            except Exception as e:
                # Never crash the whole evaluation because of one bad file
                # Flag it and move on
                bidder_results.append({
                    "bidder_id":      bidder_name,
                    "overall_status": "FLAGGED FOR REVIEW",
                    "reasons":        [f"Could not process file: {str(e)}"],
                    "audit_detail":   [{
                        "check":    "File Processing",
                        "result":   "FLAG",
                        "required": "Readable PDF",
                        "found":    "Error during scan",
                        "note":     str(e)
                    }],
                    "company_info": {}
                })

        # ── Build response in the format frontend expects ─────────
        response = build_frontend_response(tender_data, bidder_results)
        return JSONResponse(content=response)


# ─────────────────────────────────────────────
# RESPONSE BUILDER
# Maps scanner + verdict output → frontend JSON shape
# ─────────────────────────────────────────────

def build_frontend_response(tender_data, bidder_verdicts):
    """
    Converts raw scanner + verdict output into the exact JSON
    shape that app.js renderResults() expects.
    """

    # Count total unique criteria from tender
    criteria_count = len(tender_data.get("materials_required", []))

    # Build the tender summary strip
    tender_summary = {
        "title":          _get_tender_title(tender_data),
        "authority":      tender_data.get("issuing_authority", "Not stated"),
        "criteria_count": criteria_count,
        "bidder_count":   len(bidder_verdicts),
        "estimated_cost": _format_budget(tender_data.get("budget")),
    }

    # Build per-bidder cards
    bidders = []
    for verdict in bidder_verdicts:
        bidders.append({
            "bidder_id":      verdict["bidder_id"],
            "overall_status": verdict["overall_status"],
            "reasons":        verdict["reasons"],
            "company_info":   verdict.get("company_info", {}),
            "audit_detail":   verdict.get("audit_detail", []),
        })

    return {
        "tender":  tender_summary,
        "bidders": bidders,
    }


def _get_tender_title(tender_data):
    """Pull a clean title from the tender's materials list."""
    materials = tender_data.get("materials_required", [])
    if materials:
        first_item = materials[0].get("item", "")
        if first_item:
            return first_item[:80]
    return tender_data.get("issuing_authority", "Tender Document")


def _format_budget(budget_str):
    """Format a raw budget number into a readable string."""
    if not budget_str or budget_str in ("0", "0.00", ""):
        return None
    try:
        val = float(str(budget_str).replace(",", ""))
        if val >= 10_000_000:
            return f"₹{val/10_000_000:.2f} Cr"
        elif val >= 100_000:
            return f"₹{val/100_000:.2f} L"
        else:
            return f"₹{val:,.0f}"
    except Exception:
        return str(budget_str)


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "─"*50)
    print("  CRPF Tender Evaluation System")
    print("─"*50)
    print("  Server : http://localhost:8000")
    print("  UI     : http://localhost:8000")
    print("  API    : http://localhost:8000/api/evaluate")
    print("─"*50)
    print("  Put index.html, style.css, app.js")
    print("  in the same folder as main.py")
    print("─"*50 + "\n")

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)