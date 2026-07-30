'''提供推理服务的接口，包括分类和分割模型的推理功能'''

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from accelerator import resolve_device
from core.settings import SETTINGS
from processing.postprocessing import analyze_mask, save_mask
from functools import lru_cache


@lru_cache(maxsize=1)
def _load_classifier_namespace() -> dict[str, Any]:
    '''用来缓存分类模型的命名空间，避免重复导入'''
    return runpy.run_path(
        str(SETTINGS.classifier_script),
        run_name="codearts_classifier",
    )


@lru_cache(maxsize=2) # 最多保留两个不同设备的模型缓存
def _load_classifier_model(device_name: str):
    '''用来缓存分类模型，避免重复加载'''
    namespace = _load_classifier_namespace()
    return namespace["load_model"](
        SETTINGS.classifier_model,
        SETTINGS.classifier_config,
        device=device_name,
    )


@lru_cache(maxsize=1)
def _load_segmentation_namespace() -> dict[str, Any]:
    '''用来缓存分割模型的命名空间，避免重复导入'''
    original_sys_path = sys.path[:]
    try:
        sys.path.insert(0, str(SETTINGS.segmenter_script.parent))
        return runpy.run_path(
            str(SETTINGS.segmenter_script),
            run_name="codearts_segmenter",
        )
    finally:
        sys.path[:] = original_sys_path


@lru_cache(maxsize=2)
def _load_segmentation_model(device_name: str):
    '''用来缓存分割模型，避免重复加载'''
    namespace = _load_segmentation_namespace()
    return namespace["load_model"](
        SETTINGS.segmenter_model,
        device=device_name,
    )


@lru_cache(maxsize=1)
def _load_3d_segmentation_namespace() -> dict[str, Any]:
    '''缓存四模态 3D 分割脚本命名空间'''

    original_sys_path = sys.path[:]
    try:
        sys.path.insert(0, str(SETTINGS.segmenter_3d_script.parent))
        return runpy.run_path(
            str(SETTINGS.segmenter_3d_script),
            run_name="btir_segmenter_3d",
        )
    finally:
        sys.path[:] = original_sys_path


@lru_cache(maxsize=2)
def _load_3d_segmentation_model(device_name: str):
    '''缓存 SuperLightNet 权重，避免每项任务重新加载'''

    namespace = _load_3d_segmentation_namespace()
    return namespace["load_model"](
        device=device_name,
        weights_path=SETTINGS.segmenter_3d_model,
    )


def classify(image_path: Path) -> dict[str, Any]:
    '''跑分类模型，返回预测结果'''
    namespace = _load_classifier_namespace()
    torch = namespace["torch"]
    device = resolve_device(torch, SETTINGS.device)
    model, config = _load_classifier_model(str(device))
    prediction = namespace["predict"](model, str(image_path), config)
    return {
        "model": "models/classification/resnet50",
        "image_path": str(image_path),
        "classification": prediction,
    }


def segment(image_path: Path, threshold: float, output_dir: Path) -> dict[str, Any]:
    '''跑分割模型，返回预测结果'''
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("--threshold 必须位于 0 到 1 之间")

    namespace = _load_segmentation_namespace()
    torch = namespace["torch"]
    device = resolve_device(torch, SETTINGS.device)
    model = _load_segmentation_model(str(device))

    mask = namespace["predict"](model, str(image_path), threshold)
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_path = Path(save_mask(mask, image_path, output_dir))
    metrics = analyze_mask(mask)
    return {
        "model": "models/segmentation/resnet34-unet",
        "image_path": str(image_path),
        "threshold": threshold,
        "mask_path": str(mask_path),
        **metrics,
    }


def segment_volume(
    modality_paths: dict[str, Path],
    output_dir: Path,
) -> dict[str, Any]:
    '''执行四模态完整体积 SuperLightNet 分割'''

    namespace = _load_3d_segmentation_namespace()
    torch = namespace["torch"]
    device = resolve_device(torch, SETTINGS.device)
    model = _load_3d_segmentation_model(str(device))

    output_dir.mkdir(parents=True, exist_ok=True)
    mask_path = output_dir / "prediction.nii.gz"
    prediction = namespace["predict"](
        {
            modality: str(path)
            for modality, path in modality_paths.items()
        },
        device=str(device),
        model=model,
        save_nifti=mask_path,
        weights_path=SETTINGS.segmenter_3d_model,
        overlap=SETTINGS.segmenter_3d_overlap,
    )
    return {
        "model": "models/segmentation3d/superlightnet",
        "analysis_mode": "3d",
        "device": prediction["device"],
        "model_metadata": prediction["model"],
        "spatial": prediction["spatial"],
        "labels": prediction["labels"],
        "regions": prediction["regions"],
        "mask_path": prediction["saved_path"],
    }


def preload_inference_models() -> dict[str, float | str]:
    '''预加载模型到当前进程缓存；单个模型失败不会阻止另一个模型预热'''
    outcomes: dict[str, float | str] = {}
    for name, namespace_loader, model_loader in (
        ("classification", _load_classifier_namespace, _load_classifier_model),
        ("segmentation", _load_segmentation_namespace, _load_segmentation_model),
        (
            "segmentation3d",
            _load_3d_segmentation_namespace,
            _load_3d_segmentation_model,
        ),
    ):
        started_at = perf_counter()
        try:
            namespace = namespace_loader()
            device = resolve_device(namespace["torch"], SETTINGS.device)
            model_loader(str(device))
        except Exception as exc:
            outcomes[name] = f"failed: {type(exc).__name__}: {exc}"
        else:
            outcomes[name] = round((perf_counter() - started_at) * 1000, 3)
    return outcomes
