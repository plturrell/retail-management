#!/usr/bin/env python3
"""
Pre-process scanned sales taka PDFs into OCR-optimized images.

Converts Adobe Scan PDFs → high-quality PNG images with:
  - Controlled 300 DPI rendering
  - Adaptive contrast enhancement (CLAHE)
  - Deskew correction
  - Optional binarization for faded handwriting

Usage:
  python preprocess_sales_taka.py
  python preprocess_sales_taka.py --input-dir docs/sales_taka --output-dir data/preprocessed_taka
  python preprocess_sales_taka.py --binarize --deskew
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

DEFAULT_INPUT_DIR = "docs/sales_taka"
DEFAULT_OUTPUT_DIR = "data/preprocessed_taka"
TARGET_DPI = 300


def pdf_to_images(pdf_path: Path, dpi: int = TARGET_DPI) -> list[np.ndarray]:
    """Convert PDF pages to numpy arrays at specified DPI using PyMuPDF."""
    doc = fitz.open(str(pdf_path))
    images: list[np.ndarray] = []
    zoom = dpi / 72.0  # PDF default is 72 DPI
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        # PyMuPDF returns RGB
        images.append(img)
    doc.close()
    return images


def enhance_contrast(image: np.ndarray, clip_limit: float = 2.5, grid_size: int = 8) -> np.ndarray:
    """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization).

    Dramatically improves visibility of faded handwriting and pencil marks
    while preserving already-clear text.
    """
    if len(image.shape) == 3:
        lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
    else:
        l_channel = image
        a_channel = b_channel = None

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid_size, grid_size))
    enhanced_l = clahe.apply(l_channel)

    if a_channel is not None:
        merged = cv2.merge([enhanced_l, a_channel, b_channel])
        return cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)
    return enhanced_l


def adaptive_binarize(image: np.ndarray, block_size: int = 31, c_offset: int = 15) -> np.ndarray:
    """Adaptive thresholding to convert faded handwriting to clean black-on-white.

    Uses Gaussian weighting so text thickness is preserved even when ink
    density varies across the page.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    # Invert so text is white on black, apply threshold, then invert back
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        c_offset,
    )
    return binary


def deskew(image: np.ndarray, max_angle: float = 10.0) -> np.ndarray:
    """Correct page rotation using Hough line detection.

    Handwritten ledgers scanned with a phone are often tilted 1-5 degrees.
    This detects the dominant text angle and corrects it.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image.copy()

    # Detect edges
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Use probabilistic Hough transform to find line angles
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
    if lines is None or len(lines) == 0:
        return image

    # Calculate median angle of detected lines
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines (text lines)
        if abs(angle) < max_angle:
            angles.append(angle)

    if not angles:
        return image

    median_angle = float(np.median(angles))

    # Skip if rotation is negligible
    if abs(median_angle) < 0.3:
        return image

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        image,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def denoise(image: np.ndarray, strength: int = 6) -> np.ndarray:
    """Remove scan noise while preserving text edges.

    Uses non-local means denoising which is particularly good at
    preserving handwriting strokes while removing paper texture.
    """
    if len(image.shape) == 3:
        return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)
    return cv2.fastNlMeansDenoising(image, None, strength, 7, 21)


def assess_quality(image: np.ndarray) -> dict[str, Any]:
    """Quick quality assessment of the preprocessed image."""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    # Laplacian variance = sharpness metric
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    # Contrast: std deviation of pixel intensities
    contrast = float(np.std(gray))

    # Brightness: mean pixel intensity
    brightness = float(np.mean(gray))

    return {
        "sharpness": round(laplacian_var, 2),
        "contrast": round(contrast, 2),
        "brightness": round(brightness, 2),
        "resolution": f"{image.shape[1]}x{image.shape[0]}",
        "quality_rating": (
            "good" if laplacian_var > 100 and contrast > 40
            else "acceptable" if laplacian_var > 50 and contrast > 25
            else "poor"
        ),
    }


def preprocess_page(
    image: np.ndarray,
    *,
    do_deskew: bool = True,
    do_enhance: bool = True,
    do_binarize: bool = False,
    do_denoise: bool = True,
) -> np.ndarray:
    """Apply the full preprocessing pipeline to a single page image."""
    result = image.copy()

    if do_deskew:
        result = deskew(result)

    if do_denoise:
        result = denoise(result)

    if do_enhance:
        result = enhance_contrast(result)

    if do_binarize:
        result = adaptive_binarize(result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-process sales taka scans for OCR"
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dpi", type=int, default=TARGET_DPI)
    parser.add_argument(
        "--binarize",
        action="store_true",
        help="Apply adaptive binarization (best for very faded ink/pencil)",
    )
    parser.add_argument(
        "--no-deskew",
        action="store_true",
        help="Skip deskew correction",
    )
    parser.add_argument(
        "--no-enhance",
        action="store_true",
        help="Skip contrast enhancement",
    )
    parser.add_argument(
        "--no-denoise",
        action="store_true",
        help="Skip noise removal",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    def _repo_path(p: str) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    input_dir = _repo_path(args.input_dir)
    output_dir = _repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return

    print(f"Processing {len(pdf_files)} PDFs at {args.dpi} DPI")
    print(f"Pipeline: deskew={not args.no_deskew}, enhance={not args.no_enhance}, "
          f"denoise={not args.no_denoise}, binarize={args.binarize}")
    print()

    total_pages = 0
    quality_summary: list[dict[str, Any]] = []

    for pdf_path in pdf_files:
        stem = pdf_path.stem
        print(f"  {pdf_path.name}...")
        images = pdf_to_images(pdf_path, dpi=args.dpi)

        for page_idx, raw_image in enumerate(images, start=1):
            processed = preprocess_page(
                raw_image,
                do_deskew=not args.no_deskew,
                do_enhance=not args.no_enhance,
                do_binarize=args.binarize,
                do_denoise=not args.no_denoise,
            )

            # Save as PNG (lossless) for OCR
            out_name = f"{stem}_p{page_idx:02d}.png"
            out_path = output_dir / out_name

            # Convert RGB→BGR for OpenCV imwrite
            if len(processed.shape) == 3:
                cv2.imwrite(str(out_path), cv2.cvtColor(processed, cv2.COLOR_RGB2BGR))
            else:
                cv2.imwrite(str(out_path), processed)

            quality = assess_quality(processed)
            quality["file"] = out_name
            quality["source"] = pdf_path.name
            quality["page"] = page_idx
            quality_summary.append(quality)

            status = quality["quality_rating"]
            print(f"    page {page_idx}: {quality['resolution']} "
                  f"sharpness={quality['sharpness']} contrast={quality['contrast']} [{status}]")
            total_pages += 1

    print(f"\nDone: {total_pages} pages from {len(pdf_files)} PDFs → {output_dir}")

    # Summary
    good = sum(1 for q in quality_summary if q["quality_rating"] == "good")
    acceptable = sum(1 for q in quality_summary if q["quality_rating"] == "acceptable")
    poor = sum(1 for q in quality_summary if q["quality_rating"] == "poor")
    print(f"Quality: {good} good, {acceptable} acceptable, {poor} poor")

    if poor > 0:
        print("\nPoor quality pages (may need manual review or rescan):")
        for q in quality_summary:
            if q["quality_rating"] == "poor":
                print(f"  - {q['file']} (sharpness={q['sharpness']}, contrast={q['contrast']})")


if __name__ == "__main__":
    main()
