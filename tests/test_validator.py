"""Tests for KYC/AML validation service."""

import pytest
from src.models.schemas import ExtractedField
from src.models.enums import ValidationStatus
from src.services.validator import KYCAMLValidator


@pytest.fixture
def validator():
    return KYCAMLValidator()


def _make_field(name: str, value: str, confidence: float = 0.90) -> ExtractedField:
    return ExtractedField(field_name=name, value=value, confidence=confidence)


@pytest.mark.asyncio
async def test_complete_kyc_passes(validator):
    """All required fields present, no risk factors → should pass."""
    fields = [
        _make_field("customer_name", "Ahmed Ali"),
        _make_field("date_of_birth", "1985-06-15"),
        _make_field("nationality", "United Arab Emirates"),
        _make_field("source_of_funds", "Employment salary"),
        _make_field("occupation", "Software Engineer"),
        _make_field("politically_exposed", "no"),
    ]
    result = await validator.validate_kyc(fields, "kyc_form")
    assert result.status == ValidationStatus.PASSED
    assert result.risk_score < 0.2


@pytest.mark.asyncio
async def test_missing_fields_fails(validator):
    """Missing required fields → should flag for review."""
    fields = [
        _make_field("customer_name", "Ahmed Ali"),
        # Missing: date_of_birth, nationality, source_of_funds, occupation
    ]
    result = await validator.validate_kyc(fields, "kyc_form")
    assert result.status in (ValidationStatus.FAILED, ValidationStatus.NEEDS_MANUAL_REVIEW)
    assert any("Missing" in c for c in result.checks_failed)


@pytest.mark.asyncio
async def test_high_risk_country(validator):
    """FATF high-risk jurisdiction → should fail."""
    fields = [
        _make_field("customer_name", "Test User"),
        _make_field("date_of_birth", "1990-01-01"),
        _make_field("nationality", "Iran"),
        _make_field("source_of_funds", "Business"),
        _make_field("occupation", "Trader"),
    ]
    result = await validator.validate_kyc(fields, "kyc_form")
    assert "FATF_HIGH_RISK" in result.flags
    assert result.risk_score >= 0.3


@pytest.mark.asyncio
async def test_pep_identified(validator):
    """Politically Exposed Person → should flag."""
    fields = [
        _make_field("customer_name", "Minister Example"),
        _make_field("date_of_birth", "1975-03-20"),
        _make_field("nationality", "Bahrain"),
        _make_field("source_of_funds", "Government salary"),
        _make_field("occupation", "Government official"),
        _make_field("politically_exposed", "yes"),
    ]
    result = await validator.validate_kyc(fields, "kyc_form")
    assert "PEP_IDENTIFIED" in result.flags
    assert result.risk_score > 0.2


@pytest.mark.asyncio
async def test_low_confidence_flags(validator):
    """Low confidence on critical fields → should flag."""
    fields = [
        _make_field("customer_name", "Test", confidence=0.50),
        _make_field("date_of_birth", "1990-01-01", confidence=0.75),
        _make_field("nationality", "UAE", confidence=0.60),
        _make_field("source_of_funds", "Salary", confidence=0.90),
        _make_field("occupation", "Engineer", confidence=0.90),
    ]
    result = await validator.validate_kyc(fields, "kyc_form")
    assert any("confidence" in c.lower() for c in result.checks_failed)
