"""
Document Processing API Routes.
Handles document upload, classification, extraction, and validation endpoints.
"""

import time
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional

from ..config import get_settings
from ..models.enums import DocumentType, ProcessingStatus
from ..models.schemas import (
    DocumentProcessResponse,
    BatchProcessResponse,
    ValidationResult,
)
from ..services.classifier import DocumentClassifier
from ..services.extractor import DocumentExtractor
from ..services.cheque_processor import ChequeProcessor
from ..services.kyc_processor import KYCProcessor
from ..services.invoice_processor import InvoiceProcessor
from ..services.validator import KYCAMLValidator
from ..services.storage import DocumentStorage
from ..utils.image_preprocessing import ImagePreprocessor
from ..utils.helpers import (
    compute_file_hash,
    validate_file_extension,
    get_file_size_mb,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])

# Initialize services
classifier = DocumentClassifier()
extractor = DocumentExtractor()
cheque_processor = ChequeProcessor()
kyc_processor = KYCProcessor()
invoice_processor = InvoiceProcessor()
validator = KYCAMLValidator()
storage = DocumentStorage()
preprocessor = ImagePreprocessor()


@router.post("/process", response_model=DocumentProcessResponse)
async def process_document(
    file: UploadFile = File(..., description="Banking document to process"),
    document_type: Optional[str] = Form(
        default=None,
        description="Document type (auto-classified if not provided)",
    ),
):
    """
    Process a single banking document.

    1. Validates file type and size
    2. Classifies document type (if not specified)
    3. Preprocesses image for optimal OCR
    4. Extracts structured data using appropriate model
    5. Runs KYC/AML validation (if applicable)
    6. Stores results with audit trail

    Returns complete extraction results with confidence scores.
    """
    start_time = time.time()
    settings = get_settings()
    doc_id = DocumentStorage.generate_document_id()

    try:
        # ── Step 1: Validate File ────────────────────────────────
        if not validate_file_extension(file.filename, settings.allowed_extensions_list):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
            )

        file_bytes = await file.read()
        file_size = get_file_size_mb(file_bytes)

        if file_size > settings.max_file_size_mb:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file_size:.1f}MB). Max: {settings.max_file_size_mb}MB",
            )

        file_hash = compute_file_hash(file_bytes)
        logger.info(
            f"Processing document {doc_id}: {file.filename} "
            f"({file_size:.2f}MB, hash: {file_hash[:12]}...)"
        )

        # ── Step 2: Classify Document ────────────────────────────
        if document_type:
            doc_type = DocumentType(document_type)
            classification_confidence = 1.0
        else:
            doc_type, classification_confidence, reasoning = await classifier.classify(
                file_bytes, file.filename
            )
            logger.info(f"Classified as: {doc_type.value} ({classification_confidence:.2f})")

        # ── Step 3: Preprocess Image ─────────────────────────────
        processed_bytes = file_bytes
        content_type = file.content_type or ""

        if "image" in content_type or file.filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".tiff", ".bmp")
        ):
            if doc_type == DocumentType.CHEQUE:
                processed_bytes = preprocessor.preprocess_cheque(file_bytes)
            elif doc_type == DocumentType.ID_CARD:
                processed_bytes = preprocessor.preprocess_id_card(file_bytes)
            elif doc_type in (DocumentType.KYC_FORM, DocumentType.TRADE_FINANCE):
                processed_bytes = preprocessor.preprocess_form(file_bytes)

        # ── Step 4: Extract Structured Data ──────────────────────
        extracted_fields, raw_result = await extractor.extract(processed_bytes, doc_type)

        # ── Step 5: Type-Specific Processing ─────────────────────
        extraction_result = None

        if doc_type == DocumentType.INVOICE:
            extraction_result = await invoice_processor.process(extracted_fields, raw_result)
        elif doc_type == DocumentType.CHEQUE:
            extraction_result = await cheque_processor.process(extracted_fields, raw_result)
        elif doc_type == DocumentType.KYC_FORM:
            extraction_result = await kyc_processor.process(extracted_fields, raw_result)

        # ── Step 6: Confidence Check & Validation ────────────────
        confidence_ok, low_fields = extractor.check_confidence(extracted_fields)

        validation_result = None
        if doc_type in (DocumentType.KYC_FORM, DocumentType.ID_CARD):
            validation_result = await validator.validate_kyc(
                extracted_fields, doc_type.value
            )

        # ── Step 7: Determine Review Status ──────────────────────
        needs_review = False
        review_reason = None

        if not confidence_ok:
            needs_review = True
            review_reason = f"Low confidence fields: {', '.join(low_fields)}"
        elif validation_result and validation_result.status.value != "passed":
            needs_review = True
            review_reason = f"Validation: {validation_result.recommendation}"

        # ── Step 8: Build Response ───────────────────────────────
        processing_time = (time.time() - start_time) * 1000

        response = DocumentProcessResponse(
            document_id=doc_id,
            status=ProcessingStatus.COMPLETED,
            document_type=doc_type,
            classification_confidence=classification_confidence,
            extracted_fields=extracted_fields,
            extraction_result=extraction_result,
            validation=validation_result,
            processing_time_ms=round(processing_time, 2),
            pages_processed=len(raw_result.pages) if raw_result.pages else 1,
            needs_human_review=needs_review,
            review_reason=review_reason,
        )

        # ── Step 9: Persist Results ──────────────────────────────
        await storage.save_result(response)

        logger.info(
            f"Document {doc_id} processed in {processing_time:.0f}ms "
            f"| Type: {doc_type.value} | Review: {needs_review}"
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Processing failed for {doc_id}: {str(e)}", exc_info=True)
        processing_time = (time.time() - start_time) * 1000
        return DocumentProcessResponse(
            document_id=doc_id,
            status=ProcessingStatus.FAILED,
            document_type=DocumentType.UNKNOWN,
            classification_confidence=0.0,
            processing_time_ms=round(processing_time, 2),
            needs_human_review=True,
            review_reason=f"Processing error: {str(e)}",
        )


@router.post("/batch", response_model=BatchProcessResponse)
async def batch_process(
    files: list[UploadFile] = File(..., description="Multiple banking documents"),
    document_type: Optional[str] = Form(default=None),
):
    """Process multiple banking documents in a batch."""
    start_time = time.time()
    results = []
    success_count = 0
    failure_count = 0
    review_count = 0

    for file in files:
        # Reuse single document processing for each file
        try:
            result = await process_document(file=file, document_type=document_type)
            results.append(result)
            if result.status == ProcessingStatus.COMPLETED:
                success_count += 1
            if result.needs_human_review:
                review_count += 1
        except Exception as e:
            failure_count += 1
            logger.error(f"Batch item failed: {file.filename} — {str(e)}")

    total_time = (time.time() - start_time) * 1000
    return BatchProcessResponse(
        batch_id=f"BATCH-{DocumentStorage.generate_document_id()}",
        total_documents=len(files),
        results=results,
        total_processing_time_ms=round(total_time, 2),
        success_count=success_count,
        failure_count=failure_count,
        review_count=review_count,
    )


@router.get("/{document_id}", response_model=dict)
async def get_document(document_id: str):
    """Retrieve processed document results by ID."""
    result = await storage.get_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.get("/{document_id}/validate", response_model=ValidationResult)
async def validate_document(document_id: str):
    """Run KYC/AML validation on a previously processed document."""
    result = await storage.get_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")

    # Re-run validation on stored extracted fields
    # In production, deserialize the stored extracted_data
    raise HTTPException(
        status_code=501,
        detail="Re-validation from stored data — coming soon",
    )
