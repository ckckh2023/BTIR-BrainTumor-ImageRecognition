'''清理缓存和结果文件'''

from __future__ import annotations

import shutil
from pathlib import Path

from repositories.user_repository import SqliteUserRepository
from repositories.task_repository_contracts import TaskRepository


def clear_generated_files(
    project_root: Path,
    output_dir: Path,
    archive_dir: Path,
    *,
    dry_run: bool,
    task_repository: TaskRepository,
    user_repository: SqliteUserRepository,
) -> None:
    '''将开发环境的业务数据与生成文件恢复为空白状态。'''
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    archive_dir = archive_dir.resolve()
    for name, path in (
        ("输出目录", output_dir),
        ("归档目录", archive_dir),
    ):
        if path == path.parent or path == project_root:
            raise ValueError(f"{name}不能是磁盘根目录或项目根目录")

    targets = [output_dir, archive_dir]
    cache_directory_names = {"__pycache__", ".pytest_cache", ".mypy_cache"}
    targets.extend( # 寻找缓存目录
        path
        for path in project_root.rglob("*")
        if path.is_dir() and path.name in cache_directory_names
    )
    targets.extend(path for path in project_root.rglob("*.pyc") if path.is_file()) # 寻找缓存文件
    targets.extend(path for path in project_root.rglob("*.pyo") if path.is_file()) # 寻找缓存文件

    # 去重并过滤掉子目录
    unique_targets = list(dict.fromkeys(path.resolve() for path in targets))
    root_targets = [
        path
        for path in unique_targets
        if not any(parent in unique_targets for parent in path.parents)
    ] # 寻找删除目标集的根目录
    existing_targets = [path for path in root_targets if path.exists()]
    task_count = task_repository.count()
    user_count = user_repository.count()
    if not existing_targets and task_count == 0 and user_count == 0:
        print("没有可清理的缓存或结果文件")
        return

    # 打印处理结果
    print("将清理：" if dry_run else "已清理：")
    for path in existing_targets:
        print(f"  {_display_path(path, project_root)}")
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    if task_count:
        print(f"  SQLite 任务记录：{task_count} 条")
        if not dry_run:
            deleted_count = task_repository.delete_all()
            print(f"  已删除 SQLite 任务记录：{deleted_count} 条")

    if user_count:
        print(f"  SQLite 用户账号：{user_count} 条")
        if not dry_run:
            deleted_count = user_repository.delete_all()
            print(f"  已删除 SQLite 用户账号：{deleted_count} 条")


def purge_logs_and_data(
    project_root: Path,
    *,
    dry_run: bool,
) -> None:
    '''删除 logs 和 data 目录本身及其全部内容。'''
    project_root = project_root.resolve()
    logs_dir = project_root / "logs"
    data_dir = project_root / "data"

    targets = [d for d in (logs_dir, data_dir) if d.is_dir()]

    if not targets:
        print("logs 和 data 目录均不存在，无需清理")
        return

    print("将清理：" if dry_run else "已清理：")
    for path in targets:
        print(f"  {_display_path(path, project_root)}")
        if dry_run:
            continue
        shutil.rmtree(path)


def _display_path(path: Path, project_root: Path) -> str:
    '''项目内显示相对路径，项目外显示绝对路径'''
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)
