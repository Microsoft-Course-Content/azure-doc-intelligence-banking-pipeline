"""
Invoice Processing Service.
Leverages Azure AI Document Intelligence prebuilt-invoice model
for structured extraction of vendor invoices and payment documents.
"""

import logging
from ..models.schemas import InvoiceResult, ExtractedField

logger = logging.getLogger(__name__)


class InvoiceProcessor:
    """Processes invoices using prebuilt-invoice model results."""

    async def process(
        self, extracted_fields: list[ExtractedField], raw_result
    ) -> InvoiceResult:
        """
        Process extracted invoice data into structured InvoiceResult.

        Args:
            extracted_fields: Fields from prebuilt-invoice extraction
            raw_result: Raw AnalyzeResult from Document Intelligence

        Returns:
            Structured InvoiceResult
        """
        result = InvoiceResult()
        field_map = {f.field_name: f for f in extracted_fields}

        # Map prebuilt invoice fields to our schema
        result.vendor_name = field_map.get("VendorName")
        result.vendor_address = field_map.get("VendorAddress")
        result.invoice_number = field_map.get("InvoiceId")
        result.invoice_date = field_map.get("InvoiceDate")
        result.due_date = field_map.get("DueDate")
        result.subtotal = field_map.get("SubTotal")
        result.tax_amount = field_map.get("TotalTax")
        result.total_amount = field_map.get("InvoiceTotal")
        result.currency = field_map.get("CurrencyCode")
        result.purchase_order = field_map.get("PurchaseOrder")

        # Extract line items from raw result
        result.line_items = self._extract_line_items(raw_result)

        # Validate totals
        self._validate_totals(result)

        logger.info(
            f"Invoice processed: #{result.invoice_number.value if result.invoice_number else 'N/A'} "
            f"— Total: {result.total_amount.value if result.total_amount else 'N/A'}"
        )
        return result

    def _extract_line_items(self, raw_result) -> list[dict]:
        """Extract line items from invoice analysis result."""
        line_items = []

        if not raw_result or not raw_result.documents:
            return line_items

        for doc in raw_result.documents:
            items_field = doc.fields.get("Items") if doc.fields else None
            if items_field and items_field.value_array:
                for item in items_field.value_array:
                    if item.value_object:
                        line_item = {}
                        for key, val in item.value_object.items():
                            if val.value_string:
                                line_item[key] = val.value_string
                            elif val.value_number:
                                line_item[key] = val.value_number
                            elif val.value_currency:
                                line_item[key] = val.value_currency.amount
                            elif val.content:
                                line_item[key] = val.content
                        line_items.append(line_item)

        return line_items

    def _validate_totals(self, result: InvoiceResult) -> None:
        """Validate that subtotal + tax = total (flag discrepancies)."""
        try:
            if result.subtotal and result.tax_amount and result.total_amount:
                subtotal = float(result.subtotal.value.replace(",", "").replace("$", ""))
                tax = float(result.tax_amount.value.replace(",", "").replace("$", ""))
                total = float(result.total_amount.value.replace(",", "").replace("$", ""))

                expected = subtotal + tax
                if abs(expected - total) > 0.01:
                    logger.warning(
                        f"Invoice total mismatch: subtotal({subtotal}) + "
                        f"tax({tax}) = {expected}, but total = {total}"
                    )
        except (ValueError, TypeError, AttributeError):
            pass  # Skip validation if values can't be parsed
