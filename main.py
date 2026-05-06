"""
main.py — Tender Compliance System
====================================
Wires together scanner.py and verdict.py.

CLI usage (testing):
    python main.py tender.pdf bidder.pdf

Flask usage (deployment):
    python main.py
    → starts a local dev server on http://localhost:5000

    POST /compare
        multipart/form-data with fields:
            tender  — PDF or image file
            bidder  — PDF or image file
        Returns JSON verdict report.
"""

import os
import sys
import json
import tempfile

from scanner import (
    DocumentIdentifier,
    UnifiedExtractor,
    detect_document_type,
    LLMExtractor,
    JSONOutputFormatter,
    run_step1,
    run_step2,
    run_step3,
)
from verdict import VerdictEngine, VerdictFormatter, run_verdict


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline — shared by CLI and Flask
# ─────────────────────────────────────────────────────────────────────────────

def scan_document(file_path: str, label: str) -> dict:
    """
    Run the full scanner pipeline on one document.
    Returns the structured LLM output dict.
    label: "TENDER" or "BIDDER" — used only for console headings.
    """
    print(f"\n{'='*60}")
    print(f"  SCANNING {label}: {os.path.basename(file_path)}")
    print(f"{'='*60}")

    # Step 1 — identify
    doc_info = run_step1(file_path)

    if doc_info.get("pdf_type") == "SCANNED_PDF":
        print(
            f"\n[INFO] Scanned PDF — {doc_info['total_pages']} total pages. "
            f"OCR limited to first 5 pages for speed."
        )

    # Step 2 — extract text
    extraction_data = run_step2(file_path)
    raw_text = extraction_data["raw_text"]

    if not raw_text.strip():
        raise ValueError(f"No text could be extracted from {label} document.")

    # Step 3 — detect type + LLM structured extraction
    doc_type = detect_document_type(raw_text)
    print(f"\n[INFO] {label} document type detected: {doc_type}")

    structured = run_step3(raw_text, doc_type)

    print(f"\n[INFO] {label} scan complete.")
    return structured


def run_pipeline(tender_path: str, bidder_path: str) -> dict:
    """
    Full pipeline: scan both docs, compare, return verdict report.
    """
    tender_data = scan_document(tender_path, "TENDER")
    bidder_data = scan_document(bidder_path, "BIDDER")

    print(f"\n{'='*60}")
    print("  RUNNING VERDICT")
    print(f"{'='*60}")

    report = run_verdict(tender_data, bidder_data)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# CLI mode
# ─────────────────────────────────────────────────────────────────────────────

def run_cli():
    if len(sys.argv) != 3:
        print("Usage: python main.py <tender_file> <bidder_file>")
        sys.exit(1)

    tender_path = sys.argv[1]
    bidder_path = sys.argv[2]

    for path in (tender_path, bidder_path):
        if not os.path.exists(path):
            print(f"[ERROR] File not found: {path}")
            sys.exit(1)

    try:
        run_pipeline(tender_path, bidder_path)
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Flask mode
# ─────────────────────────────────────────────────────────────────────────────

def create_app():
    from flask import Flask, request, jsonify, render_template

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload limit

    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "tiff", "bmp", "webp"}

    def allowed(filename: str) -> bool:
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    # ── routes ────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/compare", methods=["POST"])
    def compare():
        if "tender" not in request.files or "bidder" not in request.files:
            return jsonify({"error": "Both 'tender' and 'bidder' files are required."}), 400

        tender_file = request.files["tender"]
        bidder_file = request.files["bidder"]

        if not allowed(tender_file.filename):
            return jsonify({"error": f"Unsupported tender file type: {tender_file.filename}"}), 400
        if not allowed(bidder_file.filename):
            return jsonify({"error": f"Unsupported bidder file type: {bidder_file.filename}"}), 400

        # Save uploads to temp files — cleaned up automatically after request
        with tempfile.NamedTemporaryFile(
            suffix=f"_{tender_file.filename}", delete=False
        ) as tf:
            tender_file.save(tf.name)
            tender_path = tf.name

        with tempfile.NamedTemporaryFile(
            suffix=f"_{bidder_file.filename}", delete=False
        ) as bf:
            bidder_file.save(bf.name)
            bidder_path = bf.name

        try:
            report = run_pipeline(tender_path, bidder_path)
            return jsonify(report), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        except Exception as e:
            return jsonify({"error": f"Internal error: {str(e)}"}), 500
        finally:
            # Always clean up temp files
            for path in (tender_path, bidder_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        # Arguments passed → CLI mode
        run_cli()
    else:
        # No arguments → Flask dev server
        app = create_app()
        app.run(debug=True, host="0.0.0.0", port=5000)