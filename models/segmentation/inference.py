from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch


# 加入项目根目录到 sys.path，以便导入自定义模块
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processing.preprocessing import build_image_transform, load_rgb_image
from processing.postprocessing import analyze_mask, save_mask
from model.unet import ResNet34UNet


PROJECT_DIR = Path(__file__).resolve().parent # 项目目录
MODEL_PATH = PROJECT_DIR / "model" / "best_unet_model.pth" # 模型权重路径
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output" # 默认输出目录


def load_model(model_path: Path = MODEL_PATH) -> ResNet34UNet:
    '''加载分割模型'''
    model = ResNet34UNet(out_classes=1)
    state_dict = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval() # 切换为推理模式
    return model


def preprocess_image(image_path: str | Path) -> torch.Tensor:
    '''预处理输入图像'''
    image = load_rgb_image(image_path)
    return build_image_transform((256, 256))(image).unsqueeze(0)


def predict(model: ResNet34UNet, image_path: str | Path, threshold: float = 0.5) -> np.ndarray:
    '''对单张图像进行分割预测'''
    image_tensor = preprocess_image(image_path)
    with torch.no_grad():
        output = model(image_tensor)
    return (output > threshold).float().squeeze().numpy()


def _print_segmentation_result(result: dict) -> None:
    print(f"分割阈值：{float(result['threshold']):.2f}")
    print(f"可疑区域像素：{int(result['tumor_pixels'])} / {int(result['image_pixels'])}")
    print(f"可疑区域占比：{float(result['tumor_area_ratio']):.2%}")
    print(f"Mask 文件：{result['mask_path']}")


def main() -> int:
    '''主函数，解析命令行参数并执行分割模型推理'''
    parser = argparse.ArgumentParser(description="脑肿瘤图像分割模型（独立自测）")
    parser.add_argument("image_path", type=Path, help="输入 MRI 图像路径")
    parser.add_argument("--threshold", type=float, default=0.5, help="分割阈值，默认 0.5")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Mask 输出目录")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    args = parser.parse_args()

    if not args.image_path.is_file():
        parser.error(f"找不到输入图像：{args.image_path}")
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold 必须位于 0 到 1 之间")

    model = load_model()
    mask = predict(model, args.image_path, args.threshold)
    output_path = save_mask(mask, args.image_path, args.output_dir)
    metrics = analyze_mask(mask)
    result = {
        "model": "models/segmentation/resnet34-unet",
        "image_path": str(args.image_path.resolve()),
        "threshold": args.threshold,
        "mask_path": output_path,
        **metrics,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("分割完成")
        print(f"输入图像：{result['image_path']}")
        _print_segmentation_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
