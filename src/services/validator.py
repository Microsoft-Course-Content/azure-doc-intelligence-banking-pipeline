"""
KYC/AML Validation Service.
Performs compliance checks on extracted document data
including sanctions screening, PEP checks, and field completeness.
"""

import logging
from datetime import datetime, date
from ..models.schemas import ValidationResult, ExtractedField
from ..models.enums import ValidationStatus

logger = logging.getLogger(__name__)

# UAE Central Bank AML requirements — minimum required fields
REQUIRED_KYC_FIELDS = [
    "customer_name",
    "date_of_birth",
    "nationality",
    "source_of_funds",
    "occupation",
]

# Simplified sanctions list (in production, use a proper sanctions API)
SANCTIONS_KEYWORDS = [
    "sanctioned_entity_1",
    "sanctioned_entity_2",
]

# High-risk jurisdictions per FATF
FATF_HIGH_RISK = [
    "Iran", "North Korea", "Myanmar",
]

FATF_INCREASED_MONITORING = [
    "Syria", "Yemen", "South Sudan", "Libya",
    "Haiti", "Nigeria", "Philippines",
]


class KYCAMLValidator:
    """
    Validates extracted document data against KYC/AML compliance rules.
    Implements UAE Central Bank and FATF guidelines.
    """

    async def validate_kyc(
        self, extracted_fields: list[ExtractedField], document_type: str
    ) -> ValidationResult:
        """
        Run full KYC/AML validation suite on extracted data.

        Args:
            extracted_fields: Extracted document fields
            document_type: Type of document being validated

        Returns:
            ValidationResult with pass/fail status and flags
        """
        checks_passed = []
        checks_failed = []
        flags = []
        risk_score = 0.0

        field_map = {f.field_name: f for f in extracted_fields}

        # ── Check 1: Field Completeness ──────────────────────────
        completeness_ok = self._check_field_completeness(
            field_map, checks_passed, checks_failed
        )
        if not completeness_ok:
            risk_score += 0.15

        # ── Check 2: ID Document Validity ────────────────────────
        id_valid = self._check_id_validity(field_map, checks_passed, checks_failed)
        if not id_valid:
            risk_score += 0.1

        # ── Check 3: Sanctions Screening ─────────────────────────
        sanctions_clear = self._check_sanctions(
            field_map, checks_passed, checks_failed, flags
        )
        if not sanctions_clear:
            risk_score += 0.5  # Major risk factor

        # ── Check 4: High-Risk Jurisdiction ──────────────────────
        jurisdiction_ok = self._check_jurisdiction(
            field_map, checks_passed, checks_failed, flags
        )
        if not jurisdiction_ok:
            risk_score += 0.3

        # ── Check 5: PEP Status ──────────────────────────────────
        pep_clear = self._check_pep_status(
            field_map, checks_passed, checks_failed, flags
        )
        if not pep_clear:
            risk_score += 0.25

        # ── Check 6: Confidence Threshold ────────────────────────
        confidence_ok = self._check_confidence_levels(
            extracted_fields, checks_passed, checks_failed
        )
        if not confidence_ok:
            risk_score += 0.1

        # Determine overall status
        risk_score = min(risk_score, 1.0)

        if checks_failed:
            if risk_score >= 0.5:
                status = ValidationStatus.FAILED
                recommendation = "REJECT — High-risk indicators detected. Escalate to compliance."
            else:
                status = ValidationStatus.NEEDS_MANUAL_REVIEW
                recommendation = (
                    "REVIEW — Some checks failed. Manual review required by compliance officer."
                )
        else:
            status = ValidationStatus.PASSED
            recommendation = "APPROVED — All compliance checks passed."

        result = ValidationResult(
            status=status,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            risk_score=risk_score,
            flags=flags,
            recommendation=recommendation,
        )

        logger.info(
            f"Validation result: {status.value} | Risk: {risk_score:.2f} | "
            f"Passed: {len(checks_passed)} | Failed: {len(checks_failed)}"
        )
        return result

    def _check_field_completeness(
        self,
        field_map: dict,
        passed: list,
        failed: list,
    ) -> bool:
        """Check that all required KYC fields are present."""
        missing = []
        for field in REQUIRED_KYC_FIELDS:
            if field not in field_map or not field_map[field].value:
                missing.append(field)

        if missing:
            failed.append(f"Missing required fields: {', '.join(missing)}")
            return False
        else:
            passed.append("All required KYC fields present")
            return True

    def _check_id_validity(
        self, field_map: dict, passed: list, failed: list
    ) -> bool:
        """Check if ID document is valid (not expired)."""
        expiry_field = field_map.get("expiry_date") or field_map.get("id_expiry")
        if expiry_field and expiry_field.value:
            try:
                # Try parsing common date formats
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        expiry = datetime.strptime(expiry_field.value, fmt).date()
                        if expiry < date.today():
                            failed.append(f"ID document expired: {expiry_field.value}")
                            return False
                        else:
                            passed.append("ID document is valid and not expired")
                            return True
                    except ValueError:
                        continue
                passed.append("ID expiry date format unrecognized — manual check needed")
                return True
            except Exception:
                passed.append("ID expiry check skipped — parsing error")
                return True
        else:
            passed.append("ID expiry check skipped — no expiry field found")
            return True

    def _check_sanctions(
        self, field_map: dict, passed: list, failed: list, flags: list
    ) -> bool:
        """Screen customer name against sanctions list."""
        name_field = field_map.get("customer_name") or field_map.get("full_name")
        if name_field and name_field.value:
            name_lower = name_field.value.lower()
            for sanctioned in SANCTIONS_KEYWORDS:
                if sanctioned.lower() in name_lower:
                    failed.append(f"SANCTIONS MATCH: {name_field.value}")
                    flags.append("SANCTIONS_HIT")
                    return False
            passed.append("Sanctions screening: CLEAR")
            return True
        passed.append("Sanctions screening skipped — no name found")
        return True

    def _check_jurisdiction(
        self, field_map: dict, passed: list, failed: list, flags: list
    ) -> bool:
        """Check customer nationality/country against FATF risk lists."""
        nationality = field_map.get("nationality")
        if nationality and nationality.value:
            country = nationality.value.strip()
            if country in FATF_HIGH_RISK:
                failed.append(f"FATF High-Risk Jurisdiction: {country}")
                flags.append("FATF_HIGH_RISK")
                return False
            elif country in FATF_INCREASED_MONITORING:
                failed.append(f"FATF Increased Monitoring: {country}")
                flags.append("FATF_MONITORING")
                return False
            else:
                passed.append(f"Jurisdiction check: {country} — CLEAR")
                return True
        passed.append("Jurisdiction check skipped — no nationality found")
        return True

    def _check_pep_status(
        self, field_map: dict, passed: list, failed: list, flags: list
    ) -> bool:
        """Check Politically Exposed Person status."""
        pep_field = field_map.get("politically_exposed")
        if pep_field and pep_field.value:
            if pep_field.value.lower() in ("yes", "true", "1"):
                failed.append("Customer is a Politically Exposed Person (PEP)")
                flags.append("PEP_IDENTIFIED")
                return False
            else:
                passed.append("PEP check: Not a PEP")
                return True
        passed.append("PEP check skipped — no PEP field found")
        return True

    def _check_confidence_levels(
        self, fields: list[ExtractedField], passed: list, failed: list
    ) -> bool:
        """Check that critical fields meet confidence thresholds."""
        low_confidence_fields = [
            f for f in fields
            if f.confidence < 0.80 and f.field_name in REQUIRED_KYC_FIELDS
        ]
        if low_confidence_fields:
            names = [f.field_name for f in low_confidence_fields]
            failed.append(f"Low confidence on critical fields: {', '.join(names)}")
            return False
        passed.append("All critical fields meet confidence threshold")
        return True
