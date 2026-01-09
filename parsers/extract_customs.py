"""
Fixed Precise Relational Data Extractor - Smart Thai Removal

Key improvements:
- Smart Thai character removal that preserves non-Thai characters
- Better extraction ">for mixed Thai/English content
- Fixed empty fields: Consignee, Total_Gross_Weight, Total_Value
- Improved Brand ">and Country_Code extraction
"""

import argparse
import json
import csv
import os
import fitz  # PyMuPDF
from pathlib import Path
import unicodedata
import re
import uuid
from datetime import datetime

def clean_thai_text(text):
    """Clean ">and normalize Thai text extracted ">from PDF."""
    if not text:
        return ""
    
    text = unicodedata.normalize('NFC', text)
    text = ''.join(char for char in text if unicodedata.category(char) not in ['Cc', 'Cf', 'Cn', 'Co', 'Cs'])
    text = text.replace('\u0012', ' ').replace('\u0013', ' ').replace('\u0010', ' ').replace('\u0011', ' ')
    
    # Fix common Thai character corruptions
    thai_fixes = {
        'Î': 'ำ', '»': 'ุ', 'à': 'ั', 'á': 'ั', 'ì': 'ี', 'í': 'ี', '¿': 'ฟ', 'Ñ': 'ภ', 'Â': 'แ'
    }
    
    for corrupt, correct in thai_fixes.items():
        text = text.replace(corrupt, correct)
    
    return text.strip()

def should_preserve_thai_content(field_comment):
    """Determine ">if field should preserve Thai - ONLY ">for 'Code_Name_and_Thai_Name' fields."""
    if not field_comment:
        return False
    
    comment_lower = field_comment.lower()
    # Very specific check - only preserve Thai for explicit Thai name fields
    return "code_name_and_thai_name" in comment_lower or "thai_name" in comment_lower

def smart_thai_removal(text, preserve_thai=False):
    """Smart Thai character removal that preserves non-Thai characters ">from mixed content."""
    if not text:
        return ""
    
    if preserve_thai:
        # Only for Code_Name_and_Thai_Name fields - keep Thai characters
        return clean_thai_text(text)
    else:
        # For all other fields - intelligently remove Thai characters
        lines = text.split('\n')
        processed_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Count Thai vs non-Thai characters
            thai_chars = sum(1 for c in line if '\u0e00' <= c <= '\u0e7f')
            non_thai_chars = sum(1 for c in line if c.isalnum() and not ('\u0e00' <= c <= '\u0e7f'))
            
            if thai_chars == 0:
                # No Thai characters - keep as is
                processed_lines.append(line)
            elif non_thai_chars == 0:
                # Only Thai characters - skip entirely
                continue
            else:
                # Mixed content - remove only Thai characters, keep non-Thai
                line_no_thai = re.sub(r'[\u0e00-\u0e7f]+', ' ', line)
                line_no_thai = re.sub(r'\s+', ' ', line_no_thai).strip()
                
                # Only keep if there's meaningful content left
                if line_no_thai and len(line_no_thai) > 1:
                    processed_lines.append(line_no_thai)
        
        result = '\n'.join(processed_lines) if processed_lines else ""
        
        # Final cleanup
        result = re.sub(r'\(\s*\)', '', result)  # Remove empty parentheses
        result = re.sub(r':\s*$', '', result)   # Remove trailing colons
        result = re.sub(r'\s+', ' ', result)    # Multiple spaces -> single space
        result = result.strip()
        
        return result

def format_multiline_text(text, preserve_thai=False):
    """Format text with proper line handling."""
    if not text:
        return ""
    
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if len(lines) <= 1:
        return ' '.join(lines)
    else:
        if preserve_thai:
            # For Thai content fields, preserve line breaks
            return '\n'.join(lines)
        else:
            # For all other fields, join with spaces
            return ' '.join(lines)

