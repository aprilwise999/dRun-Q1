import re
from typing import Dict, Set, Tuple, Optional
from rapidfuzz import fuzz
from models import CustomsLine, InvoiceLine

# === UNIT NORMALIZATION ===
UNIT_MAP = {
    "C62": "PCS", "PCE": "PCS", "PCS": "PCS", "PCE.": "PCS", "PCE": "PCS",
    "LTR": "L", "LITER": "L", "LITRE": "L", "LITERS": "L",
    "KGM": "KG", "KG": "KG", "KGS": "KG",
    "CARTON": "CTN", "CTN": "CTN", "CARTONS": "CTN", "CTNS": "CTN",
    "PALLET": "PLT", "PALLETS": "PLT", "PLT": "PLT"
}

# === ORIGIN NORMALIZATION ===
ORIGIN_TO_ISO = {
    # Full names → ISO 2-letter
    "GERMANY": "DE",
    "DE": "DE",
    "PEOPLE'S REPUBLIC OF CHINA": "CN",
    "CHINA": "CN",
    "CN": "CN",
    "INDIA": "IN",
    "IN": "IN",
    "TÜRKIYE": "TR",
    "TURKEY": "TR",
    "TR": "TR",
    "CZECH REPUBLIC": "CZ",
    "CZECHIA": "CZ",
    "CZ": "CZ",
    "ITALY": "IT",
    "IT": "IT",
    "BRAZIL": "BR",
    "BR": "BR",
    "KOREA, REPUBLIC OF": "KR",
    "SOUTH KOREA": "KR",
    "KOREA": "KR",
    "KR": "KR",
    "THAILAND": "TH",
    "TH": "TH"
}

# === PART NUMBER EXTRACTION ===
def extract_part_number(s: str) -> str:
    """
    Extract leading alphanumeric part number (e.g., '577004H900', '30329')
    """
    match = re.match(r"^([A-Z]*\d+[A-Z]*)", s.strip().upper())
    return match.group(1) if match else ""

# === FUZZY DESC MATCHER ===
def desc_match_score(desc1: str, desc2: str, threshold: float = 85.0) -> Tuple[bool, float]:
    s1 = re.sub(r"[^A-Z0-9\s]", "", desc1.upper()).strip()
    s2 = re.sub(r"[^A-Z0-9\s]", "", desc2.upper()).strip()
    # Remove common filler words
    for w in ["ASS", "ASSY", "KIT", "SET", "PART", "COMPONENT"]:
        s1 = s1.replace(w, "")
        s2 = s2.replace(w, "")
    s1 = re.sub(r"\s+", " ", s1).strip()
    s2 = re.sub(r"\s+", " ", s2).strip()
    if not s1 or not s2:
        return False, 0.0
    score = fuzz.token_sort_ratio(s1, s2)
    return score >= threshold, score

# === MATCHING LOGIC ===
def match_line(inv_line: InvoiceLine, cust_line: CustomsLine) -> Dict[str, any]:
    """
    Returns dict:
    {
      "match": bool,
      "status": "ok" | "warn" | "error",
      "details": { field_name: { "match": bool, "value1": ..., "value2": ..., "issue": str } }
    }
    """
    details = {}
    status = "ok"  # default

    # 1. Part Number ✅ Critical
    inv_pn = extract_part_number(inv_line.part_no)
    cust_pn = extract_part_number(cust_line.part_no)
    pn_match = inv_pn == cust_pn and len(inv_pn) > 0
    details["part_no"] = {
        "match": pn_match,
        "value1": inv_pn,
        "value2": cust_pn,
        "issue": "" if pn_match else "Part number mismatch"
    }
    if not pn_match:
        status = "error"

    # 2. Description 🟡 Fuzzy
    desc_ok, desc_score = desc_match_score(inv_line.desc_en, cust_line.desc_en)
    details["desc_en"] = {
        "match": desc_ok,
        "value1": inv_line.desc_en,
        "value2": cust_line.desc_en,
        "issue": "" if desc_ok else f"Fuzzy match ({desc_score:.1f}%)"
    }
    if not desc_ok and status == "ok":
        status = "warn"

    # 3. Quantity ✅ Critical (with unit normalization)
    inv_qty = inv_line.qty
    cust_qty = cust_line.qty
    inv_unit = UNIT_MAP.get(inv_line.unit.upper(), inv_line.unit.upper())
    cust_unit = UNIT_MAP.get(cust_line.unit.upper(), cust_line.unit.upper())
    qty_match = abs(inv_qty - cust_qty) < 1e-3 and inv_unit == cust_unit
    details["qty"] = {
        "match": qty_match,
        "value1": f"{inv_qty} {inv_line.unit}",
        "value2": f"{cust_qty} {cust_line.unit}",
        "issue": "" if qty_match else "Qty or unit mismatch"
    }
    if not qty_match:
        status = "error"

    # 4. Total EUR ✅ Critical
    inv_total = inv_line.total_eur
    cust_total = cust_line.price_eur
    total_match = abs(inv_total - cust_total) <= 0.05  # tolerance THB ~1.8
    details["total_eur"] = {
        "match": total_match,
        "value1": inv_total,
        "value2": cust_total,
        "issue": "" if total_match else f"Diff: {abs(inv_total - cust_total):.2f}"
    }
    if not total_match:
        status = "error"

    # 5. Origin ✅ Critical
    inv_origin = ORIGIN_TO_ISO.get(inv_line.origin_raw.upper(), "")
    cust_origin = cust_line.origin.value
    origin_match = inv_origin == cust_origin
    details["origin"] = {
        "match": origin_match,
        "value1": inv_line.origin_raw,
        "value2": cust_origin,
        "issue": "" if origin_match else "Origin mismatch"
    }
    if not origin_match:
        status = "error"

    # 6. HS Code (Optional) 🟡 Warn only
    hs_match = cust_line.hs_code == getattr(inv_line, "hs_code", "")
    if not hs_match:
        details["hs_code"] = {
            "match": False,
            "value1": getattr(inv_line, "hs_code", "—"),
            "value2": cust_line.hs_code,
            "issue": "HS code differs (Customs vs Invoice)"
        }
        if status == "ok":
            status = "warn"

    return {
        "match": status == "ok",
        "status": status,  # "ok", "warn", "error"
        "details": details
    }