'''为资源进行预处理，便于之后的模型调用'''

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image
from torchvision import transforms


# 定义RGB默认值
DEFAULT_MEAN = (0.485, 0.456, 0.406) # RGB通道的均值
DEFAULT_STD = (0.229, 0.224, 0.225) # RGB通道的标准差


def load_rgb_image(image_path: str | Path) -> Image.Image:
    '''加载RGB图像，并将其转换为RGB模式'''
    return Image.open(image_path).convert("RGB")


def build_image_transform(
    size: tuple[int, int],
    mean: Sequence[float] = DEFAULT_MEAN,
    std: Sequence[float] = DEFAULT_STD,
) -> transforms.Compose:
    '''创建由Resize → Tensor → Normalize组成的处理流水线，供模型使用'''
    return transforms.Compose(
        [
            transforms.Resize(size),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ]
    )
