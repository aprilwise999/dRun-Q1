# parsers/customs_parser.py
import json
import os
from pathlib import Path
from typing import List, Dict, Any
import fitz  # PyMuPDF

from models import CustomsLine, OriginCountry


# --- Helper functions ---
def _normalize_number(s: str) -> float:
    """Convert string number (with commas) to float."""
    if not s:
        return 0.0
    clean = s.replace(',', '').replace(' ', '').replace('\u00a0', '')
    try:
        return float(clean)
    except ValueError:
        return 0.0

def smart_thai_removal(text: str, preserve_thai: bool = False) -> str:
    """Remove Thai chars unless explicitly preserving them."""
    if not text:
        return ""
    if preserve_thai:
        return text.strip()
    # Remove only Thai characters if not preserving
    return ''.join(c for c in text if not ('\u0e00' <= c <= '\u0e7f')).strip()

def clean_thai_text(text: str) -> str:
    """Normalize and clean Thai text."""
    if not text:
        return ""
    import unicodedata
    text = unicodedata.normalize('NFC', text)
    text = ''.join(char for char in text if unicodedata.category(char) not in ['Cc', 'Cf', 'Cn', 'Co', 'Cs'])
    for corrupt, correct in {
        'Î': 'ำ', '»': 'ุ', 'à': 'ั', 'á': 'ั', 'ì': 'ี', 'í': 'ี', '¿': 'ฟ', 'Ñ': 'ภ', 'Â': 'แ'
    }.items():
        text = text.replace(corrupt, correct)
    return text.strip()

def should_preserve_thai(field_comment: str) -> bool:
    """Only preserve Thai for Code_Name_and_Thai_Name fields."""
    if not field_comment:
        return False
    return "code_name_and_thai_name" in field_comment.lower() or "thai_name" in field_comment.lower()

def extract_precise_text_only(page, rect, preserve_thai=False) -> str:
    """Extract text from exact rectangle with character-level precision."""
    try:
        text_dict = page.get_text("dict", clip=rect)
        extracted_texts = []
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    for char_info in span.get("chars", []):
                        char = char_info.get("c", "")
                        char_bbox = fitz.Rect(char_info.get("bbox", [0, 0, 0, 0]))
                        char_center_x = (char_bbox.x0 + char_bbox.x1) / 2
                        char_center_y = (char_bbox.y0 + char_bbox.y1) / 2
                        if (rect.x0 <= char_center_x <= rect.x1 and rect.y0 <= char_center_y <= rect.y1):
                            line_text += char
                if line_text.strip():
                    extracted_texts.append(line_text)
        raw_text = "\n".join(extracted_texts)
        cleaned = clean_thai_text(raw_final)
        final = smart_thai_removal(cleaned, preserve_thai)
        return final
    except:
        return ""

def parse_item_field_name(field_name: str):
    """Parse item field name to extract item number and field type."""
    if field_name.startswith('Item') and '_' in field_name:
        prefix, rest = field_name.split('_', 1)
        if prefix[4:].isdigit():  # Item1, Item2, ...
            return int(prefix[4:]), rest
        elif len(prefix) == 5 and prefix[4:].isalpha():  # ItemA, ItemB, ...
            letter = prefix[4:]
            item_num = ord(letter.upper()) - ord('A') + 4
            return item_num, rest
    return None, None

def load_template(template_path: Path) -> Dict[str, Any]:
    """Load a JSON template."""
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def extract_data_using_template(pdf_doc, template_data: Dict, page_mapping: Dict[str, List[int]]) -> List[Dict]:
    """Extract data using a single template."""
    extracted_data = []
    template_type = template_data["template_info"]["template_type"]
    fields = template_data["fields"]

    for field_id, field_info in fields.items():
        field_name = field_info["field_name"]
        field_comment = field_info.get("comment", "")
        coordinates = field_info["coordinates"]
        page_type = field_info["page_type"]
        preserve_thai = should_preserve_thai(field_comment)

        target_pages = page_mapping.get(page_type, [0])
        for page_num in target_pages:
            if page_num >= len(pdf_doc):
                continue
            page = pdf_doc[page_num]
            page_rect = page.rect
            actual_rect = fitz.Rect(
                coordinates["x0"] * page_rect.width,
                coordinates["y0"] * page_rect.height,
                coordinates["x1"] * page_rect.width,
                coordinates["y1"] * page_rect.height
            )
            extracted_text = extract_precise_text_only(page, actual_rect, preserve_thai)
            extracted_data.append({
                "field_name": field_name,
                "extracted_text": extracted_text,
                "page_number": page_num,
                "template_type": template_type,
                "is_item": template_type.startswith("item_")
            })
    return extracted_data

def map_country_to_code(country_str: str) -> str:
    """Map country string to ISO 2-letter code."""
    if not country_str:
        return "KR"  # default fallback
    clean = country_str.strip().upper()
    mapping = {
        "KOREA": "KR", "REPUBLIC OF KOREA": "KR", "SOUTH KOREA": "KR",
        "GERMANY": "DE", "DEUTSCHLAND": "DE",
        "CHINA": "CN", "PEOPLE'S REPUBLIC OF CHINA": "CN",
        "INDIA": "IN",
        "TURKEY": "TR", "TÜRKIYE": "TR",
        "CZECH": "CZ", "CZECH REPUBLIC": "CZ", "CZECHIA": "CZ",
        "ITALY": "IT",
        "BRAZIL": "BR"
    }
    return mapping.get(clean, "KR")


