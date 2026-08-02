"""Deterministic SuperLightNet inference for a four-modality BraTS subject.

This module intentionally contains no API or task-system code.  It is the
standalone inference boundary that can be integrated after its input/output
contract has been verified.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import uuid
from collections.abc import Callable
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import torch
from monai.inferers import sliding_window_inference


SEG_DIR = Path(__file__).resolve().parent
MODEL_DIR = SEG_DIR / "model"
NET_DIR = MODEL_DIR / "SuperLightNet-main"

if str(NET_DIR) not in sys.path:
    sys.path.insert(0, str(NET_DIR))

from Jnetworks.superlightnet import NormalU_Net  # noqa: E402


MODEL_WEIGHTS = MODEL_DIR / "model_epoch_297.pth"
MODEL_NAME = "SuperLightNet"
MODEL_VARIANT = "small"
MODALITIES = ("flair", "t1ce", "t1", "t2")
MODALITY_ALIASES = {
    "flair": ("flair",),
    "t1ce": ("t1ce", "t1c", "t1gd"),
    "t1": ("t1",),
    "t2": ("t2",),
}
ROI_SIZE = (128, 128, 128)
CUDA_ACCUMULATOR_RESERVE_BYTES = 2 * 1024**3
INTERNAL_TO_BRATS = np.asarray((0, 1, 2, 4), dtype=np.uint8)
BRATS_CLASS_NAMES = {
    0: "background",
    1: "NCR/NET",
    2: "ED",
    4: "ET",
}


class InputValidationError(ValueError):
    """Raised when the four input modalities do not form one spatial volume."""


def _configure_determinism(seed: int) -> None:
    """Configure deterministic inference before any CUDA work is submitted."""

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if hasattr(torch.backends.cuda.matmul, "allow_tf32"):
        torch.backends.cuda.matmul.allow_tf32 = False
    if hasattr(torch.backends.cudnn, "allow_tf32"):
        torch.backends.cudnn.allow_tf32 = False


def _resolve_device(device: str | torch.device) -> torch.device:
    requested = str(device).strip().lower()
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"

    resolved = torch.device(requested)
    if resolved.type not in {"cpu", "cuda"}:
        raise ValueError(f"仅支持 cpu、cuda 或 auto，收到: {device!r}")
    if resolved.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("请求了 CUDA 推理，但当前 PyTorch 环境无法使用 CUDA")
    return resolved


def _unwrap_state_dict(checkpoint: Any) -> Mapping[str, torch.Tensor]:
    if not isinstance(checkpoint, Mapping):
        raise RuntimeError("模型权重不是有效的 state_dict")

    for key in ("state_dict", "model_state_dict"):
        nested = checkpoint.get(key)
        if isinstance(nested, Mapping):
            checkpoint = nested
            break

    if not checkpoint or not all(isinstance(key, str) for key in checkpoint):
        raise RuntimeError("模型权重中没有找到有效参数")
    return checkpoint


def load_model(
    device: str | torch.device,
    weights_path: str | Path = MODEL_WEIGHTS,
) -> torch.nn.Module:
    resolved_device = _resolve_device(device)
    weights_path = Path(weights_path)
    if not weights_path.is_file():
        raise FileNotFoundError(f"未找到模型权重: {weights_path}")

    model = NormalU_Net(depths_unidirectional=MODEL_VARIANT)
    checkpoint = torch.load(
        weights_path,
        map_location="cpu",
        weights_only=True,
    )
    state_dict = _unwrap_state_dict(checkpoint)
    cleaned = {
        key.removeprefix("module."): value
        for key, value in state_dict.items()
    }
    model.load_state_dict(cleaned, strict=True)

    direction_index = 0
    for module in model.modules():
        if hasattr(module, "inference_direction"):
            module.inference_direction = direction_index % 3
            direction_index += 1
    if direction_index == 0:
        raise RuntimeError("模型中没有找到需要固定方向的 THPA 推理模块")

    model.to(resolved_device)
    model.eval()
    return model


def _strip_nifti_suffix(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".nii.gz"):
        return lowered[:-7]
    if lowered.endswith(".nii"):
        return lowered[:-4]
    return lowered


def _matches_modality(path: Path, modality: str) -> bool:
    stem = _strip_nifti_suffix(path.name)
    return any(
        re.search(rf"(?:^|[_-]){re.escape(alias)}$", stem) is not None
        for alias in MODALITY_ALIASES[modality]
    )


def _discover_modality_files(subject_dir: Path) -> dict[str, Path]:
    if not subject_dir.is_dir():
        raise InputValidationError(f"受试者目录不存在: {subject_dir}")

    candidates = sorted(
        path
        for path in subject_dir.iterdir()
        if path.is_file()
        and path.name.lower().endswith((".nii", ".nii.gz"))
    )
    resolved: dict[str, Path] = {}
    for modality in MODALITIES:
        matches = [path for path in candidates if _matches_modality(path, modality)]
        if not matches:
            raise InputValidationError(
                f"缺少 {modality} 模态 NIfTI 文件: {subject_dir}"
            )
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise InputValidationError(
                f"{modality} 模态匹配到多个文件，无法确定输入: {names}"
            )
        resolved[modality] = matches[0]
    return resolved


def _resolve_modality_files(
    subject: str | Path | Mapping[str, str | Path],
) -> dict[str, Path]:
    if isinstance(subject, Mapping):
        missing = [modality for modality in MODALITIES if modality not in subject]
        if missing:
            raise InputValidationError(
                f"缺少必需模态: {', '.join(missing)}"
            )
        resolved = {
            modality: Path(subject[modality]).expanduser().resolve()
            for modality in MODALITIES
        }
        nonexistent = [
            f"{modality}={path}"
            for modality, path in resolved.items()
            if not path.is_file()
        ]
        if nonexistent:
            raise InputValidationError(
                "以下模态文件不存在: " + ", ".join(nonexistent)
            )
        return resolved

    return _discover_modality_files(Path(subject).expanduser().resolve())


def _orientation(affine: np.ndarray) -> tuple[str, str, str]:
    orientation = nib.aff2axcodes(affine)
    if any(axis is None for axis in orientation):
        raise InputValidationError("NIfTI affine 无法确定空间方向")
    return tuple(str(axis) for axis in orientation)


def _validate_single_image(
    modality: str,
    image: nib.spatialimages.SpatialImage,
    path: Path,
) -> None:
    if len(image.shape) != 3:
        raise InputValidationError(
            f"{modality} 必须是三维 NIfTI，当前 shape={image.shape}: {path}"
        )
    if any(int(size) <= 0 for size in image.shape):
        raise InputValidationError(
            f"{modality} 包含无效空间尺寸 {image.shape}: {path}"
        )
    affine = np.asarray(image.affine, dtype=np.float64)
    if affine.shape != (4, 4) or not np.isfinite(affine).all():
        raise InputValidationError(f"{modality} affine 无效: {path}")
    if abs(float(np.linalg.det(affine[:3, :3]))) < 1e-8:
        raise InputValidationError(f"{modality} affine 不可逆: {path}")
    _orientation(affine)


def _load_and_validate_subject(
    subject: str | Path | Mapping[str, str | Path],
) -> tuple[np.ndarray, nib.spatialimages.SpatialImage, dict[str, Path]]:
    paths = _resolve_modality_files(subject)
    images: dict[str, nib.spatialimages.SpatialImage] = {}

    for modality in MODALITIES:
        path = paths[modality]
        try:
            image = nib.load(str(path))
        except Exception as exc:
            raise InputValidationError(
                f"无法读取 {modality} NIfTI 文件: {path}"
            ) from exc
        _validate_single_image(modality, image, path)
        images[modality] = image

    reference = images["flair"]
    reference_shape = tuple(int(size) for size in reference.shape)
    reference_affine = np.asarray(reference.affine, dtype=np.float64)
    reference_zooms = np.asarray(reference.header.get_zooms()[:3], dtype=np.float64)
    reference_orientation = _orientation(reference_affine)

    for modality in MODALITIES[1:]:
        image = images[modality]
        if tuple(image.shape) != reference_shape:
            raise InputValidationError(
                f"四模态 shape 不一致: flair={reference_shape}, "
                f"{modality}={image.shape}"
            )
        if not np.allclose(
            image.affine,
            reference_affine,
            rtol=1e-5,
            atol=1e-4,
        ):
            raise InputValidationError(
                f"{modality} 与 flair 的 affine 不一致，禁止直接堆叠推理"
            )
        zooms = np.asarray(image.header.get_zooms()[:3], dtype=np.float64)
        if not np.allclose(zooms, reference_zooms, rtol=1e-5, atol=1e-5):
            raise InputValidationError(
                f"{modality} 与 flair 的 voxel spacing 不一致"
            )
        if _orientation(image.affine) != reference_orientation:
            raise InputValidationError(
                f"{modality} 与 flair 的空间方向不一致"
            )

    def load_array(modality: str) -> np.ndarray:
        try:
            data = np.asarray(images[modality].dataobj, dtype=np.float32)
        except Exception as exc:
            raise InputValidationError(
                f"读取 {modality} 体素数据失败: {paths[modality]}"
            ) from exc
        if not np.isfinite(data).all():
            raise InputValidationError(
                f"{modality} 体素中包含 NaN 或无穷值"
            )
        return data

    with ThreadPoolExecutor(max_workers=len(MODALITIES)) as executor:
        arrays = list(executor.map(load_array, MODALITIES))

    stacked = np.stack(arrays, axis=-1)
    return stacked, reference, paths


def _zscore_normalize(images: np.ndarray) -> np.ndarray:
    foreground = np.any(images != 0, axis=-1)
    if not np.any(foreground):
        raise InputValidationError("四模态均为空，无法推理")

    normalized = np.zeros(images.shape, dtype=np.float32)
    for index, modality in enumerate(MODALITIES):
        channel = images[..., index]
        values = channel[foreground]
        standard_deviation = float(values.std(dtype=np.float64))
        if not np.isfinite(standard_deviation) or standard_deviation <= 1e-8:
            raise InputValidationError(
                f"{modality} 前景体素没有有效强度变化，无法执行 z-score"
            )
        mean = float(values.mean(dtype=np.float64))
        normalized_channel = normalized[..., index]
        normalized_channel[foreground] = (values - mean) / standard_deviation
    return normalized


def _to_tensor(images: np.ndarray) -> torch.Tensor:
    array = np.ascontiguousarray(images.transpose(3, 0, 1, 2))
    return torch.from_numpy(array).float().unsqueeze(0)


def _validate_roi_size(roi_size: tuple[int, int, int]) -> None:
    if len(roi_size) != 3 or any(size <= 0 for size in roi_size):
        raise ValueError(f"roi_size 必须包含三个正整数，收到: {roi_size}")
    if any(size % 16 != 0 for size in roi_size):
        raise ValueError(
            f"SuperLightNet 的 roi_size 每一维必须是 16 的倍数，收到: {roi_size}"
        )


def _select_accumulator_device(
    image_shape: tuple[int, int, int],
    inference_device: torch.device,
) -> torch.device:
    """在显存充足时让 MONAI 直接在 GPU 汇总窗口，避免频繁传回 CPU。"""

    cpu = torch.device("cpu")
    if inference_device.type != "cuda":
        return cpu

    # GPU 路径需要四通道输入、四通道输出与一张权重图，另留 2 GiB
    # 给当前窗口、模型激活和运行时碎片。显存不足时继续使用原 CPU 路径。
    staging_bytes = int(np.prod(image_shape, dtype=np.int64)) * 9 * 4
    try:
        free_bytes, _ = torch.cuda.mem_get_info(inference_device)
    except (RuntimeError, TypeError):
        return cpu
    if free_bytes < CUDA_ACCUMULATOR_RESERVE_BYTES + staging_bytes:
        return cpu
    return inference_device


def _stage_input_tensor(
    images: np.ndarray,
    inference_device: torch.device,
    accumulator_device: torch.device,
) -> tuple[torch.Tensor, torch.device]:
    '''显存充足时一次上传完整输入；失败则连同结果汇总一起回退 CPU。'''

    tensor = _to_tensor(images)
    if accumulator_device.type != "cuda":
        return tensor, accumulator_device
    try:
        return tensor.to(inference_device), accumulator_device
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        return tensor, torch.device("cpu")


def _run_full_volume_inference(
    images: np.ndarray,
    model: torch.nn.Module,
    device: torch.device,
    *,
    roi_size: tuple[int, int, int],
    overlap: float,
    progress: bool,
    progress_callback: Callable[[float], None] | None = None,
) -> np.ndarray:
    _validate_roi_size(roi_size)
    if not 0 <= overlap < 1:
        raise ValueError(f"overlap 必须位于 [0, 1)，收到: {overlap}")

    accumulator_device = _select_accumulator_device(images.shape[:3], device)
    tensor, accumulator_device = _stage_input_tensor(
        images,
        device,
        accumulator_device,
    )

    predictor = model
    if progress_callback is not None:
        total_windows = _count_sliding_windows(images.shape[:3], roi_size, overlap)
        if total_windows > 0:
            window_counter = {"done": 0}

            def progress_predictor(
                patch_data: torch.Tensor,
                *args: Any,
                **kwargs: Any,
            ) -> torch.Tensor:
                window_counter["done"] += 1
                progress_callback(
                    min(window_counter["done"], total_windows) / total_windows
                )
                return model(patch_data, *args, **kwargs)

            predictor = progress_predictor

    def infer(output_device: torch.device) -> torch.Tensor:
        return sliding_window_inference(
            inputs=tensor,
            roi_size=roi_size,
            sw_batch_size=1,
            predictor=predictor,
            overlap=overlap,
            mode="gaussian",
            sw_device=device,
            device=output_device,
            progress=progress,
        )

    with torch.inference_mode():
        try:
            logits = infer(accumulator_device)
        except torch.cuda.OutOfMemoryError:
            if accumulator_device.type != "cuda":
                raise
            torch.cuda.empty_cache()
            logits = infer(torch.device("cpu"))

    expected_shape = (1, 4, *images.shape[:3])
    if tuple(logits.shape) != expected_shape:
        raise RuntimeError(
            f"模型输出 shape 异常，期望 {expected_shape}，收到 {tuple(logits.shape)}"
        )
    internal_labels = logits.argmax(dim=1).squeeze(0).to("cpu").numpy()
    if internal_labels.min(initial=0) < 0 or internal_labels.max(initial=0) > 3:
        raise RuntimeError("模型返回了 0-3 范围外的内部类别")
    return internal_labels.astype(np.uint8, copy=False)


def _count_sliding_windows(
    image_size: tuple[int, int, int],
    roi_size: tuple[int, int, int],
    overlap: float,
) -> int:
    '''按 MONAI 相同的规则统计滑窗数量，用于逐窗口推理进度计算'''
    from monai.inferers.utils import (
        _get_scan_interval,
        dense_patch_slices,
        fall_back_tuple,
    )
    from monai.utils import ensure_tuple_rep

    roi = fall_back_tuple(roi_size, image_size)
    padded_size = tuple(
        max(image_size[i], roi[i])
        for i in range(len(image_size))
    )
    scan_interval = _get_scan_interval(
        padded_size,
        roi,
        len(image_size),
        ensure_tuple_rep(overlap, len(image_size)),
    )
    slices = dense_patch_slices(
        padded_size,
        roi,
        scan_interval,
        return_slice=True,
    )
    return len(slices)


def _to_brats_labels(internal_labels: np.ndarray) -> np.ndarray:
    """Map internal contiguous classes 0/1/2/3 to BraTS labels 0/1/2/4."""

    return INTERNAL_TO_BRATS[internal_labels]


def _region_statistics(
    segmentation: np.ndarray,
    reference: nib.spatialimages.SpatialImage,
) -> dict[str, dict[str, float | int | str]]:
    voxel_volume_mm3 = abs(float(np.linalg.det(reference.affine[:3, :3])))
    total_voxels = int(segmentation.size)
    regions: dict[str, dict[str, float | int | str]] = {}

    for label, name in BRATS_CLASS_NAMES.items():
        count = int(np.count_nonzero(segmentation == label))
        regions[str(label)] = {
            "name": name,
            "voxels": count,
            "volume_mm3": round(count * voxel_volume_mm3, 3),
            "ratio": round(count / total_voxels, 8),
        }
    return regions


def _save_segmentation(
    segmentation: np.ndarray,
    reference: nib.spatialimages.SpatialImage,
    output_path: str | Path,
) -> Path:
    output_path = Path(output_path).expanduser().resolve()
    if not output_path.name.lower().endswith((".nii", ".nii.gz")):
        raise ValueError("分割结果必须保存为 .nii 或 .nii.gz")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = reference.header.copy()
    header.set_data_dtype(np.uint8)
    output_image = nib.Nifti1Image(
        segmentation.astype(np.uint8, copy=False),
        np.asarray(reference.affine),
        header=header,
    )
    qform, qform_code = reference.get_qform(coded=True)
    sform, sform_code = reference.get_sform(coded=True)
    if qform is not None:
        output_image.set_qform(qform, int(qform_code))
    if sform is not None:
        output_image.set_sform(sform, int(sform_code))

    nifti_suffix = ".nii.gz" if output_path.name.lower().endswith(".nii.gz") else ".nii"
    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.tmp{nifti_suffix}"
    )
    try:
        nib.save(output_image, str(temporary_path))
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def predict(
    subject: str | Path | Mapping[str, str | Path],
    *,
    device: str | torch.device = "auto",
    model: torch.nn.Module | None = None,
    return_volume: bool = False,
    save_nifti: str | Path | None = None,
    weights_path: str | Path = MODEL_WEIGHTS,
    roi_size: tuple[int, int, int] = ROI_SIZE,
    overlap: float = 0.5,
    seed: int = 0,
    progress: bool = False,
    progress_callback: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run deterministic full-volume segmentation for one BraTS subject.

    ``subject`` can be a directory containing exactly discoverable modality
    files, or an explicit mapping with the keys flair/t1ce/t1/t2.
    """

    total_started_at = time.perf_counter()
    resolved_device = _resolve_device(device)
    _configure_determinism(seed)

    started_at = time.perf_counter()
    images, reference, paths = _load_and_validate_subject(subject)
    load_validate_ms = (time.perf_counter() - started_at) * 1000

    started_at = time.perf_counter()
    normalized = _zscore_normalize(images)
    normalize_ms = (time.perf_counter() - started_at) * 1000

    started_at = time.perf_counter()
    model = model or load_model(resolved_device, weights_path)
    model_setup_ms = (time.perf_counter() - started_at) * 1000

    started_at = time.perf_counter()
    internal_labels = _run_full_volume_inference(
        normalized,
        model,
        resolved_device,
        roi_size=roi_size,
        overlap=overlap,
        progress=progress,
        progress_callback=progress_callback,
    )
    model_inference_ms = (time.perf_counter() - started_at) * 1000

    started_at = time.perf_counter()
    segmentation = _to_brats_labels(internal_labels)
    regions = _region_statistics(segmentation, reference)
    postprocess_ms = (time.perf_counter() - started_at) * 1000

    result: dict[str, Any] = {
        "model": {
            "name": MODEL_NAME,
            "variant": MODEL_VARIANT,
            "weights": Path(weights_path).name,
        },
        "device": str(resolved_device),
        "modalities": {
            modality: str(paths[modality])
            for modality in MODALITIES
        },
        "spatial": {
            "shape": [int(size) for size in reference.shape],
            "voxel_spacing_mm": [
                float(value)
                for value in reference.header.get_zooms()[:3]
            ],
            "orientation": list(_orientation(reference.affine)),
            "affine": np.asarray(reference.affine).tolist(),
        },
        "labels": {
            "scheme": "BraTS",
            "values": {
                str(label): name
                for label, name in BRATS_CLASS_NAMES.items()
            },
        },
        "regions": regions,
    }

    save_ms = 0.0
    if save_nifti is not None:
        started_at = time.perf_counter()
        result["saved_path"] = str(
            _save_segmentation(segmentation, reference, save_nifti)
        )
        save_ms = (time.perf_counter() - started_at) * 1000
    if return_volume:
        result["segmentation"] = segmentation
    result["timing"] = {
        "load_validate_ms": round(load_validate_ms, 3),
        "normalize_ms": round(normalize_ms, 3),
        "model_setup_ms": round(model_setup_ms, 3),
        "model_inference_ms": round(model_inference_ms, 3),
        "postprocess_ms": round(postprocess_ms, 3),
        "save_ms": round(save_ms, 3),
        "total_ms": round((time.perf_counter() - total_started_at) * 1000, 3),
    }
    return result


