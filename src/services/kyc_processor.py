"""
KYC (Know Your Customer) Document Processing Service.
Extracts customer information from KYC forms and performs
initial risk assessment based on extracted data.
"""

import json
import logging
from openai import AzureOpenAI
from ..config import get_settings
from ..models.schemas import KYCFormResult, ExtractedField

logger = logging.getLogger(__name__)

KYC_EXTRACTION_PROMPT = """You are a KYC document extraction specialist for a bank.
Analyze the following document text extracted from a KYC/account opening form 
and extract ALL available fields into structured JSON.

Required fields (return null if not found):
{
    "customer_name": "Full name of the customer",
    "date_of_birth": "DOB in YYYY-MM-DD format",
    "nationality": "Customer nationality",
    "occupation": "Occupation or profession",
    "employer": "Employer name",
    "annual_income": "Annual income with currency",
    "source_of_funds": "Source of funds/wealth",
    "purpose_of_account": "Purpose of opening account",
    "politically_exposed": "yes/no — is the person a PEP",
    "residential_address": "Full residential address",
    "phone_number": "Contact phone number",
    "email": "Email address",
    "id_type": "Type of ID document provided",
    "id_number": "ID document number",
    "id_expiry": "ID expiry date"
}

Return ONLY the JSON object, no additional text.
"""

# Risk scoring weights for KYC assessment
RISK_FACTORS = {
    "high_risk_countries": [
        "Iran", "North Korea", "Syria", "Yemen", "Libya",
        "Somalia", "South Sudan", "Myanmar"
    ],
    "high_risk_occupations": [
        "money exchanger", "casino", "gambling", "cryptocurrency",
        "arms dealer", "precious metals", "real estate agent"
    ],
    "pep_risk_multiplier": 2.0,
    "missing_field_penalty": 0.1,
}


class KYCProcessor:
    """
    Processes KYC forms using Azure AI Document Intelligence layout
    extraction combined with GPT-4o for structured field extraction.
    """

    def __init__(self):
        settings = get_settings()
        self.client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        self.deployment = settings.azure_openai_deployment_name

    async def process(
        self, extracted_fields: list[ExtractedField], raw_result
    ) -> KYCFormResult:
        """
        Process KYC form using layout text + GPT-4o extraction.

        Args:
            extracted_fields: Fields from Document Intelligence layout extraction
            raw_result: Raw AnalyzeResult

        Returns:
            Structured KYCFormResult
        """
        # Combine all extracted text
        full_text = "\n".join(
            f.value for f in extracted_fields if f.value and f.field_name == "text_line"
        )

        # Use GPT-4o to extract structured KYC fields from raw text
        kyc_data = await self._extract_with_gpt(full_text)

        # Build KYCFormResult
        result = KYCFormResult(
            customer_name=self._make_field("customer_name", kyc_data.get("customer_name")),
            date_of_birth=self._make_field("date_of_birth", kyc_data.get("date_of_birth")),
            nationality=self._make_field("nationality", kyc_data.get("nationality")),
            occupation=self._make_field("occupation", kyc_data.get("occupation")),
            employer=self._make_field("employer", kyc_data.get("employer")),
            annual_income=self._make_field("annual_income", kyc_data.get("annual_income")),
            source_of_funds=self._make_field("source_of_funds", kyc_data.get("source_of_funds")),
            purpose_of_account=self._make_field(
                "purpose_of_account", kyc_data.get("purpose_of_account")
            ),
            politically_exposed=self._make_field(
                "politically_exposed", kyc_data.get("politically_exposed")
            ),
        )

        # Calculate initial risk rating
        result.risk_rating = self._calculate_risk_rating(kyc_data)

        # Add ID document info
        if kyc_data.get("id_type") or kyc_data.get("id_number"):
            result.id_documents = [
                {
                    "type": kyc_data.get("id_type", "Unknown"),
                    "number": kyc_data.get("id_number", ""),
                    "expiry": kyc_data.get("id_expiry", ""),
                }
            ]

        logger.info(
            f"KYC processed: {result.customer_name.value if result.customer_name else 'N/A'} "
            f"— Risk: {result.risk_rating}"
        )
        return result

    async def _extract_with_gpt(self, document_text: str) -> dict:
        """Use GPT-4o to extract structured fields from KYC form text."""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": KYC_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": f"Extract KYC fields from this document:\n\n{document_text}",
                    },
                ],
                max_tokens=1000,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"GPT extraction failed: {str(e)}")
            return {}

    def _make_field(
        self, field_name: str, value: str | None, confidence: float = 0.85
    ) -> ExtractedField | None:
        """Create an ExtractedField if value exists."""
        if value and value.lower() not in ("null", "none", "n/a", ""):
            return ExtractedField(
                field_name=field_name, value=value, confidence=confidence
            )
        return None

    def _calculate_risk_rating(self, kyc_data: dict) -> str:
        """
        Calculate KYC risk rating based on extracted data.
        Returns: 'low', 'medium', 'high', or 'very_high'
        """
        risk_score = 0.0

        # Check nationality against high-risk countries
        nationality = (kyc_data.get("nationality") or "").strip()
        if nationality in RISK_FACTORS["high_risk_countries"]:
            risk_score += 0.4

        # Check occupation
        occupation = (kyc_data.get("occupation") or "").lower()
        for high_risk_occ in RISK_FACTORS["high_risk_occupations"]:
            if high_risk_occ in occupation:
                risk_score += 0.3
                break

        # PEP status
        pep = (kyc_data.get("politically_exposed") or "").lower()
        if pep in ("yes", "true", "1"):
            risk_score *= RISK_FACTORS["pep_risk_multiplier"]
            risk_score += 0.3

        # Missing critical fields penalty
        critical_fields = [
            "customer_name", "date_of_birth", "nationality",
            "source_of_funds", "occupation"
        ]
        for field in critical_fields:
            if not kyc_data.get(field):
                risk_score += RISK_FACTORS["missing_field_penalty"]

        # Map score to rating
        if risk_score >= 0.7:
            return "very_high"
        elif risk_score >= 0.4:
            return "high"
        elif risk_score >= 0.2:
            return "medium"
        else:
            return "low"
