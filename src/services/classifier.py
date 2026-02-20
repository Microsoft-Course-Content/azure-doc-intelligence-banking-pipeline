"""
Document Classifier using Azure OpenAI GPT-4o Vision.
Classifies incoming banking documents into predefined categories
using multimodal capabilities (image + text understanding).
"""

import base64
import logging
from pathlib import Path
from openai import AzureOpenAI
from ..config import get_settings
from ..models.enums import DocumentType

logger = logging.getLogger(__name__)

CLASSIFICATION_SYSTEM_PROMPT = """You are a banking document classification expert. 
Analyze the provided document image and classify it into exactly ONE of these categories:

- invoice: Commercial invoices, bills, payment requests from vendors
- cheque: Bank cheques, demand drafts, pay orders
- id_card: Passports, national ID cards, driving licenses, Emirates ID
- kyc_form: Know Your Customer forms, account opening forms, customer due diligence forms
- trade_finance: Letters of credit, bills of lading, SWIFT messages, trade documents
- receipt: Payment receipts, transaction confirmations
- bank_statement: Account statements, transaction summaries
- unknown: Cannot determine document type

Respond with ONLY a JSON object in this exact format:
{
    "document_type": "<type>",
    "confidence": <float 0-1>,
    "reasoning": "<brief explanation>"
}
"""


class DocumentClassifier:
    """Classifies banking documents using GPT-4o vision capabilities."""

    def __init__(self):
        settings = get_settings()
        self.client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        self.deployment = settings.azure_openai_deployment_name

    def _encode_image(self, file_bytes: bytes, content_type: str) -> str:
        """Encode image bytes to base64 for GPT-4o vision."""
        return base64.b64encode(file_bytes).decode("utf-8")

    def _get_media_type(self, filename: str) -> str:
        """Determine media type from file extension."""
        ext = Path(filename).suffix.lower()
        media_types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
        }
        return media_types.get(ext, "application/octet-stream")

    async def classify(
        self, file_bytes: bytes, filename: str
    ) -> tuple[DocumentType, float, str]:
        """
        Classify a banking document using GPT-4o multimodal vision.

        Args:
            file_bytes: Raw file bytes
            filename: Original filename for media type detection

        Returns:
            Tuple of (DocumentType, confidence_score, reasoning)
        """
        try:
            media_type = self._get_media_type(filename)
            base64_image = self._encode_image(file_bytes, media_type)

            logger.info(f"Classifying document: {filename} ({media_type})")

            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Classify this banking document. Return only the JSON response.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{base64_image}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=300,
                temperature=0.1,  # Low temperature for consistent classification
                response_format={"type": "json_object"},
            )

            import json
            result = json.loads(response.choices[0].message.content)

            doc_type = DocumentType(result.get("document_type", "unknown"))
            confidence = float(result.get("confidence", 0.0))
            reasoning = result.get("reasoning", "No reasoning provided")

            logger.info(
                f"Classification result: {doc_type.value} "
                f"(confidence: {confidence:.2f}) — {reasoning}"
            )

            return doc_type, confidence, reasoning

        except Exception as e:
            logger.error(f"Classification failed for {filename}: {str(e)}")
            return DocumentType.UNKNOWN, 0.0, f"Classification error: {str(e)}"

    async def classify_batch(
        self, files: list[tuple[bytes, str]]
    ) -> list[tuple[DocumentType, float, str]]:
        """
        Classify multiple documents.

        Args:
            files: List of (file_bytes, filename) tuples

        Returns:
            List of classification results
        """
        results = []
        for file_bytes, filename in files:
            result = await self.classify(file_bytes, filename)
            results.append(result)
        return results