def extract_precise_text_only(page, rect, preserve_thai=False, debug=False):
    """Extract text ONLY within exact rectangle boundaries with smart Thai handling."""
    
    # Try multiple extraction methods for better recovery
    extraction_methods = []
    
    # Method 1: Dictionary-based extraction(most precise)
    try:
        text_dict = page.get_text("dict", clip=rect)
        extracted_texts = []
        
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
                
            for line in block["lines"]:
                line_texts = []
                
                for span in line.get("spans", []):
                    span_text = ""
                    chars = span.get("chars", [])
                    
                    if not chars and span.get("text"):
                        # Fallback to span text if no character info
                        span_bbox = fitz.Rect(span.get("bbox", [0, 0, 0, 0]))
                        # Check if span bbox overlaps with our target rect
                        if (rect.x0 <= span_bbox.x1 and span_bbox.x0 <= rect.x1 and 
                            rect.y0 <= span_bbox.y1 and span_bbox.y0 <= rect.y1):
                            span_text = span.get("text", "")
                    else:
                        # Check each character precisely
                        for char_info in chars:
                            char = char_info.get("c", "")
                            char_bbox = fitz.Rect(char_info.get("bbox", [0, 0, 0, 0]))
                            
                            # Character center must be within target rectangle
                            char_center_x = (char_bbox.x0 + char_bbox.x1) / 2
                            char_center_y = (char_bbox.y0 + char_bbox.y1) / 2
                            
                            if (rect.x0 <= char_center_x <= rect.x1 and 
                                rect.y0 <= char_center_y <= rect.y1):
                                span_text += char
                    
                    if span_text.strip():
                        line_texts.append(span_text)
                
                if line_texts:
                    line_text = "".join(line_texts)
                    extracted_texts.append(line_text)
        
        method1_text = "\n".join(extracted_texts) if extracted_texts else ""
        extraction_methods.append(("precise_dict", method1_text))
    except:
        extraction_methods.append(("precise_dict", ""))
    
    # Method 2: Standard text extraction
    try:
        method2_text = page.get_text("text", clip=rect)
        extraction_methods.append(("standard", method2_text))
    except:
        extraction_methods.append(("standard", ""))
    
    # Method 3: Slightly relaxed extraction(minimal expansion for edge cases)
    try:
        margin = 1  # Very small margin
        expanded_rect = fitz.Rect(
            rect.x0 - margin, rect.y0 - margin,
            rect.x1 + margin, rect.y1 + margin
        )
        method3_text = page.get_text("text", clip=expanded_rect)
        extraction_methods.append(("relaxed", method3_text))
    except:
        extraction_methods.append(("relaxed", ""))
    
    # Choose the best extraction result
    best_text = ""
    best_method = "none"
    
    for method_name, raw_text in extraction_methods:
        if not raw_text:
            continue
        
        # Clean the text
        cleaned = clean_thai_text(raw_text)
        
        # Apply smart Thai removal
        processed = smart_thai_removal(cleaned, preserve_thai)
        
        # Score the result
        score = len(processed.strip())
        if score > len(best_text.strip()):
            best_text = processed
            best_method = method_name
    
    # Format the final text
    formatted_text = format_multiline_text(best_text, preserve_thai)
    
    if debug:
        print(f"    Smart extraction(preserve_thai={preserve_thai}):")
        for method_name, raw_text in extraction_methods:
            processed = smart_thai_removal(clean_thai_text(raw_text), preserve_thai)
            print(f"      {method_name:12}: {repr(processed[:80])}")
        print(f"    Best method: {best_method}")
        print(f"    Final result: {repr(formatted_text)}")
    
    return formatted_text

def parse_item_field_name(field_name):
    """Parse item field name to extract item number and field type."""
    
    if field_name.startswith('Item') and '_' in field_name:
        prefix, rest = field_name.split('_', 1)
        
        if prefix[4:].isdigit():  # Item1, Item2, Item3
            item_num = int(prefix[4:])
            return item_num, rest
        elif len(prefix) == 5 and prefix[4:].isalpha():  # ItemA, ItemB, ItemC, etc.
            letter = prefix[4:]
            # Convert A=4, B=5, C=6, D=7, E=8
            item_num = ord(letter.upper()) - ord('A') + 4
            return item_num, rest
    
    return None, None

