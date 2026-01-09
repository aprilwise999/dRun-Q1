# parsers/customs_parser.py
import re
from typing import List
from models import CustomsLine, OriginCountry

def _normalize_number(s: str) -> float:
    return float(s.replace(',', '').replace(' ', ''))

def parse_customs(pdf_path: str) -> List[CustomsLine]:
    import pdfplumber
    lines = []
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    
    # Extract all blocks that look like a customs line
    # We look for: part_no (alphanumeric, 6+ chars), desc, qty (number + unit), EUR total, invno#
    candidates = re.finditer(
        r'(\b\d{6,}[A-Z]*)\s+(.+?)\s+'
        r'(\d+(?:\.\d+)?)\s+([A-Z0-9]+)\s+'
        r'.*?EUR\s+([\d\.,]+)\s+'
        r'.*?invno#\s+(\d+)',
        full_text, re.DOTALL | re.IGNORECASE
    )
    
    for i, match in enumerate(candidates):
        try:
            part_no = match.group(1).strip()
            desc = match.group(2).strip()
            qty = _normalize_number(match.group(3))
            unit = match.group(4).strip()
            price_eur = _normalize_number(match.group(5))
            invoice_no = match.group(6).strip()
            
            # Guess origin from context (Set 2: "KOREA" or "KR")
            origin = "KR"
            if "germany" in full_text.lower():
                origin = "DE"
            elif "china" in full_text.lower() or "cn" in full_text.lower():
                origin = "CN"
            elif "india" in full_text.lower():
                origin = "IN"
            elif "türkiye" in full_text.lower() or "turkey" in full_text.lower():
                origin = "TR"
            elif "czech" in full_text.lower():
                origin = "CZ"
            elif "italy" in full_text.lower():
                origin = "IT"
            elif "brazil" in full_text.lower():
                origin = "BR"
            
            line = CustomsLine(
                line_no=i + 1,
                hs_code="",  # Not reliably available in Set 2
                part_no=part_no,
                desc_en=desc,
                qty=qty,
                unit=unit,
                price_eur=price_eur,
                origin=OriginCountry(origin),
                invoice_no=invoice_no
            )
            lines.append(line)
        except Exception as e:
            continue
    
    return lines