def _print_human_summary(output: dict[str, Any], elapsed_seconds: float) -> None:
    model = output["model"]
    spatial = output["spatial"]
    regions = output["regions"]
    shape_text = " × ".join(str(size) for size in spatial["shape"])
    spacing_text = " × ".join(
        f"{value:g}" for value in spatial["voxel_spacing_mm"]
    )
    orientation_text = "".join(spatial["orientation"])
    tumor_voxels = sum(
        int(regions[str(label)]["voxels"])
        for label in (1, 2, 4)
    )

    print()
    print("=" * 62)
    print("  SuperLightNet 三维分割完成")
    print("=" * 62)
    print(f"  模型版本      {model['name']} / {model['variant']}")
    print(f"  计算设备      {output['device']}")
    print(f"  原始尺寸      {shape_text}")
    print(f"  体素间距      {spacing_text} mm")
    print(f"  空间方向      {orientation_text}")
    print(f"  推理耗时      {elapsed_seconds:.2f} 秒")
    print(f"  非背景体素    {tumor_voxels:,}")
    print()
    print("  分割区域（BraTS 标签）")
    for label in (1, 2, 4):
        region = regions[str(label)]
        print(
            f"    {label}  {region['name']:<8} "
            f"{int(region['voxels']):>10,} 体素  "
            f"{float(region['volume_mm3']):>12,.3f} mm^3"
        )
    if output.get("saved_path"):
        print()
        print(f"  结果文件      {output['saved_path']}")
    print()
    print("  说明：结果仅供分割与定量分析，不构成医学诊断。")
    print("=" * 62)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 SuperLightNet 对四模态 BraTS NIfTI 执行确定性分割"
    )
    parser.add_argument(
        "subject_dir",
        type=Path,
        help="包含 flair、t1ce、t1、t2 NIfTI 文件的受试者目录",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="auto、cpu、cuda 或 cuda:0，默认 auto",
    )
    parser.add_argument(
        "--save",
        type=Path,
        help="输出 .nii 或 .nii.gz 文件",
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=0.5,
        help="滑窗重叠率，默认 0.5",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="显示完整体积滑窗进度",
    )
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="控制台输出格式，默认 human",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    started_at = time.perf_counter()
    if args.format == "human":
        print("=" * 62)
        print("  SuperLightNet 三维脑肿瘤分割")
        print("=" * 62)
        print(f"  输入目录      {args.subject_dir.resolve()}")
        print(f"  请求设备      {args.device}")
        print("  正在校验四模态并执行完整体积推理，请稍候……", flush=True)
    try:
        output = predict(
            args.subject_dir,
            device=args.device,
            save_nifti=args.save,
            overlap=args.overlap,
            progress=args.progress,
        )
    except (InputValidationError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"推理失败: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        _print_human_summary(
            output,
            elapsed_seconds=time.perf_counter() - started_at,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
