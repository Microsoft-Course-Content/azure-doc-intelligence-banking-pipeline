"""
Azure Blob Storage Connector.
Handles document upload to Azure Blob Storage and result retrieval.
Supports local file fallback when Azure is not configured.
"""

import os
import json
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Azure SDK import — graceful fallback if not installed
try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_BLOB_AVAILABLE = True
except ImportError:
    AZURE_BLOB_AVAILABLE = False
    logger.warning("azure-storage-blob not installed. Using local storage fallback.")


class BlobStorageConnector:
    """
    Manages document storage in Azure Blob Storage.
    Falls back to local filesystem when Azure is not configured.
    """

    def __init__(self):
        self.connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        self.container_uploads = os.getenv("BLOB_CONTAINER_UPLOADS", "banking-doc-uploads")
        self.container_results = os.getenv("BLOB_CONTAINER_RESULTS", "banking-doc-results")
        self.use_azure = bool(self.connection_string) and AZURE_BLOB_AVAILABLE
        self.blob_service = None

        if self.use_azure:
            try:
                self.blob_service = BlobServiceClient.from_connection_string(self.connection_string)
                self._ensure_containers()
                logger.info("Azure Blob Storage connected")
            except Exception as e:
                logger.warning(f"Azure Blob init failed: {e}. Using local storage.")
                self.use_azure = False

        if not self.use_azure:
            os.makedirs("uploads", exist_ok=True)
            os.makedirs("outputs", exist_ok=True)
            logger.info("Using local file storage")

    def _ensure_containers(self):
        """Create blob containers if they don't exist."""
        for container_name in [self.container_uploads, self.container_results]:
            try:
                self.blob_service.create_container(container_name)
                logger.info(f"Created container: {container_name}")
            except Exception:
                pass  # Container already exists

    async def upload_document(
        self, file_bytes: bytes, filename: str, content_type: str = "application/octet-stream"
    ) -> dict:
        """
        Upload a document to storage.

        Returns:
            dict with storage_path, storage_type, upload_id
        """
        upload_id = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{filename}"

        if self.use_azure:
            blob_client = self.blob_service.get_blob_client(
                container=self.container_uploads, blob=upload_id
            )
            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
            storage_path = f"https://{self.blob_service.account_name}.blob.core.windows.net/{self.container_uploads}/{upload_id}"
            logger.info(f"Uploaded to Azure Blob: {upload_id}")
        else:
            local_path = os.path.join("uploads", upload_id)
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            storage_path = local_path
            logger.info(f"Saved locally: {local_path}")

        return {
            "upload_id": upload_id,
            "storage_path": storage_path,
            "storage_type": "azure_blob" if self.use_azure else "local",
            "filename": filename,
            "size_bytes": len(file_bytes),
        }

    async def save_result(self, document_id: str, result: dict) -> str:
        """Save processing result as JSON."""
        result_filename = f"{document_id}_result.json"
        result_json = json.dumps(result, indent=2, default=str)

        if self.use_azure:
            blob_client = self.blob_service.get_blob_client(
                container=self.container_results, blob=result_filename
            )
            blob_client.upload_blob(
                result_json,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
            path = f"https://{self.blob_service.account_name}.blob.core.windows.net/{self.container_results}/{result_filename}"
        else:
            path = os.path.join("outputs", result_filename)
            with open(path, "w") as f:
                f.write(result_json)

        return path

    async def get_result(self, document_id: str) -> dict | None:
        """Retrieve a processing result."""
        result_filename = f"{document_id}_result.json"

        try:
            if self.use_azure:
                blob_client = self.blob_service.get_blob_client(
                    container=self.container_results, blob=result_filename
                )
                data = blob_client.download_blob().readall()
                return json.loads(data)
            else:
                path = os.path.join("outputs", result_filename)
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return json.load(f)
                return None
        except Exception as e:
            logger.error(f"Failed to retrieve result {document_id}: {e}")
            return None

    def get_storage_info(self) -> dict:
        """Get storage configuration info for health check."""
        return {
            "storage_type": "azure_blob" if self.use_azure else "local",
            "uploads_container": self.container_uploads if self.use_azure else "uploads/",
            "results_container": self.container_results if self.use_azure else "outputs/",
            "status": "connected" if self.use_azure else "local_fallback",
        }
