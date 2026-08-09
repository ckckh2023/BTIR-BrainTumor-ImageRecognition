'''生成病例四模态切片预览图：病灶最大层面，影像 + 分割掩码叠加'''

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

REGION_COLORS: dict[int, tuple[int, int, int]] = {
    1: (239, 68, 68),
    2: (34, 197, 94),
    4: (250, 204, 21),
}

MODALITY_ORDER: list[tuple[str, str]] = [
    ("FLAIR", "flair"),
    ("T1CE", "t1ce"),
    ("T1", "t1"),
    ("T2", "t2"),
]

TILE_SIZE = 300
LABEL_HEIGHT = 28
MASK_ALPHA = 0.45


def _load_volume(path: Path) -> np.ndarray | None:
    try:
        img = nib.load(str(path))
    except Exception as exc:
        logger.warning("preview volume load failed %s: %s", path, exc)
        return None
    data = np.asanyarray(img.get_fdata())
    if data.ndim == 4:
        data = data[..., 0]
    return data


def _to_gray(slice_data: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(slice_data, (1, 99.5))
    if hi <= lo:
        hi = lo + 1.0
    gray = np.clip((slice_data.astype(np.float32) - lo) / (hi - lo), 0, 1)
    return (gray * 255).astype(np.uint8)


def _render_tile(gray: np.ndarray, mask_slice: np.ndarray) -> Image.Image:
    rgb = np.stack([gray, gray, gray], axis=-1).astype(np.float32)
    # 直接混色：mask 区域整体向区域色偏移
    for label, color in REGION_COLORS.items():
        selected = mask_slice == label
        if selected.any():
            tint = np.array(color, dtype=np.float32)
            rgb[selected] = rgb[selected] * (1.0 - MASK_ALPHA) + tint * MASK_ALPHA
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "msyh.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_case_preview(
    modality_paths: dict[str, Any],
    mask_path: Path,
    output_path: Path,
) -> Path | None:
    '''生成四模态 2x2 拼图；无病灶或读取失败时返回 None'''
    mask_data = _load_volume(mask_path)
    if mask_data is None or mask_data.ndim != 3 or mask_data.size == 0:
        return None

    has_tumor = bool(np.any(mask_data > 0))
    z = (
        int(np.argmax(np.sum(mask_data > 0, axis=(0, 1))))
        if has_tumor
        else mask_data.shape[2] // 2
    )
    mask_slice = mask_data[:, :, z]

    tiles: list[tuple[str, Image.Image]] = []
    for label, key in MODALITY_ORDER:
        raw_path = modality_paths.get(key)
        if raw_path is None:
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        data = _load_volume(path)
        if data is None or data.ndim != 3 or data.shape != mask_data.shape:
            continue
        tiles.append((label, _render_tile(_to_gray(data[:, :, z]), mask_slice)))

    if not tiles:
        return None

    columns = 2
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (TILE_SIZE * columns, (LABEL_HEIGHT + TILE_SIZE) * rows),
        (248, 250, 252),
    )
    draw = ImageDraw.Draw(canvas)
    font = _load_font(16)
    for index, (label, tile) in enumerate(tiles):
        col = index % columns
        row = index // columns
        x = col * TILE_SIZE
        y = row * (LABEL_HEIGHT + TILE_SIZE)
        draw.text((x + 8, y + 5), label, fill=(30, 41, 59), font=font)
        canvas.paste(tile, (x, y + LABEL_HEIGHT))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    return output_path
