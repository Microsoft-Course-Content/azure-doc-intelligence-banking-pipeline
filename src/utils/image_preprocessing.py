"""
Image Preprocessing Utilities.
OpenCV-based preprocessing to improve OCR and extraction accuracy
for banking documents (cheques, forms, IDs).
"""

import cv2
import numpy as np
from io import BytesIO
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """
    Preprocesses document images before sending to Azure AI
    Document Intelligence for improved extraction accuracy.
    """

    @staticmethod
    def bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
        """Convert raw bytes to OpenCV image array."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image from bytes")
        return img

    @staticmethod
    def cv2_to_bytes(img: np.ndarray, format: str = ".png") -> bytes:
        """Convert OpenCV image array back to bytes."""
        success, buffer = cv2.imencode(format, img)
        if not success:
            raise ValueError("Failed to encode image to bytes")
        return buffer.tobytes()

    @staticmethod
    def deskew(image: np.ndarray) -> np.ndarray:
        """
        Correct document skew/rotation using Hough Line Transform.
        Critical for cheques and forms that may be scanned at an angle.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=100,
            minLineLength=100, maxLineGap=10
        )

        if lines is None:
            return image

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) < 45:  # Filter out vertical lines
                angles.append(angle)

        if not angles:
            return image

        median_angle = np.median(angles)

        if abs(median_angle) < 0.5:
            return image  # Skip if skew is negligible

        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(
            image, rotation_matrix, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )

        logger.info(f"Deskewed image by {median_angle:.2f} degrees")
        return rotated

    @staticmethod
    def enhance_contrast(image: np.ndarray) -> np.ndarray:
        """
        Enhance image contrast using CLAHE (Contrast Limited 
        Adaptive Histogram Equalization) — improves OCR on 
        low-contrast documents like faded cheques.
        """
        if len(image.shape) == 3:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l_channel, a, b = cv2.split(lab)
        else:
            l_channel = image

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_l = clahe.apply(l_channel)

        if len(image.shape) == 3:
            enhanced = cv2.merge([enhanced_l, a, b])
            return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        return enhanced_l

    @staticmethod
    def remove_noise(image: np.ndarray) -> np.ndarray:
        """
        Remove noise using bilateral filtering.
        Preserves edges while smoothing — important for
        maintaining text clarity in banking documents.
        """
        return cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)

    @staticmethod
    def binarize(image: np.ndarray) -> np.ndarray:
        """
        Convert to binary (black & white) using adaptive thresholding.
        Best for documents with uneven lighting conditions.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, blockSize=11, C=2
        )
        return binary

    @staticmethod
    def remove_borders(image: np.ndarray, border_size: int = 10) -> np.ndarray:
        """Remove dark borders from scanned documents."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            margin = border_size
            x, y = max(0, x - margin), max(0, y - margin)
            return image[y:y + h + 2 * margin, x:x + w + 2 * margin]

        return image

    @staticmethod
    def resize_for_ocr(
        image: np.ndarray, target_dpi: int = 300, current_dpi: int = 150
    ) -> np.ndarray:
        """
        Resize image to target DPI for optimal OCR accuracy.
        Azure AI Document Intelligence works best at 300 DPI.
        """
        scale_factor = target_dpi / current_dpi
        if abs(scale_factor - 1.0) < 0.1:
            return image  # Already at target DPI

        width = int(image.shape[1] * scale_factor)
        height = int(image.shape[0] * scale_factor)
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_CUBIC)

    def preprocess_cheque(self, image_bytes: bytes) -> bytes:
        """
        Full preprocessing pipeline optimized for cheque images.
        
        Pipeline: Deskew → Denoise → Enhance Contrast → Resize
        """
        img = self.bytes_to_cv2(image_bytes)
        img = self.deskew(img)
        img = self.remove_noise(img)
        img = self.enhance_contrast(img)
        img = self.resize_for_ocr(img)
        logger.info("Cheque preprocessing complete")
        return self.cv2_to_bytes(img)

    def preprocess_id_card(self, image_bytes: bytes) -> bytes:
        """
        Preprocessing pipeline for ID cards and passports.
        
        Pipeline: Deskew → Remove Borders → Enhance → Resize
        """
        img = self.bytes_to_cv2(image_bytes)
        img = self.deskew(img)
        img = self.remove_borders(img)
        img = self.enhance_contrast(img)
        img = self.resize_for_ocr(img)
        logger.info("ID card preprocessing complete")
        return self.cv2_to_bytes(img)

    def preprocess_form(self, image_bytes: bytes) -> bytes:
        """
        Preprocessing pipeline for KYC forms and applications.
        
        Pipeline: Deskew → Denoise → Enhance → Binarize (optional)
        """
        img = self.bytes_to_cv2(image_bytes)
        img = self.deskew(img)
        img = self.remove_noise(img)
        img = self.enhance_contrast(img)
        logger.info("Form preprocessing complete")
        return self.cv2_to_bytes(img)
