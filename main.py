"""
main.py — Tender Compliance System
====================================
Wires together scanner.py and verdict.py.

CLI usage (testing):
    python main.py tender.pdf bidder.pdf

Flask usage (deployment):
    gunicorn "main:create_app()"

    POST /scan-tender
        multipart/form-data with field:
            tender  — PDF or image file
        Returns JSON { session_id: "..." }

    POST /compare-bidder
        multipart/form-data with fields:
            session_id — from /scan-tender
            bidder     — PDF or image file
        Returns JSON verdict report.
"""

import os
import sys
import uuid
import tempfile

from scanner import (
    detect_document_type,
    run_step1,
    run_step2,
    run_step3,
)
from verdict import run_verdict


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline helpers
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

    doc_info = run_step1(file_path)

    if doc_info.get("pdf_type") == "SCANNED_PDF":
        print(
            f"\n[INFO] Scanned PDF — {doc_info['total_pages']} total pages. "
            f"OCR limited to first 5 pages for speed."
        )

    extraction_data = run_step2(file_path)
    raw_text = extraction_data["raw_text"]

    if not raw_text.strip():
        raise ValueError(f"No text could be extracted from {label} document.")

    doc_type = detect_document_type(raw_text)
    print(f"\n[INFO] {label} document type detected: {doc_type}")

    structured = run_step3(raw_text, doc_type)

    print(f"\n[INFO] {label} scan complete.")
    return structured


def run_pipeline(tender_path: str, bidder_path: str) -> dict:
    """Full pipeline for CLI: scan both docs, compare, return verdict."""
    tender_data = scan_document(tender_path, "TENDER")
    bidder_data = scan_document(bidder_path, "BIDDER")

    print(f"\n{'='*60}")
    print("  RUNNING VERDICT")
    print(f"{'='*60}")

    return run_verdict(tender_data, bidder_data)


# ─────────────────────────────────────────────────────────────────────────────
# CLI mode
# ─────────────────────────────────────────────────────────────────────────────

def run_cli():
    if len(sys.argv) != 3:
        print("Usage: python main.py <tender_file> <bidder_file>")
        sys.exit(1)

    tender_path, bidder_path = sys.argv[1], sys.argv[2]

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
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

    # In-memory tender cache: { session_id: tender_data_dict }
    # Each entry is populated by /scan-tender and consumed by /compare-bidder.
    # On Render's free tier (single worker) this lives for the process lifetime.
    tender_cache = {}

    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "tiff", "bmp", "webp"}

    def allowed(filename: str) -> bool:
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    def save_upload(file_obj) -> str:
        """Save an uploaded FileStorage to a temp file, return its path."""
        with tempfile.NamedTemporaryFile(
            suffix=f"_{file_obj.filename}", delete=False
        ) as tf:
            file_obj.save(tf.name)
            return tf.name

    def cleanup(*paths):
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    # ── routes ────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/scan-tender", methods=["POST"])
    def scan_tender_endpoint():
        """
        Scan the tender document once and cache the result.
        Returns { session_id } to be passed with every /compare-bidder call.
        """
        if "tender" not in request.files:
            return jsonify({"error": "Tender file is required."}), 400

        tender_file = request.files["tender"]
        if not allowed(tender_file.filename):
            return jsonify({"error": f"Unsupported file type: {tender_file.filename}"}), 400

        tender_path = save_upload(tender_file)
        try:
            tender_data = scan_document(tender_path, "TENDER")
            session_id = str(uuid.uuid4())
            tender_cache[session_id] = tender_data
            return jsonify({"session_id": session_id}), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        except Exception as e:
            return jsonify({"error": f"Internal error: {str(e)}"}), 500
        finally:
            cleanup(tender_path)

    @app.route("/compare-bidder", methods=["POST"])
    def compare_bidder():
        """
        Compare one bidder against the already-scanned tender (by session_id).
        Tender is NOT re-scanned — zero extra tokens spent on it.
        """
        session_id = request.form.get("session_id")
        if not session_id or session_id not in tender_cache:
            return jsonify({"error": "Invalid or expired session. Please re-upload the tender."}), 400

        if "bidder" not in request.files:
            return jsonify({"error": "Bidder file is required."}), 400

        bidder_file = request.files["bidder"]
        if not allowed(bidder_file.filename):
            return jsonify({"error": f"Unsupported file type: {bidder_file.filename}"}), 400

        bidder_path = save_upload(bidder_file)
        try:
            tender_data = tender_cache[session_id]
            bidder_data = scan_document(bidder_path, "BIDDER")

            print(f"\n{'='*60}")
            print("  RUNNING VERDICT")
            print(f"{'='*60}")

            report = run_verdict(tender_data, bidder_data)
            return jsonify(report), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        except Exception as e:
            return jsonify({"error": f"Internal error: {str(e)}"}), 500
        finally:
            cleanup(bidder_path)

    # Keep the old /compare route working for CLI testers / backwards compat
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

        tender_path = save_upload(tender_file)
        bidder_path = save_upload(bidder_file)
        try:
            report = run_pipeline(tender_path, bidder_path)
            return jsonify(report), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        except Exception as e:
            return jsonify({"error": f"Internal error: {str(e)}"}), 500
        finally:
            cleanup(tender_path, bidder_path)

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        run_cli()
    else:
        app = create_app()
        app.run(debug=True, host="0.0.0.0", port=5000)