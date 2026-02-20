"""
Core document extraction service using Azure AI Document Intelligence.
Handles routing to prebuilt and custom models based on document type.
"""

import logging
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentField,
)
from azure.core.credentials import AzureKeyCredential

from ..config import get_settings
from ..models.enums import DocumentType
from ..models.schemas import ExtractedField

logger = logging.getLogger(__name__)

# Mapping of document types to Azure AI Document Intelligence model IDs
MODEL_MAPPING = {
    DocumentType.INVOICE: "prebuilt-invoice",
    DocumentType.RECEIPT: "prebuilt-receipt",
    DocumentType.ID_CARD: "prebuilt-idDocument",
    DocumentType.CHEQUE: "prebuilt-layout",  # Use layout + custom post-processing
    DocumentType.KYC_FORM: "prebuilt-layout",  # Layout extraction + GPT-4o
    DocumentType.TRADE_FINANCE: "prebuilt-layout",  # Layout + GPT-4o for complex docs
    DocumentType.BANK_STATEMENT: "prebuilt-layout",
    DocumentType.UNKNOWN: "prebuilt-layout",
}


class DocumentExtractor:
    """
    Extracts structured data from banking documents using
    Azure AI Document Intelligence prebuilt and custom models.
    """

    def __init__(self):
        settings = get_settings()
        self.client = DocumentIntelligenceClient(
            endpoint=settings.azure_document_intelligence_endpoint,
            credential=AzureKeyCredential(settings.azure_document_intelligence_key),
        )
        self.confidence_threshold = settings.confidence_threshold

    def _convert_field(
        self, field_name: str, field: DocumentField, page_number: int = 1
    ) -> ExtractedField:
        """Convert Azure DocumentField to our ExtractedField schema."""
        value = None
        if field.value_string:
            value = field.value_string
        elif field.value_number:
            value = str(field.value_number)
        elif field.value_date:
            value = field.value_date.isoformat()
        elif field.value_currency:
            value = f"{field.value_currency.symbol or ''}{field.value_currency.amount}"
        elif field.content:
            value = field.content

        bounding_box = None
        if field.bounding_regions:
            region = field.bounding_regions[0]
            bounding_box = region.polygon if region.polygon else None

        return ExtractedField(
            field_name=field_name,
            value=value,
            confidence=field.confidence or 0.0,
            bounding_box=bounding_box,
            page_number=page_number,
        )

    async def extract(
        self, file_bytes: bytes, document_type: DocumentType
    ) -> tuple[list[ExtractedField], AnalyzeResult]:
        """
        Extract fields from a document using the appropriate model.

        Args:
            file_bytes: Raw document bytes
            document_type: Classified document type

        Returns:
            Tuple of (extracted_fields list, raw AnalyzeResult)
        """
        model_id = MODEL_MAPPING.get(document_type, "prebuilt-layout")
        logger.info(f"Extracting with model: {model_id} for type: {document_type.value}")

        try:
            poller = self.client.begin_analyze_document(
                model_id=model_id,
                analyze_request=AnalyzeDocumentRequest(bytes_source=file_bytes),
                content_type="application/octet-stream",
            )
            result: AnalyzeResult = poller.result()

            extracted_fields = []

            # Extract fields from documents (prebuilt models)
            if result.documents:
                for doc in result.documents:
                    if doc.fields:
                        for field_name, field in doc.fields.items():
                            extracted = self._convert_field(field_name, field)
                            extracted_fields.append(extracted)
                            logger.debug(
                                f"  {field_name}: {extracted.value} "
                                f"(confidence: {extracted.confidence:.2f})"
                            )

            # Extract text from layout analysis (for custom processing)
            if result.pages:
                for page in result.pages:
                    if page.lines:
                        for line in page.lines:
                            extracted_fields.append(
                                ExtractedField(
                                    field_name="text_line",
                                    value=line.content,
                                    confidence=1.0,  # OCR text lines
                                    page_number=page.page_number,
                                )
                            )

            # Extract tables
            if result.tables:
                for table_idx, table in enumerate(result.tables):
                    table_data = []
                    for cell in table.cells:
                        table_data.append(
                            {
                                "row": cell.row_index,
                                "col": cell.column_index,
                                "content": cell.content,
                                "kind": cell.kind if hasattr(cell, "kind") else "content",
                            }
                        )
                    extracted_fields.append(
                        ExtractedField(
                            field_name=f"table_{table_idx}",
                            value=str(table_data),
                            confidence=1.0,
                        )
                    )

            logger.info(f"Extracted {len(extracted_fields)} fields from document")
            return extracted_fields, result

        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}")
            raise

    async def extract_with_layout(self, file_bytes: bytes) -> AnalyzeResult:
        """
        Extract using layout model — useful for unstructured documents
        where we need full text, tables, and structure.
        """
        poller = self.client.begin_analyze_document(
            model_id="prebuilt-layout",
            analyze_request=AnalyzeDocumentRequest(bytes_source=file_bytes),
            content_type="application/octet-stream",
        )
        return poller.result()

    def check_confidence(self, fields: list[ExtractedField]) -> tuple[bool, list[str]]:
        """
        Check if extracted fields meet confidence threshold.

        Returns:
            Tuple of (all_passed, list_of_low_confidence_fields)
        """
        low_confidence = []
        for field in fields:
            if field.confidence < self.confidence_threshold and field.field_name != "text_line":
                low_confidence.append(
                    f"{field.field_name}: {field.confidence:.2f} "
                    f"(threshold: {self.confidence_threshold})"
                )

        return len(low_confidence) == 0, low_confidence
