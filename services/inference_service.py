'''提供推理服务的接口，包括分类和分割模型的推理功能'''

from __future__ import annotations

from functools import lru_cache
import runpy
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from accelerator import resolve_device
from core.settings import SETTINGS
from processing.volume_classification import (
    aggregate_mean_slice_predictions,
    prepare_volume_slices,
)


@lru_cache(maxsize=1)
def _load_vit_classifier_namespace() -> dict[str, Any]:
    '''缓存本地二分类 ViT 推理模块'''

    from models.classification import vit_binary

    return {
        "torch": vit_binary.torch,
        "load_model": vit_binary.load_model,
        "predict_images": vit_binary.predict_images,
    }


@lru_cache(maxsize=2)
def _load_vit_classifier_model(device_name: str):
    '''按设备缓存本地 ViT 权重；加载过程禁止联网'''

    namespace = _load_vit_classifier_namespace()
    return namespace["load_model"](
        SETTINGS.vit_classifier_model_dir,
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


def classify_volume(modality_paths: dict[str, Path]) -> dict[str, Any]:
    '''仅使用本地 ViT 执行患者级分类；异常交由任务重试机制处理'''

    return _classify_volume_vit(modality_paths)


def _classify_volume_vit(modality_paths: dict[str, Path]) -> dict[str, Any]:
    '''使用本地二分类 ViT 对轴向切片执行患者级均值聚合'''

    modality = SETTINGS.volume_classifier_modality
    try:
        volume_path = modality_paths[modality]
    except KeyError as exc:
        raise ValueError(f"3D 分类缺少 {modality} 模态") from exc

    prepared = prepare_volume_slices(
        volume_path,
        max_slices=SETTINGS.vit_classifier_max_slices,
    )
    namespace = _load_vit_classifier_namespace()
    torch = namespace["torch"]
    device = resolve_device(torch, SETTINGS.device)
    loaded = _load_vit_classifier_model(str(device))
    predictions = namespace["predict_images"](
        loaded,
        prepared.images,
        batch_size=SETTINGS.vit_classifier_batch_size,
    )
    classification = aggregate_mean_slice_predictions(
        prepared.indices,
        predictions,
        modality=modality,
        threshold=SETTINGS.vit_classifier_threshold,
    )
    classification.update(
        {
            "device": str(device),
            "checkpoint": loaded.checkpoint_name,
            "canonical_shape": list(prepared.canonical_shape),
            "foreground_slices": prepared.foreground_slice_count,
            "intensity_window": list(prepared.intensity_window),
        }
    )
    return {
        "model": "models/classification/vit-binary",
        "analysis_mode": "3d",
        "classification": classification,
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
    '''按 Worker 路线预加载模型；单个模型失败不会阻止其他模型预热'''

    loaders = (
        ("classification", _load_vit_classifier_namespace, _load_vit_classifier_model),
        ("segmentation", _load_3d_segmentation_namespace, _load_3d_segmentation_model),
    )

    outcomes: dict[str, float | str] = {}
    for name, namespace_loader, model_loader in loaders:
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
