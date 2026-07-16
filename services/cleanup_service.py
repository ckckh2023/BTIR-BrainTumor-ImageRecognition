'''清理缓存和结果文件'''

from __future__ import annotations

import shutil
from pathlib import Path


def clear_generated_files(
    project_root: Path,
    output_dir: Path,
    segmentation_dir: Path,
    *,
    dry_run: bool,
) -> None:
    '''仅用于清理缓存和结果文件'''
    targets = [output_dir, segmentation_dir / "output"]
    cache_directory_names = {"__pycache__", ".pytest_cache", ".mypy_cache"}
    targets.extend( # 寻找缓存目录
        path
        for path in project_root.rglob("*")
        if path.is_dir() and path.name in cache_directory_names
    )
    targets.extend(path for path in project_root.rglob("*.pyc") if path.is_file()) # 寻找缓存文件
    targets.extend(path for path in project_root.rglob("*.pyo") if path.is_file()) # 寻找缓存文件
    targets.extend(segmentation_dir.glob("*_segmented.png")) # 寻找结果文件

    # 去重并过滤掉子目录
    unique_targets = list(dict.fromkeys(path.resolve() for path in targets))
    root_targets = [
        path
        for path in unique_targets
        if not any(parent in unique_targets for parent in path.parents)
    ] # 寻找删除目标集的根目录
    existing_targets = [path for path in root_targets if path.exists()]
    if not existing_targets:
        print("没有可清理的缓存或结果文件。")
        return

    # 打印处理结果
    print("将清理：" if dry_run else "已清理：")
    for path in existing_targets:
        print(f"  {path.relative_to(project_root)}")
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
