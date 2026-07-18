from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torchvision import models


# 加入项目根目录到 sys.path，以便导入自定义模块
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processing.preprocessing import build_image_transform, load_rgb_image


def load_model(
    model_path: str | Path,
    config_path: str | Path,
    device: torch.device | str = "cpu",
) -> tuple[nn.Module, dict[str, Any]]:
    '''加载模型和配置'''
    with Path(config_path).open(encoding="utf-8") as file:
        config = json.load(file) # 读取配置

    model = models.resnet50(weights=None) # 创建 ResNet50 模型实例
    model.fc = nn.Sequential(
        nn.Dropout(0.5),
        nn.Linear(model.fc.in_features, 256),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(256, config["num_classes"]),
    )
    # 加载训练好的模型权重
    device = torch.device(device)
    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval() # 切换推理模式
    return model, config


def get_transform(config: dict[str, Any]):
    '''获取图像预处理变换函数 '''
    normalization = config["normalization"]
    return build_image_transform(
        (224, 224),
        mean=normalization["mean"],
        std=normalization["std"],
    )


def predict(model: nn.Module, image_path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    '''对单张图像进行预测'''
    image = load_rgb_image(image_path)
    device = next(model.parameters()).device
    input_tensor = get_transform(config)(image).unsqueeze(0).to(device)
    with torch.no_grad(): # 不计算梯度，计算推理结果
        output = model(input_tensor)
        probabilities = torch.nn.functional.softmax(output, dim=1)
        class_id = torch.argmax(probabilities, dim=1).item()

    return {
        "class": config["class_names"][class_id],
        "class_id": class_id,
        "confidence": probabilities[0][class_id].item(),
        "probabilities": {
            config["class_names"][index]: probabilities[0][index].item()
            for index in range(len(config["class_names"]))
        },
    }


def _print_prediction(prediction: dict[str, Any]) -> None:
    label = str(prediction["class"])
    label_text = {"yes": "疑似有肿瘤", "no": "未发现肿瘤"}.get(label, label)
    print(f"分类结果：{label_text} ({label})")
    print(f"置信度：{float(prediction['confidence']):.2%}")
    probabilities = prediction.get("probabilities", {})
    if probabilities:
        values = "；".join(
            f"{name} {float(score):.2%}" for name, score in probabilities.items()
        )
        print(f"各类别概率：{values}")


def main() -> int:
    '''主函数，解析命令行参数并执行分类模型推理'''
    parser = argparse.ArgumentParser(description="脑肿瘤 yes/no 分类模型（独立自测）")
    parser.add_argument("image_path", type=Path, help="输入 MRI 图像路径")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    args = parser.parse_args()
    if not args.image_path.is_file():
        parser.error(f"找不到输入图像：{args.image_path}")

    model_dir = Path(__file__).resolve().parent / "model"
    model, config = load_model(model_dir / "pytorch_model.pth", model_dir / "config.json")
    prediction = predict(model, args.image_path, config)
    result = {
        "model": "models/classification/resnet50",
        "image_path": str(args.image_path.resolve()),
        "classification": prediction,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("分类完成")
        print(f"输入图像：{result['image_path']}")
        _print_prediction(prediction)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
