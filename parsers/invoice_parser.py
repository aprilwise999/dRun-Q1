# invoice_parser.py
import re
import pdfplumber
from typing import List, Optional
from models import InvoiceLine, OriginCountry

class InvoiceParser:
    def __init__(self):
        self.supplier_patterns = {
            "FEBI": self._parse_febi,
            "SWAG": self._parse_swag,
            "ZF": self._parse_zf,
            "DEFAULT": self._parse_generic,
        }

    def detect_supplier(self, text: str) -> str:
        u = text.upper()
        if "FEBI" in u or "SWAG" in u:
            return "FEBI"  # SWAG uses same layout
        if "ZF SERVICES" in u or "KOREA" in u:
            return "ZF"
        return "DEFAULT"

    def parse(self, pdf_path: str) -> List[InvoiceLine]:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            supplier = self.detect_supplier(full_text)

            parser = self.supplier_patterns.get(supplier, self._parse_generic)
            try:
                lines = parser(pdf, full_text)
                if lines:
                    for line in lines:
                        line.supplier = supplier
                    return lines
            except Exception as e:
                print(f"⚠️ {supplier} parser failed: {e}")

            # Fallback
            lines = self._parse_generic(pdf, full_text)
            for line in lines:
                line.supplier = "GENERIC"
            return lines

    # --- SUPPLIER-SPECIFIC PARSERS ---

    def _parse_febi(self, pdf, full_text: str) -> List[InvoiceLine]:
        lines = []
        current_delivery = ""
        current_order = ""

        for page in pdf.pages:
            text = page.extract_text() or ""
            # Extract group headers
            del_match = re.search(r"Delivery No\.\s*:\s*(\d+)", text)
            ord_match = re.search(r"Order No\.\s*:\s*(\d+)", text)
            if del_match:
                current_delivery = del_match.group(1)
            if ord_match:
                current_order = ord_match.group(1)

            # Table extraction first
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "text",
                "snap_tolerance": 2,
            })
            if table and len(table) > 2:
                for row in table[1:]:
                    if not row or len(row) < 5:
                        continue
                    # Skip summary rows
                    if "Amount brought forward" in str(row):
                        continue
                    # Try structured
                    try:
                        raw_desc = row[1] or ""
                        part_match = re.match(r"^(\d+[A-Z]?)\s+", raw_desc)
                        part_no = part_match.group(1) if part_match else ""
                        desc_en = re.sub(r"^\d+[A-Z]?\s+", "", raw_desc).strip()

                        qty_str = row[3] or ""
                        qty_match = re.search(r"(\d+)\s+PCE", qty_str)
                        qty = int(qty_match.group(1)) if qty_match else 1

                        unit_price_str = row[4].split()[0] if row[4] else "0"
                        total_eur_str = row[5] or "0"

                        origin_raw = ""
                        for cell in row:
                            if cell and "Country of origin:" in cell:
                                origin_raw = cell.split(":", 1)[1].strip()
                                break

                        line = InvoiceLine(
                            line_no=len(lines) + 1,
                            part_no=part_no,
                            desc_en=desc_en,
                            qty=qty,
                            unit="PCE",
                            unit_price=float(unit_price_str.replace(',', '.')),
                            total_eur=float(total_eur_str.replace(',', '.')),
                            origin_raw=origin_raw,
                            delivery_no=current_delivery,
                            order_no=current_order,
                        )
                        lines.append(line)
                        continue
                    except (IndexError, ValueError, AttributeError):
                        pass

            # Fallback: regex line-by-line
            page_lines = (page.extract_text_lines() or [])
            for pline in page_lines:
                line_text = pline["text"]
                if re.match(r"\d+/\d+\s+\d+[A-Z]", line_text):
                    try:
                        parts = re.split(r"\s{2,}", line_text)
                        if len(parts) < 5:
                            continue
                        part_no = parts[1].split()[0] if parts[1] else ""
                        desc_en = " ".join(parts[1].split()[1:]) if parts[1] else ""
                        qty = int(re.search(r"(\d+)\s+PCE", parts[2]).group(1))
                        unit_price = float(parts[3].split()[0].replace(',', '.'))
                        total_eur = float(parts[4].replace(',', '.'))
                        origin_raw = "Germany" if "DE" in text else "People's Republic of China"

                        line = InvoiceLine(
                            line_no=len(lines) + 1,
                            part_no=part_no,
                            desc_en=desc_en,
                            qty=qty,
                            unit="PCE",
                            unit_price=unit_price,
                            total_eur=total_eur,
                            origin_raw=origin_raw,
                            delivery_no=current_delivery,
                            order_no=current_order,
                        )
                        lines.append(line)
                    except:
                        continue
        return lines

    _parse_swag = _parse_febi  # Identical layout

    def _parse_zf(self, pdf, full_text: str) -> List[InvoiceLine]:
        # ZF: compact single-item format
        lines = []
        # Find part line: "577004H900 GEAR& TIE ROD END ASS 60 120.87 7,252.20"
        match = re.search(
            r"(\d+[A-Z]*)\s+([A-Z\s&]+)\s+(\d+)\s+([\d,\.]+)\s+([\d,\.]+)", 
            full_text, re.IGNORECASE
        )
        if match:
            part_no = match.group(1).strip()
            desc_en = match.group(2).strip()
            qty = int(match.group(3))
            unit_price = float(match.group(4).replace(',', ''))
            total_eur = float(match.group(5).replace(',', ''))
            origin_match = re.search(r"MADE IN ([A-Z]+)", full_text)
            origin_raw = origin_match.group(1).strip() if origin_match else "KOREA"

            line = InvoiceLine(
                line_no=1,
                part_no=part_no,
                desc_en=desc_en,
                qty=qty,
                unit="PCS",
                unit_price=unit_price,
                total_eur=total_eur,
                origin_raw=origin_raw,
            )
            lines.append(line)
        return lines

    def _parse_generic(self, pdf, full_text: str) -> List[InvoiceLine]:
        # Fallback for unknown formats
        lines = []
        # Look for: PART / DESC / QTY / PRICE / TOTAL
        candidates = re.findall(
            r"(\b\d{5,}[A-Z]*\b)\s+([A-Z\s]{5,}?)\s+(\d{1,4})\s+([\d,\.]+)\s+([\d,\.]+)",
            full_text, re.IGNORECASE
        )
        for i, (part, desc, qty, up, total) in enumerate(candidates):
            try:
                line = InvoiceLine(
                    line_no=i + 1,
                    part_no=part.strip(),
                    desc_en=desc.strip(),
                    qty=int(qty),
                    unit="PCS",
                    unit_price=float(up.replace(',', '')),
                    total_eur=float(total.replace(',', '')),
                    origin_raw="",
                )
                lines.append(line)
            except:
                continue
        return lines