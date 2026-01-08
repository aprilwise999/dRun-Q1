# bl_parser.py
import re
import pdfplumber
from typing import List
from models import BLLine

class BLParser:
    def parse(self, pdf_path: str) -> BLLine:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            return self._parse_generic(full_text)

    def _parse_generic(self, text: str) -> BLLine:
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # B/L Number (fallback: filename or marks)
        bl_no = ""
        bl_match = re.search(r"(B/L\s+No\.:\s*(\S+))|(HAHS\d+)|(ANRBKK\s+[\d/\-]+)", text, re.IGNORECASE)
        if bl_match:
            bl_no = (bl_match.group(2) or bl_match.group(3) or bl_match.group(4)).replace("/", "-")

        # Vessel & Voyage
        vessel = voyage = ""
        vessel_match = re.search(r"(KMTC SINGAPORE|BERLIN EXPRESS|XIN YANG PU)[^\n]*\(([^)]+)\)", text, re.IGNORECASE)
        if vessel_match:
            vessel = vessel_match.group(1).strip()
            voyage = vessel_match.group(2).strip()

        # ETD
        etd = ""
        etd_match = re.search(r"(ETD|Sailing on or about|LADEN ON BOARD)[^\d]*(\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}/\d{1,2}/\d{4})", text, re.IGNORECASE)
        if etd_match:
            etd = etd_match.group(2)

        # Weight & Packages
        gross_kg = 0.0
        packages = 0
        gross_match = re.search(r"(\d+(?:,\d+)*)\s*(?:KGS|KG|KGM)", text, re.IGNORECASE)
        if gross_match:
            gross_kg = float(gross_match.group(1).replace(",", ""))
        pack_match = re.search(r"(\d+)\s+(?:PALLETS?|PACKAGE|CARTON)", text, re.IGNORECASE)
        if pack_match:
            packages = int(pack_match.group(1))

        # Marks — critical for group linking
        marks = []
        # Strategy 1: dedicated "Marks and numbers" section
        marks_match = re.search(r"(Marks and numbers|MARKS:)\s*([^\n]{20,})", text, re.IGNORECASE)
        if marks_match:
            marks_text = marks_match.group(2).strip()
            # Split by likely delimiters
            for m in re.split(r"\s*;\s*|\s{2,}", marks_text):
                if len(m) > 10 and "BANGKOK" in m:
                    marks.append(m.strip())
        # Strategy 2: lines with supplier + POT + delivery ID
        for line in text.split("\n"):
            if any(kw in line.upper() for kw in ["FEBI", "SWAG", "ZF"]) and "POT" in line and "BANGKOK" in line:
                marks.append(line.strip())

        # Shipper & Consignee
        shipper = consignee = ""
        shipper_match = re.search(r"(Shipper|Consignee)[^\n]*\n([^\n]{20,})", text, re.IGNORECASE)
        if shipper_match:
            shipper = shipper_match.group(2).strip()
        consignee_match = re.search(r"Consignee[^\n]*\n([^\n]{20,})", text, re.IGNORECASE)
        if consignee_match:
            consignee = consignee_match.group(1).strip()

        return BLLine(
            bl_no=bl_no,
            vessel=vessel,
            voyage=voyage,
            etd=etd,
            gross_kg=gross_kg,
            packages=packages,
            marks=marks,
            shipper=shipper,
            consignee=consignee,
        )