"""
Pydantic models for request/response schemas.
Defines structured data models for the banking document processing pipeline.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from .enums import DocumentType, ProcessingStatus, ValidationStatus


# ─── Extracted Field Model ──────────────────────────────────────────

class ExtractedField(BaseModel):
    """A single extracted field with confidence score."""
    field_name: str = Field(..., description="Name of the extracted field")
    value: Optional[str] = Field(None, description="Extracted value")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    bounding_box: Optional[list[float]] = Field(
        None, description="Bounding box coordinates [x1, y1, x2, y2]"
    )
    page_number: Optional[int] = Field(None, description="Page number where field was found")


# ─── Document Processing Request ────────────────────────────────────

class DocumentProcessRequest(BaseModel):
    """Request model for document processing."""
    document_type: Optional[DocumentType] = Field(
        default=None, description="Document type — auto-classified if not provided"
    )
    priority: str = Field(default="normal", description="Processing priority: low, normal, high")
    callback_url: Optional[str] = Field(
        None, description="Webhook URL for async notification"
    )


# ─── Invoice Extraction Result ──────────────────────────────────────

class InvoiceResult(BaseModel):
    """Extracted invoice fields."""
    vendor_name: Optional[ExtractedField] = None
    vendor_address: Optional[ExtractedField] = None
    invoice_number: Optional[ExtractedField] = None
    invoice_date: Optional[ExtractedField] = None
    due_date: Optional[ExtractedField] = None
    subtotal: Optional[ExtractedField] = None
    tax_amount: Optional[ExtractedField] = None
    total_amount: Optional[ExtractedField] = None
    currency: Optional[ExtractedField] = None
    purchase_order: Optional[ExtractedField] = None
    line_items: Optional[list[dict]] = Field(default_factory=list)


# ─── Cheque Extraction Result ───────────────────────────────────────

class ChequeResult(BaseModel):
    """Extracted cheque fields including MICR data."""
    payee_name: Optional[ExtractedField] = None
    amount_in_words: Optional[ExtractedField] = None
    amount_in_figures: Optional[ExtractedField] = None
    cheque_date: Optional[ExtractedField] = None
    bank_name: Optional[ExtractedField] = None
    branch_name: Optional[ExtractedField] = None
    account_number: Optional[ExtractedField] = None
    cheque_number: Optional[ExtractedField] = None
    micr_code: Optional[ExtractedField] = None
    ifsc_code: Optional[ExtractedField] = None
    signature_detected: bool = Field(default=False)


# ─── ID Document Extraction Result ──────────────────────────────────

class IDDocumentResult(BaseModel):
    """Extracted ID document fields."""
    full_name: Optional[ExtractedField] = None
    first_name: Optional[ExtractedField] = None
    last_name: Optional[ExtractedField] = None
    date_of_birth: Optional[ExtractedField] = None
    gender: Optional[ExtractedField] = None
    nationality: Optional[ExtractedField] = None
    document_number: Optional[ExtractedField] = None
    expiry_date: Optional[ExtractedField] = None
    issuing_country: Optional[ExtractedField] = None
    address: Optional[ExtractedField] = None
    photo_detected: bool = Field(default=False)


# ─── KYC Form Extraction Result ─────────────────────────────────────

class KYCFormResult(BaseModel):
    """Extracted KYC form fields."""
    customer_name: Optional[ExtractedField] = None
    date_of_birth: Optional[ExtractedField] = None
    nationality: Optional[ExtractedField] = None
    occupation: Optional[ExtractedField] = None
    employer: Optional[ExtractedField] = None
    annual_income: Optional[ExtractedField] = None
    source_of_funds: Optional[ExtractedField] = None
    purpose_of_account: Optional[ExtractedField] = None
    politically_exposed: Optional[ExtractedField] = None
    risk_rating: Optional[str] = None
    id_documents: Optional[list[dict]] = Field(default_factory=list)


# ─── Trade Finance Extraction Result ────────────────────────────────

class TradeFinanceResult(BaseModel):
    """Extracted trade finance / LC document fields."""
    lc_number: Optional[ExtractedField] = None
    issuing_bank: Optional[ExtractedField] = None
    beneficiary: Optional[ExtractedField] = None
    applicant: Optional[ExtractedField] = None
    amount: Optional[ExtractedField] = None
    currency: Optional[ExtractedField] = None
    expiry_date: Optional[ExtractedField] = None
    swift_code: Optional[ExtractedField] = None
    port_of_loading: Optional[ExtractedField] = None
    port_of_discharge: Optional[ExtractedField] = None
    goods_description: Optional[ExtractedField] = None


# ─── Validation Result ──────────────────────────────────────────────

class ValidationResult(BaseModel):
    """KYC/AML validation result."""
    status: ValidationStatus
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    risk_score: float = Field(ge=0.0, le=1.0, description="Risk score 0 (low) to 1 (high)")
    flags: list[str] = Field(default_factory=list, description="AML/compliance flags")
    recommendation: str = Field(default="", description="Action recommendation")


# ─── Main Processing Response ───────────────────────────────────────

class DocumentProcessResponse(BaseModel):
    """Complete document processing response."""
    document_id: str = Field(..., description="Unique document processing ID")
    status: ProcessingStatus
    document_type: DocumentType
    classification_confidence: float = Field(
        ge=0.0, le=1.0, description="Document classification confidence"
    )
    extracted_fields: list[ExtractedField] = Field(default_factory=list)
    extraction_result: Optional[
        InvoiceResult | ChequeResult | IDDocumentResult | KYCFormResult | TradeFinanceResult
    ] = None
    validation: Optional[ValidationResult] = None
    processing_time_ms: float = Field(..., description="Total processing time in milliseconds")
    pages_processed: int = Field(default=1)
    needs_human_review: bool = Field(default=False)
    review_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    raw_text: Optional[str] = Field(None, description="Raw extracted text content")


# ─── Batch Processing ───────────────────────────────────────────────

class BatchProcessRequest(BaseModel):
    """Batch document processing request."""
    document_type: Optional[DocumentType] = None
    priority: str = Field(default="normal")


class BatchProcessResponse(BaseModel):
    """Batch processing response."""
    batch_id: str
    total_documents: int
    results: list[DocumentProcessResponse]
    total_processing_time_ms: float
    success_count: int
    failure_count: int
    review_count: int


# ─── Health Check ───────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    document_intelligence_status: str
    openai_status: str
    database_status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
