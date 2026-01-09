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
    
    # Handle Set 1 format (FEBI/SWAG)
    set1_pattern = re.compile(
        r'^\s*(\d+)\s+([\d\.]+)\s+.*?(\d+[A-Z]*)\s+([A-Z\s]{5,}?)\s+([\d\.,]+)\s+([A-Z0-9]+)\s+.*?EUR\s+([\d\.,]+)\s+.*?(?:FEBI|SWAG|ZF)\s+([A-Z]{2})\s+invno#\s+(\d+)',
        re.MULTILINE | re.IGNORECASE
    )
    
    # Handle Set 2 format (ZF Korea) — more flexible
    set2_pattern = re.compile(
        r'(\d{6,}[A-Z]*)\s+(.+?)\s+'
        r'(\d+(?:\.\d+)?)\s+([\d\.,]+)\s+KGM\s+\d+\s+'
        r'(\d+(?:\.\d+)?)%\s+'
        r'(\d+(?:\.\d+)?)\s+([A-Z0-9]+)\s+'
        r'0\.00\s+([\d\.,]+)\s+[\d\.,]+\s+'
        r'[A-Z0-9]+\s+([A-Z]{2})\s+'
        r'invno#\s+(\d+)',
        re.DOTALL
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
        except:
            continue
    
    # If no Set 1 lines found, try Set 2
    if not lines:
        for match in set2_pattern.finditer(full_text):
            try:
                lines.append(CustomsLine(
                    line_no=1,
                    hs_code="",  # Not clearly available in Set 2
                    part_no=match.group(1).strip(),
                    desc_en=match.group(2).strip(),
                    qty=_normalize_number(match.group(6)),  # C62 quantity
                    unit=match.group(7).strip(),  # e.g., C62
                    price_eur=_normalize_number(match.group(8)),
                    origin=OriginCountry(match.group(9).strip()),
                    invoice_no=match.group(10).strip()
                ))
            except:
                continue
    
    return lines