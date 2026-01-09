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
    
    # --- Set 1: FEBI/SWAG-style (with clear line numbers and structure) ---
    set1_pattern = re.compile(
        r'^\s*(\d+)\s+([\d\.]+)\s+.*?(\d+[A-Z]*)\s+([A-Z\s]{5,}?)\s+([\d\.,]+)\s+([A-Z0-9]+)\s+.*?EUR\s+([\d\.,]+)\s+.*?(?:FEBI|SWAG|ZF)\s+([A-Z]{2})\s+invno#\s+(\d+)',
        re.MULTILINE | re.IGNORECASE
    )
    
    # --- Set 2: ZF Korea-style (no line number, part# on its own line) ---
    set2_pattern = re.compile(
        r'(\d{6,}[A-Z]*)\s+(.+?)\s+'
        r'(\d+(?:\.\d+)?)\s+([A-Z0-9]+)\s+'
        r'.*?EUR\s+([\d\.,]+)\s+'
        r'.*?invno#\s+(\d+)\s+'
        r'(?:.*?(?:MADE IN|ประเทศก[A-Z]{2}น|KOREA|GERMANY|CHINA|INDIA|TURKEY|CZECH|ITALY|BRAZIL))?.*?'
        r'([A-Z]{2})',
        re.DOTALL | re.IGNORECASE
    )
    
    # Try Set 1 first
    for match in set1_pattern.finditer(full_text):
        try:
            lines.append(CustomsLine(
                line_no=int(match.group(1)),
                hs_code=match.group(2).strip(),
                part_no=match.group(3).strip(),
                desc_en=match.group(4).strip(),
                qty=_normalize_number(match.group(5)),
                unit=match.group(6).strip(),
                price_eur=_normalize_number(match.group(7)),
                origin=OriginCountry(match.group(8).strip()),
                invoice_no=match.group(9).strip()
            ))
        except Exception:
            continue
    
    # If no Set 1 found, try Set 2
    if not lines:
        for match in set2_pattern.finditer(full_text):
            try:
                part_no = match.group(1).strip()
                desc = match.group(2).strip()
                qty = _normalize_number(match.group(3))
                unit = match.group(4).strip()
                price_eur = _normalize_number(match.group(5))
                invoice_no = match.group(6).strip()
                origin_str = (match.group(7) or "KR").strip().upper()
                
                # Map common non-ISO to ISO
                origin_map = {
                    "KOREA": "KR", "SOUTH KOREA": "KR", "REPUBLIC OF KOREA": "KR",
                    "GERMANY": "DE", "DEUTSCHLAND": "DE",
                    "CHINA": "CN", "PEOPLE'S REPUBLIC OF CHINA": "CN",
                    "INDIA": "IN",
                    "TURKEY": "TR", "TÜRKIYE": "TR",
                    "CZECH": "CZ", "CZECHIA": "CZ", "CZECH REPUBLIC": "CZ",
                    "ITALY": "IT",
                    "BRAZIL": "BR"
                }
                origin = origin_map.get(origin_str, origin_str)
                if origin not in [e.value for e in OriginCountry]:
                    origin = "KR"  # fallback for ZF Korea
                
                lines.append(CustomsLine(
                    line_no=1,
                    hs_code="",  # Not always available in Set 2
                    part_no=part_no,
                    desc_en=desc,
                    qty=qty,
                    unit=unit,
                    price_eur=price_eur,
                    origin=OriginCountry(origin),
                    invoice_no=invoice_no
                ))
            except Exception:
                continue
    
    return lines