# --- Main function ---
def parse_customs(pdf_path: str) -> List[CustomsLine]:
    """
    Parse a customs PDF using coordinate templates.
    Returns List[CustomsLine] for compatibility with web_app.py.
    """
    # Load templates from ./templates (relative to this file)
    TEMPLATES_DIR = Path(__file__).parent / "templates"
    templates = {
        "main_first": load_template(TEMPLATES_DIR / "main_first_template.json"),
        "main_last": load_template(TEMPLATES_DIR / "main_last_template.json"),
        "item_first": load_template(TEMPLATES_DIR / "item_first_template.json"),
        "item_other": load_template(TEMPLATES_DIR / "item_other_template.json")
    }

    if not all(templates.values()):
        raise FileNotFoundError("One or more template files missing in parsers/templates/")

    # Open PDF
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Page mapping
    page_mapping = {
        "first": [0],
        "last": [total_pages - 1],
        "middle": list(range(1, total_pages - 1)) if total_pages > 2 else [0]
    }

    # Extract all data
    all_data = []
    for name, template in templates.items():
        if template:
            all_data.extend(extract_data_using_template(doc, template, page_mapping))

    doc.close()

    # --- Build header ---
    header = {}
    for record in all_data:
        if not record["is_item"]:
            header[record["field_name"]] = record["extracted_text"]

    # --- Build items ---
    item_records = [r for r in all_data if r["is_item"]]
    items_by_number = {}

    for record in item_records:
        item_num, field_type = parse_item_field_name(record["field_name"])
        if item_num is None:
            continue

        # Global item number (for multi-page)
        global_item_num = item_num
        if record["page_number"] > 0:
            # Middle pages: ItemA=4 → global 4 + 5*(page-1)
            if 'A' <= record["field_name"][4] <= 'E':
                global_item_num += 5 * (record["page_number"] - 1)
            else:
                # First page items (1-3) stay as-is
                pass

        if global_item_num not in items_by_number:
            items_by_number[global_item_num] = {"line_no": global_item_num}

        items_by_number[global_item_num][field_type] = record["extracted_text"]

    # === DEBUG: Print raw extracted items ===
    print("\n" + "="*60)
    print("🔍 DEBUG: Raw extracted items from templates:")
    for i, item in enumerate(items_by_number.values()):
        print(f"  Item {i+1}:")
        for k, v in item.items():
            print(f"    {k}: {repr(v)}")
    print("="*60 + "\n")
    # === END DEBUG ===

    # --- Convert to CustomsLine objects ---
    result = []
    for item in items_by_number.values():
        # Try to get required fields
        part_no = item.get("Part", "") or item.get("Code_Name_and_Thai_Name", "")
        desc_en = item.get("Code_Name_and_Thai_Name", "") or part_no
        qty_str = item.get("Quantity", "").split()[0] if item.get("Quantity") else "1"
        qty = _normalize_number(qty_str)
        unit = item.get("Quantity", "").split()[1] if item.get("Quantity") and len(item["Quantity"].split()) > 1 else "C62"
        price_str = item.get("Price_in_Foreign_Currency", "").replace("EUR", "").strip()
        price_eur = _normalize_number(price_str)
        origin_str = item.get("Country_Code", "")
        origin = OriginCountry(map_country_to_code(origin_str))
        invoice_no = header.get("Invoice_Number_and_Date", "").split("#")[-1].split(":")[0].strip() if header.get("Invoice_Number_and_Date") else ""

        # Fallback: extract from PDF filename if needed
        if not invoice_no:
            invoice_no = Path(pdf_path).stem

        line = CustomsLine(
            line_no=item["line_no"],
            hs_code="",  # Not always available in templates
            part_no=part_no,
            desc_en=desc_en,
            qty=qty,
            unit=unit,
            price_eur=price_eur,
            origin=origin,
            invoice_no=invoice_no
        )
        result.append(line)

        # If template-based extraction found items, return them
    if result:
        return result

    # Otherwise, fall back to regex parser
    return parse_customs_fallback(pdf_path)


    # --- Fallback regex parser for simple/custom layouts (Set 2) ---
def parse_customs_fallback(pdf_path: str) -> List[CustomsLine]:
    import re
    doc = fitz.open(pdf_path)
    full_text = "\n".join(p.get_text() for p in doc)
    doc.close()

    # Match line: "577004H900 GEAR& TIE ROD END ASSY ... 60.000 C62 ... EUR 7,252.20 ... invno# 265088"
    pattern = r'(\d{6,}[A-Z]*)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+([A-Z0-9]+)\s+.*?EUR\s+([\d,\.]+)\s+.*?invno#\s+(\d+)'
    matches = re.findall(pattern, full_text)

    # === DEBUG: Show regex matches ===
    print("\n🔍 DEBUG: Fallback regex matches:")
    for i, match in enumerate(matches):
        print(f"  Match {i+1}: {match}")
    # === END DEBUG ===

    result = []
    for i, (part_no, desc, qty_str, unit, price_eur_str, invoice_no) in enumerate(matches):
        try:
            qty = _normalize_number(qty_str)
            price_eur = _normalize_number(price_eur_str)
            # Guess origin from "MADE IN KOREA" or similar
            origin = "KR"
            if "GERMANY" in full_text.upper():
                origin = "DE"
            elif "CHINA" in full_text.upper():
                origin = "CN"
            # Add more as needed

            line = CustomsLine(
                line_no=i + 1,
                hs_code="",
                part_no=part_no.strip(),
                desc_en=desc.strip(),
                qty=qty,
                unit=unit.strip(),
                price_eur=price_eur,
                origin=OriginCountry(origin),
                invoice_no=invoice_no.strip()
            )
            result.append(line)
        except Exception:
            continue
    return result