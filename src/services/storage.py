"""
Database Persistence Layer.
Stores processed document results in Azure SQL Database
with full audit trail for banking compliance.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from ..config import get_settings
from ..models.schemas import DocumentProcessResponse

logger = logging.getLogger(__name__)


class DocumentStorage:
    """
    Handles persistence of processed documents to Azure SQL.
    Maintains audit trail and supports retrieval for compliance.
    """

    def __init__(self):
        self.connection_string = get_settings().database_connection_string
        self._connection = None

    async def _get_connection(self):
        """Get or create database connection."""
        if not self._connection:
            try:
                import pyodbc

                self._connection = pyodbc.connect(self.connection_string)
                logger.info("Database connection established")
            except Exception as e:
                logger.warning(f"Database connection failed: {e}. Using in-memory storage.")
                self._connection = None
        return self._connection

    async def initialize_tables(self):
        """Create required tables if they don't exist."""
        conn = await self._get_connection()
        if not conn:
            logger.warning("Skipping table initialization — no database connection")
            return

        create_sql = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='processed_documents')
        CREATE TABLE processed_documents (
            document_id NVARCHAR(50) PRIMARY KEY,
            document_type NVARCHAR(50) NOT NULL,
            status NVARCHAR(50) NOT NULL,
            classification_confidence FLOAT,
            extracted_data NVARCHAR(MAX),  -- JSON
            validation_result NVARCHAR(MAX),  -- JSON
            processing_time_ms FLOAT,
            needs_human_review BIT DEFAULT 0,
            review_reason NVARCHAR(500),
            file_hash NVARCHAR(64),
            created_at DATETIME2 DEFAULT GETUTCDATE(),
            updated_at DATETIME2 DEFAULT GETUTCDATE(),
            processed_by NVARCHAR(100) DEFAULT 'system'
        );

        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='audit_log')
        CREATE TABLE audit_log (
            log_id INT IDENTITY(1,1) PRIMARY KEY,
            document_id NVARCHAR(50),
            action NVARCHAR(100),
            details NVARCHAR(MAX),
            performed_by NVARCHAR(100) DEFAULT 'system',
            timestamp DATETIME2 DEFAULT GETUTCDATE()
        );
        """
        try:
            cursor = conn.cursor()
            cursor.execute(create_sql)
            conn.commit()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.error(f"Table initialization failed: {e}")

    async def save_result(self, result: DocumentProcessResponse) -> str:
        """
        Save a processed document result to the database.

        Args:
            result: Complete document processing response

        Returns:
            document_id
        """
        conn = await self._get_connection()

        if not conn:
            # Fallback: log to file for compliance trail
            self._save_to_file(result)
            return result.document_id

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO processed_documents 
                (document_id, document_type, status, classification_confidence,
                 extracted_data, validation_result, processing_time_ms,
                 needs_human_review, review_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                result.document_id,
                result.document_type.value,
                result.status.value,
                result.classification_confidence,
                json.dumps([f.model_dump() for f in result.extracted_fields]),
                json.dumps(result.validation.model_dump()) if result.validation else None,
                result.processing_time_ms,
                result.needs_human_review,
                result.review_reason,
            )

            # Audit log entry
            cursor.execute(
                """
                INSERT INTO audit_log (document_id, action, details)
                VALUES (?, ?, ?)
                """,
                result.document_id,
                "DOCUMENT_PROCESSED",
                f"Type: {result.document_type.value}, Status: {result.status.value}",
            )

            conn.commit()
            logger.info(f"Document saved: {result.document_id}")
            return result.document_id

        except Exception as e:
            logger.error(f"Database save failed: {e}")
            self._save_to_file(result)
            return result.document_id

    async def get_result(self, document_id: str) -> Optional[dict]:
        """Retrieve a processed document by ID."""
        conn = await self._get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM processed_documents WHERE document_id = ?",
                document_id,
            )
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None
        except Exception as e:
            logger.error(f"Database retrieval failed: {e}")
            return None

    def _save_to_file(self, result: DocumentProcessResponse):
        """Fallback: save to JSON file when database is unavailable."""
        import os

        output_dir = "outputs"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{result.document_id}.json")

        with open(filepath, "w") as f:
            json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

        logger.info(f"Result saved to file: {filepath}")

    @staticmethod
    def generate_document_id() -> str:
        """Generate a unique document processing ID."""
        return f"DOC-{uuid.uuid4().hex[:12].upper()}"
