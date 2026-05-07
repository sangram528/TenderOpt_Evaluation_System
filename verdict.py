

import os
import re
import json
from datetime import datetime
from difflib import SequenceMatcher

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

CRITICAL_FIELDS = {
    "emd_amount",
    "estimated_cost",
    "budget",
    "submission_deadline",
    "delivery_period",
    "quantity",
    "eligibility",
    "key_performance_specs",
    "materials_required",
}

NUMERIC_FIELDS = {
    "emd_amount",
    "estimated_cost",
    "budget",
    "quantity",
    "fabric_weight",
}

DATE_FIELDS = {
    "submission_deadline",
    "opening_date",
    "date_of_issue",
}


_LAKH  = 1_00_000
_CRORE = 1_00_00_000

def _parse_amount(value: str) -> float | None:
    """
    Convert messy Indian-currency strings to a plain float.
    Handles: ₹, Rs., commas, lakh/lakhs, crore/crores, L, Cr.

    Returns None if the string cannot be parsed.
    """
    if not value:
        return None

    s = str(value).lower().strip()
    s = s.replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "")
    s = s.strip()

    multiplier = 1
    if re.search(r"crore|cr\b", s):
        multiplier = _CRORE
    elif re.search(r"lakh|lac\b|l\b", s):
        multiplier = _LAKH


    m = re.search(r"[\d]+(?:\.\d+)?", s)
    if not m:
        return None

    try:
        return float(m.group()) * multiplier
    except ValueError:
        return None


def _amounts_match(a: str, b: str, tolerance: float = 0.01) -> bool:
    """
    True if two amount strings refer to the same number within `tolerance`
    fractional difference (default 1 %).
    """
    na, nb = _parse_amount(a), _parse_amount(b)
    if na is None or nb is None:
        return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio() > 0.85
    if na == 0 and nb == 0:
        return True
    if na == 0 or nb == 0:
        return False
    return abs(na - nb) / max(abs(na), abs(nb)) <= tolerance



_DATE_FORMATS = [
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
    "%B %d, %Y", "%b %d, %Y",
    "%Y-%m-%d",
]

def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _dates_match(a: str, b: str) -> bool:
    da, db = _parse_date(a), _parse_date(b)
    if da and db:
        return da.date() == db.date()
    # Fall back to string fuzzy if parsing fails
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio() > 0.85


def _llm_compare_fields(pairs: list[dict], client: Groq) -> list[dict]:
    """
    Send a batch of field-pairs to the LLM and get back a match/mismatch
    verdict with a brief reason for each.

    pairs: [{"field": "work_name", "tender": "...", "bidder": "..."}, ...]

    Returns the same list with "match" (bool) and "reason" (str) added.
    """
    if not pairs:
        return []

    system_msg = (
        "You are a tender compliance auditor. You will receive a JSON array of "
        "field comparisons between a government tender document and a bidder's "
        "response document. For each entry decide whether the bidder's value "
        "semantically matches the tender's value — allow for paraphrasing, "
        "abbreviations, and minor formatting differences, but flag genuine "
        "discrepancies in meaning, scope, or requirement.\n\n"
        "Return ONLY a JSON array (same order, same length) where each element "
        "has exactly two keys:\n"
        '  "match": true or false\n'
        '  "reason": one concise sentence explaining the decision\n'
        "No markdown, no extra keys, no preamble."
    )

    user_msg = json.dumps(pairs, ensure_ascii=False, indent=2)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.0,
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        verdicts = json.loads(raw)
    except Exception:
        verdicts = [
            {"match": False, "reason": "LLM output could not be parsed — manual review required."}
            for _ in pairs
        ]

    
    for pair, verdict in zip(pairs, verdicts):
        pair["match"]  = verdict.get("match", False)
        pair["reason"] = verdict.get("reason", "No reason provided.")

    return pairs




