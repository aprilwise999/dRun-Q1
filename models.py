# models.py
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, validator

class OriginCountry(str, Enum):
    DE = "DE"
    CN = "CN"
    IN = "IN"
    TR = "TR"
    CZ = "CZ"
    IT = "IT"
    BR = "BR"
    KR = "KR"
    TH = "TH"

class CustomsLine(BaseModel):
    line_no: int
    hs_code: str
    part_no: str
    desc_en: str
    qty: float
    unit: str  # e.g., "C62", "LTR"
    price_eur: float
    origin: OriginCountry
    invoice_no: str
    freight_usd: Optional[float] = None
    insurance_thb: Optional[float] = None

class InvoiceLine(BaseModel):
    line_no: int
    part_no: str
    desc_en: str
    qty: int
    unit: str  # e.g., "PCE", "PCS", "LTR"
    unit_price: float
    total_eur: float
    origin_raw: str
    delivery_no: str = ""
    order_no: str = ""
    supplier: str = ""

class BLLine(BaseModel):
    bl_no: str = ""
    vessel: str = ""
    voyage: str = ""
    etd: str = ""
    gross_kg: float = 0.0
    packages: int = 0
    marks: List[str] = []
    shipper: str = ""
    consignee: str = ""