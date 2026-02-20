"""Document type enumerations for the banking pipeline."""

from enum import Enum


class DocumentType(str, Enum):
    """Supported banking document types."""
    INVOICE = "invoice"
    CHEQUE = "cheque"
    ID_CARD = "id_card"
    KYC_FORM = "kyc_form"
    TRADE_FINANCE = "trade_finance"
    RECEIPT = "receipt"
    BANK_STATEMENT = "bank_statement"
    UNKNOWN = "unknown"


class ProcessingStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    CLASSIFYING = "classifying"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ValidationStatus(str, Enum):
    """KYC/AML validation status."""
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    PENDING = "pending"
