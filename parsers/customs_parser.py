# customs_parser.py
import re
import pdfplumber
from typing import List
from models import CustomsLine, OriginCountry

# Robust regex for ใบขนฯ — handles Thai/English mix, space variations
LINE_RE = re.compile(
    r'^\s*(\d+)\s+'                          # line_no
    r'([\d\.]+)\s+'                          # hs_code
    r'.*?'                                  
    r'\s(\d+[A-Z]*)\s+([A-Z\s]+?)\s+'       # part_no + desc_en (non-greedy)
    r'([\d\.,]+)\s+([A-Z0-9]+)\s+'          # qty + unit
    r'.*?EUR\s+([\d\.,]+)\s+'               # price_eur
    r'.*?(?:FEBI|SWAG|ZF)\s+([A-Z]{2})\s+'  # origin (DE, CN, etc.)
    r'invno#\s+(\d+)',                       # invoice_no
    re.MULTILINE | re.IGNORECASE
)

def _normalize_number(s: str) -> float:
    return float(s.replace(',', '').replace(' ', ''))

def extract_full_text(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(x_tolerance=1, y_tolerance=1) or ""
            text += page_text + "\n"
    return text

def parse_customs(pdf_path: str) -> List[CustomsLine]:
    lines = []
    text = extract_full_text(pdf_path)

    for match in LINE_RE.finditer(text):
        try:
            line = CustomsLine(
                line_no=int(match.group(1)),
                hs_code=match.group(2).strip(),
                part_no=match.group(3).strip(),
                desc_en=match.group(4).strip(),
                qty=_normalize_number(match.group(5)),
                unit=match.group(6).strip(),
                price_eur=_normalize_number(match.group(7)),
                origin=OriginCountry(match.group(8).strip()),
                invoice_no=match.group(9).strip()
            )
            lines.append(line)
        except (ValueError, KeyError) as e:
            print(f"⚠️ Skipping line {match.group(1)}: {e}")
            continue
    return lines