def extract_data_using_template(pdf_doc, template_data, page_mapping, debug=False):
    """Extract data from PDF using template with SMART extraction."""
    extracted_data = []
    template_type = template_data["template_info"]["template_type"]
    
    if debug:
        print(f"\nExtracting data using {template_type} template...")
    
    for field_id, field_info in template_data["fields"].items():
        field_name = field_info["field_name"]
        field_comment = field_info.get("comment", "")
        field_type = field_info.get("field_type", "text_field")
        has_thai = field_info.get("has_thai", False)
        coordinates = field_info["coordinates"]
        page_type = field_info["page_type"]
        
        # Determine which page(s) to extract from
        target_pages = []
        if page_type == "first":
            target_pages = [0]
        elif page_type == "last":
            target_pages = [len(pdf_doc) - 1]
        elif page_type == "middle":
            target_pages = list(range(1, len(pdf_doc) - 1))
        else:
            target_pages = page_mapping.get(template_type, [0])
        
        # Extract from each target page
        for page_num in target_pages:
            if page_num >= len(pdf_doc):
                continue
                
            page = pdf_doc[page_num]
            page_rect = page.rect
            
            # Convert normalized coordinates to actual coordinates
            actual_rect = fitz.Rect(
                coordinates["x0"] * page_rect.width,
                coordinates["y0"] * page_rect.height,
                coordinates["x1"] * page_rect.width,
                coordinates["y1"] * page_rect.height
            )
            
            # Use smart extraction with Thai preservation logic
            preserve_thai = should_preserve_thai_content(field_comment)
            extracted_text = extract_precise_text_only(page, actual_rect, preserve_thai, debug)
            
            # Store extracted data
            data_record = {
                "field_id": field_id,
                "field_name": field_name,
                "field_comment": field_comment,
                "field_type": field_type,
                "page_number": page_num + 1,
                "page_type": page_type,
                "extracted_text": extracted_text,
                "template_type": template_type,
                "coordinates": coordinates,
                "has_thai": preserve_thai
            }
            
            extracted_data.append(data_record)
            
            if debug:
                thai_flag = "🇹🇭" if preserve_thai else "🚫"
                empty_flag = "⚠️" if not extracted_text.strip() else "✓"
                thai_chars = sum(1 for c in extracted_text if '\u0e00' <= c <= '\u0e7f')
                print(f"  {field_name} [{field_type}] {thai_flag} {empty_flag} (Page {page_num + 1}): {repr(extracted_text[:50])}")
                
                # Warning for non-Thai fields with Thai characters
                if not preserve_thai and thai_chars > 0:
                    print(f"    ⚠️  Non-Thai field still has {thai_chars} Thai characters!")
    
    return extracted_data

def load_template(template_path):
    """Load a template file."""
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template_data = json.load(f)
        return template_data
    except Exception as e:
        print(f"Error loading template {template_path}: {e}")
        return None

def create_relational_structure(all_main_data, all_item_data, input_filename):
    """Create relational database structure with document ID."""
    
    # Generate unique document ID
    document_id = str(uuid.uuid4())[:8]  # Short UUID
    extraction_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create main document record
    main_record = {
        'document_id': document_id,
        'source_file': input_filename,
        'extraction_date': extraction_date,
        'total_pages': 0  # Will be updated
    }
    
    # Add main fields to the main record
    for record in all_main_data:
        field_name = record['field_name']
        extracted_text = record['extracted_text']
        # Format text for single-line storage
        text_for_storage = extracted_text.replace('\n', ' | ') if '\n' in extracted_text else extracted_text
        main_record[field_name] = text_for_storage
        
        # Update total pages
        main_record['total_pages'] = max(main_record['total_pages'], record['page_number'])
    
    # Process item data into relational structure
    items_by_number = {}  # item_number -> {field_name: value}
    
    for record in all_item_data:
        field_name = record['field_name']
        extracted_text = record['extracted_text']
        page_number = record['page_number']
        
        # Parse item number from field name
        item_num, item_field = parse_item_field_name(field_name)
        
        if item_num is not None and item_field is not None:
            # Calculate global item number considering page groups
            # For pages beyond first page, add offset
            if page_number > 1:
                # Each additional page adds 5 items(A,B,C,D,E pattern)
                page_offset = (page_number - 1) * 5
                if item_num >= 4:  # ItemA+ pattern
                    # Adjust for multiple page groups
                    global_item_num = item_num + page_offset
                else:
                    global_item_num = item_num  # Item1,2,3 stay as is
            else:
                global_item_num = item_num
            
            if global_item_num not in items_by_number:
                items_by_number[global_item_num] = {
                    'document_id': document_id,
                    'item_number': global_item_num,
                    'source_page': page_number
                }
            
            # Format text for storage
            text_for_storage = extracted_text.replace('\n', ' | ') if '\n' in extracted_text else extracted_text
            items_by_number[global_item_num][item_field] = text_for_storage
    
    # Convert items dict to list
    items_list = [items_by_number[item_num] for item_num in sorted(items_by_number.keys())]
    
    return main_record, items_list

