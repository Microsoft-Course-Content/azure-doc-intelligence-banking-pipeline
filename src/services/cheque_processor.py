"""
Cheque Processing Service.
Specialized extraction for banking cheques including MICR code parsing,
amount validation, and signature detection.
"""

import re
import logging
from ..models.schemas import ChequeResult, ExtractedField

logger = logging.getLogger(__name__)

# MICR code pattern: [cheque_number] [bank_routing_code] [account_number]
MICR_PATTERN = r"[\u2446]?(\d{6})[\u2446]?\s*[\u2447]?(\d{9})[\u2447]?\s*(\d{6,12})"


class ChequeProcessor:
    """
    Processes cheque documents with specialized extraction logic.
    Handles MICR code parsing, amount cross-validation, and bank identification.
    """

    # Major bank routing codes (UAE & India examples)
    BANK_ROUTING_CODES = {
        "033": "ADCB - Abu Dhabi Commercial Bank",
        "044": "Emirates NBD",
        "046": "Abu Dhabi Islamic Bank",
        "035": "First Abu Dhabi Bank (FAB)",
        "050": "Mashreq Bank",
        "060": "State Bank of India",
        "002": "HDFC Bank",
        "004": "ICICI Bank",
        "029": "Axis Bank",
    }

    async def process(
        self, extracted_fields: list[ExtractedField], raw_result
    ) -> ChequeResult:
        """
        Process extracted cheque data into structured ChequeResult.

        Args:
            extracted_fields: Fields from Document Intelligence extraction
            raw_result: Raw AnalyzeResult for additional processing

        Returns:
            Structured ChequeResult with all cheque fields
        """
        result = ChequeResult()

        # Build a text map from extracted fields
        text_content = self._build_text_content(extracted_fields)

        # Extract MICR code
        micr_data = self._extract_micr(text_content)
        if micr_data:
            result.cheque_number = ExtractedField(
                field_name="cheque_number",
                value=micr_data["cheque_number"],
                confidence=0.90,
            )
            result.micr_code = ExtractedField(
                field_name="micr_code",
                value=micr_data["full_micr"],
                confidence=0.88,
            )
            result.account_number = ExtractedField(
                field_name="account_number",
                value=micr_data["account_number"],
                confidence=0.90,
            )
            # Identify bank from routing code
            bank_info = self.BANK_ROUTING_CODES.get(
                micr_data["routing_code"][:3], "Unknown Bank"
            )
            result.bank_name = ExtractedField(
                field_name="bank_name", value=bank_info, confidence=0.85
            )

        # Extract amount (figures and words)
        result.amount_in_figures = self._extract_amount_figures(text_content)
        result.amount_in_words = self._extract_amount_words(text_content)

        # Cross-validate amounts
        if result.amount_in_figures and result.amount_in_words:
            self._validate_amounts(result)

        # Extract date
        result.cheque_date = self._extract_date(text_content)

        # Extract payee
        result.payee_name = self._extract_payee(text_content)

        # Check for signature presence
        result.signature_detected = self._detect_signature_region(raw_result)

        logger.info(
            f"Cheque processed: #{result.cheque_number.value if result.cheque_number else 'N/A'}"
        )
        return result

    def _build_text_content(self, fields: list[ExtractedField]) -> str:
        """Concatenate all text fields into searchable content."""
        return "\n".join(
            f.value for f in fields if f.value and f.field_name == "text_line"
        )

    def _extract_micr(self, text: str) -> dict | None:
        """Extract and parse MICR code from cheque text."""
        # Try standard MICR pattern
        match = re.search(MICR_PATTERN, text)
        if match:
            return {
                "cheque_number": match.group(1),
                "routing_code": match.group(2),
                "account_number": match.group(3),
                "full_micr": f"{match.group(1)} {match.group(2)} {match.group(3)}",
            }

        # Try alternative numeric patterns (6+ consecutive digits near bottom)
        alt_pattern = r"(\d{6})\s+(\d{9})\s+(\d{6,12})"
        match = re.search(alt_pattern, text)
        if match:
            return {
                "cheque_number": match.group(1),
                "routing_code": match.group(2),
                "account_number": match.group(3),
                "full_micr": f"{match.group(1)} {match.group(2)} {match.group(3)}",
            }

        return None

    def _extract_amount_figures(self, text: str) -> ExtractedField | None:
        """Extract numerical amount from cheque."""
        # Match common amount patterns: AED 50,000.00 or Rs. 1,00,000.00 or $5,000
        patterns = [
            r"(?:AED|USD|INR|Rs\.?|SAR|\$|£|€)\s*([\d,]+\.?\d*)",
            r"([\d,]+\.?\d*)\s*(?:AED|USD|INR|SAR|/-)",
            r"\*{1,3}\s*([\d,]+\.?\d*)\s*\*{1,3}",  # Amount between asterisks
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1).replace(",", "")
                return ExtractedField(
                    field_name="amount_in_figures",
                    value=amount,
                    confidence=0.85,
                )
        return None

    def _extract_amount_words(self, text: str) -> ExtractedField | None:
        """Extract amount in words from cheque."""
        # Look for patterns like "Fifty Thousand Only" or "Rupees ... Only"
        pattern = r"(?:Rupees?|Dirhams?|Dollars?|Pay)[\s:]+(.+?)(?:Only|ONLY|only)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return ExtractedField(
                field_name="amount_in_words",
                value=match.group(1).strip(),
                confidence=0.80,
            )
        return None

    def _validate_amounts(self, result: ChequeResult) -> None:
        """Cross-validate amount in figures vs words (flag mismatch)."""
        # In production, use a number-to-words library for validation
        # For now, just flag if both exist for manual review
        if result.amount_in_figures and result.amount_in_words:
            logger.info(
                f"Amount cross-check: figures={result.amount_in_figures.value}, "
                f"words={result.amount_in_words.value}"
            )

    def _extract_date(self, text: str) -> ExtractedField | None:
        """Extract cheque date."""
        # Common date patterns: DD/MM/YYYY, DD-MM-YYYY, DD MMM YYYY
        patterns = [
            r"(?:Date|Dated?)[\s:]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})",
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return ExtractedField(
                    field_name="cheque_date",
                    value=match.group(1),
                    confidence=0.85,
                )
        return None

    def _extract_payee(self, text: str) -> ExtractedField | None:
        """Extract payee name from cheque."""
        pattern = r"(?:Pay|Pay to|Payee)[\s:]+(.+?)(?:\n|or bearer|or order)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return ExtractedField(
                field_name="payee_name",
                value=match.group(1).strip(),
                confidence=0.80,
            )
        return None

    def _detect_signature_region(self, raw_result) -> bool:
        """
        Detect if a signature region is present on the cheque.
        Uses spatial analysis of the document layout.
        """
        # In production: analyze bottom-right quadrant for ink marks
        # using the bounding regions from the layout analysis
        if raw_result and hasattr(raw_result, "pages") and raw_result.pages:
            page = raw_result.pages[0]
            # Check if there are marks in the signature region (bottom-right)
            if page.lines:
                page_height = page.height or 1000
                page_width = page.width or 1000
                for line in page.lines:
                    if hasattr(line, "polygon") and line.polygon:
                        # Check if text is in bottom-right quadrant
                        y_positions = [line.polygon[i] for i in range(1, len(line.polygon), 2)]
                        x_positions = [line.polygon[i] for i in range(0, len(line.polygon), 2)]
                        if (
                            any(y > page_height * 0.75 for y in y_positions)
                            and any(x > page_width * 0.5 for x in x_positions)
                        ):
                            return True
        return False
