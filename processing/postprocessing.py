'''后处理，用于分割掩码'''

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def analyze_mask(mask: np.ndarray) -> dict[str, Any]:
    '''分析分割掩码，计算肿瘤像素数量、图像像素数量以及肿瘤面积占比'''
    mask_array = np.asarray(mask)
    if mask_array.ndim != 2:
        raise ValueError(f"Expected a 2D segmentation mask, got shape {mask_array.shape}")

    binary_mask = mask_array > 0
    tumor_pixels = int(np.count_nonzero(binary_mask))
    image_pixels = int(binary_mask.size)
    return {
        "tumor_pixels": tumor_pixels,
        "image_pixels": image_pixels,
        "tumor_area_ratio": tumor_pixels / image_pixels if image_pixels else 0.0,
    }


def save_mask(mask: np.ndarray, original_image_path: str | Path, output_dir: str | Path) -> str:
    '''将mask保存为png文件，并且返回保存路径'''
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(original_image_path).stem}_segmented.png"
    binary_mask = (np.asarray(mask) > 0).astype(np.uint8) * 255
    Image.fromarray(binary_mask).save(output_path)
    return str(output_path.resolve())