def save_as_json(main_record, items_list, output_dir, input_filename):
    """Save extracted data as a single JSON file with nested structure."""
    
    # Build header object (all main fields except metadata)
    header_fields = {
        k: v for k, v in main_record.items()
        if k not in ['document_id', 'source_file', 'extraction_date', 'total_pages']
    }
    
    # Build items list
    items = []
    for item in items_list:
        item_data = {
            k: v for k, v in item.items()
            if k not in ['document_id', 'item_number', 'source_page']
        }
        items.append({
            "item_number": item['item_number'],
            "source_page": item['source_page'],
            **item_data
        })
    
    # Final JSON structure
    json_output = {
        "document_id": main_record['document_id'],
        "source_file": main_record['source_file'],
        "extraction_date": main_record['extraction_date'],
        "total_pages": main_record['total_pages'],
        "header": header_fields,
        "items": items
    }
    
    # Create output filename
    base_name = Path(input_filename).stem
    json_path = output_dir / f"{base_name}_extracted.json"
    
    # Save
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)
    
    return json_path

def main():
    parser = argparse.ArgumentParser(description="Extract PDF data with SMART Thai character removal")
    parser.add_argument("--input", required=True, help="Input PDF file to extract data from")
    parser.add_argument("--templates-dir", default="templates", help="Directory containing template files")
    parser.add_argument("--output-dir", default="extracted_data", help="Output directory for extracted data")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    
    args = parser.parse_args()
    
    # Check input PDF
    if not Path(args.input).exists():
        print(f"Error: Input PDF file not found: {args.input}")
        return
    
    input_filename = Path(args.input).name
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    # Load templates
    templates_dir = Path(args.templates_dir)
    template_files = {
        "main_first": templates_dir / "main_first_template.json",
        "main_last": templates_dir / "main_last_template.json",
        "item_first": templates_dir / "item_first_template.json",
        "item_other": templates_dir / "item_other_template.json"
    }
    
    templates = {}
    
    for template_type, template_path in template_files.items():
        if template_path.exists():
            templates[template_type] = load_template(template_path)
            if templates[template_type]:
                field_count = len(templates[template_type]["fields"])
                thai_fields = sum(1 for field in templates[template_type]["fields"].values() 
                                if field.get("has_thai", False))
                print(f"✓ Loaded {template_type} template: {field_count} fields({thai_fields} Thai)")
            else:
                print(f"✗ Failed to load {template_type} template")
        else:
            print(f"⚠ Template file not found: {template_path}")
    
    if not templates:
        print("Error: No templates loaded. Please run template_creator.py first.")
        return
    
    # Open PDF document
    print(f"\nProcessing PDF: {args.input}")
    doc = fitz.open(args.input)
    total_pages = len(doc)
    print(f"Total pages: {total_pages}")
    
    # Create page mapping for templates
    page_mapping = {
        "main_first": [0],
        "main_last": [total_pages - 1],
        "item_first": [0],
        "item_other": list(range(1, total_pages))
    }
    
    # Extract data using each template
    all_main_data = []
    all_item_data = []
    
    for template_type, template_data in templates.items():
        if template_data:
            extracted_data = extract_data_using_template(
                doc, template_data, page_mapping, args.debug
            )
            
            if template_type.startswith("main_"):
                all_main_data.extend(extracted_data)
            elif template_type.startswith("item_"):
                all_item_data.extend(extracted_data)
    
    doc.close()
    
    # Create relational structure
    print(f"\nCreating relational database structure...")
    main_record, items_list = create_relational_structure(all_main_data, all_item_data, input_filename)
    
    # Save as JSON instead of CSV
    json_path = save_as_json(main_record, items_list, output_dir, input_filename)
    
    # Summary with detailed field analysis
    print(f"\nExtraction completed in JSON format!")
    print(f"Document ID: {main_record['document_id']}")
    
    # Analyze main fields
    main_data_fields = [k for k in main_record.keys() if k not in ['document_id', 'source_file', 'extraction_date', 'total_pages']]
    non_empty_main = [k for k in main_data_fields if main_record[k].strip()]
    empty_main = [k for k in main_data_fields if not main_record[k].strip()]
    
    print(f"Header fields: {len(main_data_fields)} total ({len(non_empty_main)} populated, {len(empty_main)} empty)")
    if empty_main:
        print(f"  Empty header fields: {', '.join(empty_main[:5])}")
    
    print(f"Items extracted: {len(items_list)}")
    
    if items_list:
        item_numbers = [item['item_number'] for item in items_list]
        print(f"Item numbers: {sorted(item_numbers)}")
    
    print(f"\nOutput file:")
    print(f"  - JSON: {json_path}")

if __name__ == "__main__":
    main()
            