class VerdictEngine:

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not set. Add it to your .env file:\n"
                "  GROQ_API_KEY=gsk_..."
            )
        self.client = Groq(api_key=api_key)


    def compare(self, tender: dict, bidder: dict) -> dict:
        """
        Compare tender and bidder dicts (both from scanner.py output).
        Returns a structured verdict report.
        """
        conflicts      = []   # critical mismatches
        notes          = []   # informational mismatches
        text_pairs     = []   # queued for LLM batch call
        python_results = []   # already decided by Python logic

        all_fields = set(tender.keys()) | set(bidder.keys())

        for field in sorted(all_fields):
            t_val = tender.get(field)
            b_val = bidder.get(field)
            is_critical = field in CRITICAL_FIELDS
            
            if self._is_empty(t_val) and self._is_empty(b_val):
                continue

            if self._is_empty(t_val) or self._is_empty(b_val):
                entry = {
                    "field":    field,
                    "tender":   self._display(t_val),
                    "bidder":   self._display(b_val),
                    "reason":   "Field present in one document but missing in the other.",
                    "critical": is_critical,
                }
                (conflicts if is_critical else notes).append(entry)
                continue

            if field in NUMERIC_FIELDS:
                match = _amounts_match(str(t_val), str(b_val))
                python_results.append({
                    "field":    field,
                    "tender":   self._display(t_val),
                    "bidder":   self._display(b_val),
                    "match":    match,
                    "reason":   "Numeric values match within 1% tolerance." if match
                                else f"Numeric mismatch: tender={t_val}, bidder={b_val}.",
                    "critical": is_critical,
                })
                continue

            if field in DATE_FIELDS:
                match = _dates_match(str(t_val), str(b_val))
                python_results.append({
                    "field":    field,
                    "tender":   self._display(t_val),
                    "bidder":   self._display(b_val),
                    "match":    match,
                    "reason":   "Dates match." if match
                                else f"Date mismatch: tender={t_val}, bidder={b_val}.",
                    "critical": is_critical,
                })
                continue
            
            text_pairs.append({
                "field":    field,
                "tender":   self._display(t_val),
                "bidder":   self._display(b_val),
                "critical": is_critical,
            })

        if text_pairs:
            _llm_compare_fields(text_pairs, self.client)

        for result in python_results + text_pairs:
            if not result.get("match", True):
                target = conflicts if result["critical"] else notes
                target.append({
                    "field":    result["field"],
                    "tender":   result["tender"],
                    "bidder":   result["bidder"],
                    "reason":   result["reason"],
                    "critical": result["critical"],
                })

        status = "FLAGGED" if conflicts else "PASSED"

        return {
            "verdict":   status,
            "conflicts": conflicts,   # critical mismatches — need manual review
            "notes":     notes,       # informational mismatches — softer
            "summary":   self._summary(status, conflicts, notes),
        }


    @staticmethod
    def _is_empty(val) -> bool:
        if val is None:
            return True
        if isinstance(val, str) and val.strip() in ("", "null", "None"):
            return True
        if isinstance(val, (list, dict)) and not val:
            return True
        return False

    @staticmethod
    def _display(val) -> str:
        if val is None:
            return "—"
        if isinstance(val, (list, dict)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    @staticmethod
    def _summary(status: str, conflicts: list, notes: list) -> str:
        if status == "PASSED":
            if notes:
                return (
                    f"Bidder PASSED. No critical mismatches found. "
                    f"{len(notes)} minor informational discrepancy(ies) noted."
                )
            return "Bidder PASSED. All fields match the tender requirements."
        return (
            f"Bidder FLAGGED for manual review. "
            f"{len(conflicts)} critical conflict(s) and "
            f"{len(notes)} informational discrepancy(ies) found."
        )


class VerdictFormatter:

    def display(self, report: dict):
        verdict = report["verdict"]
        print("\n" + "=" * 60)
        print(f"  VERDICT: {verdict}")
        print("=" * 60)
        print(f"\n  {report['summary']}\n")

        if report["conflicts"]:
            print("── CRITICAL CONFLICTS (manual review required) ──────────────")
            for i, c in enumerate(report["conflicts"], 1):
                print(f"\n  [{i}] Field     : {c['field']}")
                print(f"      Tender    : {c['tender']}")
                print(f"      Bidder    : {c['bidder']}")
                print(f"      Reason    : {c['reason']}")

        if report["notes"]:
            print("\n── INFORMATIONAL NOTES ──────────────────────────────────────")
            for i, n in enumerate(report["notes"], 1):
                print(f"\n  [{i}] Field     : {n['field']}")
                print(f"      Tender    : {n['tender']}")
                print(f"      Bidder    : {n['bidder']}")
                print(f"      Reason    : {n['reason']}")

        print("\n" + "=" * 60 + "\n")




def run_verdict(tender_data: dict, bidder_data: dict) -> dict:
    engine    = VerdictEngine()
    report    = engine.compare(tender_data, bidder_data)
    VerdictFormatter().display(report)
    return report


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python verdict.py tender_output.json bidder_output.json")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        tender_json = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        bidder_json = json.load(f)

    run_verdict(tender_json, bidder_json)