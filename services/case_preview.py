'''生成病例多模态切片预览图'''

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
PREVIEW_OFFSETS = (-1, 0, 1)


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


def _render_tile(
    gray: np.ndarray,
    mask_slice: np.ndarray,
    *,
    show_mask: bool,
) -> Image.Image:
    rgb = np.stack([gray, gray, gray], axis=-1).astype(np.float32)
    if show_mask:
        for label, color in REGION_COLORS.items():
            selected = mask_slice == label
            if selected.any():
                tint = np.array(color, dtype=np.float32)
                rgb[selected] = rgb[selected] * (1.0 - MASK_ALPHA) + tint * MASK_ALPHA
    image = Image.fromarray(rgb.astype(np.uint8), "RGB")
    return image.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.BICUBIC)


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "msyh.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_preview_data(
    modality_paths: dict[str, Any],
    mask_path: Path,
) -> tuple[np.ndarray, list[tuple[str, np.ndarray]]] | None:
    mask_data = _load_volume(mask_path)
    if mask_data is None or mask_data.ndim != 3 or mask_data.size == 0:
        return None

    modalities: list[tuple[str, np.ndarray]] = []
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
        modalities.append((label, data))
    return (mask_data, modalities) if modalities else None


def _focus_slice(mask_data: np.ndarray) -> int:
    if np.any(mask_data > 0):
        return int(np.argmax(np.sum(mask_data > 0, axis=(0, 1))))
    return mask_data.shape[2] // 2


def _render_montage(
    modalities: list[tuple[str, np.ndarray]],
    mask_data: np.ndarray,
    slice_index: int,
    *,
    show_mask: bool,
) -> Image.Image:
    tiles = [
        (label, _render_tile(_to_gray(data[:, :, slice_index]), mask_data[:, :, slice_index], show_mask=show_mask))
        for label, data in modalities
    ]
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
    return canvas


def _save_montage(
    output_path: Path,
    modalities: list[tuple[str, np.ndarray]],
    mask_data: np.ndarray,
    slice_index: int,
    *,
    show_mask: bool,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _render_montage(modalities, mask_data, slice_index, show_mask=show_mask).save(
        output_path,
        format="PNG",
    )
    return output_path


def render_case_preview(
    modality_paths: dict[str, Any],
    mask_path: Path,
    output_path: Path,
) -> Path | None:
    '''生成最大病灶层四模态掩码叠加图'''
    prepared = _load_preview_data(modality_paths, mask_path)
    if prepared is None:
        return None
    mask_data, modalities = prepared
    return _save_montage(
        output_path,
        modalities,
        mask_data,
        _focus_slice(mask_data),
        show_mask=True,
    )


def render_case_preview_series(
    modality_paths: dict[str, Any],
    mask_path: Path,
    output_dir: Path,
) -> dict[str, Any] | None:
    '''生成最大病灶层及相邻层的原图与掩码叠加图'''
    prepared = _load_preview_data(modality_paths, mask_path)
    if prepared is None:
        return None
    mask_data, modalities = prepared
    focus = _focus_slice(mask_data)
    frames: list[dict[str, int | str]] = []
    for offset in PREVIEW_OFFSETS:
        slice_index = focus + offset
        if slice_index < 0 or slice_index >= mask_data.shape[2]:
            continue
        raw_name = f"slice-{slice_index:03d}-raw.png"
        overlay_name = f"slice-{slice_index:03d}-overlay.png"
        _save_montage(
            output_dir / raw_name,
            modalities,
            mask_data,
            slice_index,
            show_mask=False,
        )
        _save_montage(
            output_dir / overlay_name,
            modalities,
            mask_data,
            slice_index,
            show_mask=True,
        )
        frames.append(
            {
                "slice_index": slice_index,
                "offset": offset,
                "raw": f"{output_dir.name}/{raw_name}",
                "overlay": f"{output_dir.name}/{overlay_name}",
            }
        )
    return {"focus_slice": focus, "frames": frames}
