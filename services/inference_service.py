'''提供推理服务的接口，包括分类和分割模型的推理功能'''

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any

from processing.postprocessing import analyze_mask, save_mask


# 常用路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"
CLASSIFIER_DIR = MODELS_DIR / "classification"
CLASSIFIER_SCRIPT = CLASSIFIER_DIR / "inference.py"
CLASSIFIER_MODEL = CLASSIFIER_DIR / "model" / "pytorch_model.pth"
CLASSIFIER_CONFIG = CLASSIFIER_DIR / "model" / "config.json"
SEGMENTER_DIR = MODELS_DIR / "segmentation"
SEGMENTER_SCRIPT = SEGMENTER_DIR / "inference.py"
SEGMENTER_MODEL = SEGMENTER_DIR / "model" / "best_unet_model.pth"


def classify(image_path: Path) -> dict[str, Any]:
    '''跑分类模型，返回预测结果'''
    namespace = runpy.run_path(str(CLASSIFIER_SCRIPT), run_name="codearts_classifier")
    model, config = namespace["load_model"](str(CLASSIFIER_MODEL), str(CLASSIFIER_CONFIG))
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
    model = namespace["ResNet34UNet"](out_classes=1)
    state_dict = torch.load(SEGMENTER_MODEL, map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()

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


def _load_segmentation_namespace() -> dict[str, Any]:
    '''加载分割模型的命名空间，避免重复导入'''
    original_sys_path = sys.path[:]
    try:
        sys.path.insert(0, str(SEGMENTER_DIR))
        return runpy.run_path(str(SEGMENTER_SCRIPT), run_name="codearts_segmenter")
    finally:
        sys.path[:] = original_sys_path
