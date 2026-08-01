"""Offline inference adapter for the local binary brain-tumor ViT."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import torch
from PIL.Image import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification


REQUIRED_FILES = (
    "config.json",
    "model.safetensors",
    "preprocessor_config.json",
)


@dataclass(frozen=True)
class LoadedBinarySliceClassifier:
    """Local model, processor, label mapping, and runtime metadata."""

    model: torch.nn.Module
    processor: Any
    no_index: int
    yes_index: int
    device: torch.device
    checkpoint_name: str


def load_model(
    model_dir: str | Path,
    *,
    device: str | torch.device,
) -> LoadedBinarySliceClassifier:
    """Load the complete model directory without any network fallback."""

    path = Path(model_dir).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"本地 ViT 分类模型目录不存在：{path}")
    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"本地 ViT 分类模型缺少文件：{missing}")
    weights_path = path / "model.safetensors"
    if weights_path.stat().st_size < 1_024:
        raise ValueError("本地 ViT 权重不是有效模型文件；请先执行 git lfs pull")

    processor = AutoImageProcessor.from_pretrained(
        path,
        local_files_only=True,
        use_fast=False,
    )
    model = AutoModelForImageClassification.from_pretrained(
        path,
        local_files_only=True,
        use_safetensors=True,
    )
    label2id = {
        str(label).strip().lower(): int(index)
        for label, index in model.config.label2id.items()
    }
    if set(label2id) != {"no", "yes"} or set(label2id.values()) != {0, 1}:
        raise ValueError("本地 ViT 分类模型必须提供 no/yes 二分类标签")

    runtime_device = torch.device(device)
    model.to(runtime_device)
    model.eval()
    return LoadedBinarySliceClassifier(
        model=model,
        processor=processor,
        no_index=label2id["no"],
        yes_index=label2id["yes"],
        device=runtime_device,
        checkpoint_name=weights_path.name,
    )


def predict_images(
    loaded: LoadedBinarySliceClassifier,
    images: Sequence[Image],
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Classify in-memory MRI slices using the model's saved processor."""

    if not images:
        raise ValueError("本地 ViT 分类至少需要一张切片")
    if batch_size <= 0:
        raise ValueError("本地 ViT 分类 batch_size 必须大于 0")

    predictions: list[dict[str, Any]] = []
    with torch.inference_mode():
        for start in range(0, len(images), batch_size):
            batch = loaded.processor(
                images=[image.convert("RGB") for image in images[start : start + batch_size]],
                return_tensors="pt",
            )
            inputs = {
                name: value.to(loaded.device) if isinstance(value, torch.Tensor) else value
                for name, value in batch.items()
            }
            logits = loaded.model(**inputs).logits
            if logits.ndim != 2 or logits.shape[1] != 2:
                raise RuntimeError(
                    "本地 ViT 分类模型返回了无效输出："
                    f"shape={tuple(logits.shape)}"
                )
            probabilities = torch.softmax(logits, dim=-1).detach().cpu()
            for row in probabilities:
                no_probability = float(row[loaded.no_index].item())
                yes_probability = float(row[loaded.yes_index].item())
                predicted_tumor = yes_probability >= no_probability
                predictions.append(
                    {
                        "class": "yes" if predicted_tumor else "no",
                        "class_id": 1 if predicted_tumor else 0,
                        "confidence": max(no_probability, yes_probability),
                        "probabilities": {
                            "no": no_probability,
                            "yes": yes_probability,
                        },
                    }
                )
    return predictions
