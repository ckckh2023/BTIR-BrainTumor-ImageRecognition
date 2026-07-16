'''输出结果到终端或 JSON 文件'''

from __future__ import annotations

import json
from typing import Any


def print_json(data: dict[str, Any]) -> None:
    '''打印 JSON 数据到终端'''
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_result(data: dict[str, Any], as_json: bool) -> None:
    '''打印结果到终端或 JSON 文件'''
    if as_json:
        print_json(data)
        return

    if "combined_result_path" in data:
        print("一键推理完成")
        print(f"输入图像：{data['image_path']}")
        print()
        print_classification_text(data["classification"]["classification"])
        print()
        print_segmentation_text(data["segmentation"])
        print_task_paths(data)
        print(f"汇总结果：{data['combined_result_path']}")
        return

    if "classification" in data:
        print("分类完成")
        print(f"输入图像：{data['image_path']}")
        print_classification_text(data["classification"])
        print_task_paths(data)
        return

    print("分割完成")
    print(f"输入图像：{data['image_path']}")
    print_segmentation_text(data)
    print_task_paths(data)


def print_task_paths(data: dict[str, Any]) -> None:
    '''打印任务相关的路径信息'''
    task_dir = data.get("task_dir")
    if task_dir:
        print(f"任务目录：{task_dir}")
    frontend_path = data.get("frontend_result_path") or data.get("combined_result_path")
    if frontend_path:
        print(f"前端 JSON：{frontend_path}")


def print_classification_text(prediction: dict[str, Any]) -> None:
    '''打印分类结果到终端'''
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


def print_segmentation_text(result: dict[str, Any]) -> None:
    '''打印分割结果到终端'''
    print(f"分割阈值：{float(result['threshold']):.2f}")
    print(f"可疑区域像素：{int(result['tumor_pixels'])} / {int(result['image_pixels'])}")
    print(f"可疑区域占比：{float(result['tumor_area_ratio']):.2%}")
    print(f"Mask 文件：{result['mask_path']}")
