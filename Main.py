'''命令行入口，支持创建任务、运行分类/分割模型、清理缓存和结果等操作'''

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

from core.settings import SETTINGS
from repositories.task_repository import task_repository
from services.cleanup_service import clear_generated_files
from services.inference_service import classify, segment
from services.presentation import print_result
from services.task_service import (
    create_run_dir,
    create_task_dir,
    get_task_dir,
    initialize_task,
    load_task_image,
    persist_model_result,
    validate_image_path,
    write_json,
)


# 统一使用项目配置中的路径与默认阈值
PROJECT_ROOT = SETTINGS.project_root
DEFAULT_OUTPUT_DIR = SETTINGS.output_dir
SEGMENTER_DIR = SETTINGS.segmenter_script.parent


def main(argv: list[str] | None = None) -> int:
    '''主函数，解析命令行参数并执行相应操作'''
    parser = _build_parser()
    args = parser.parse_args(argv)
    task_dir: Path | None = None

    # 按照对应命令执行指定行为
    try:
        if args.command == "help":
            _print_help(parser)
            return 0

        if args.command == "clear":
            output_dir = args.output_dir.resolve()
            clear_generated_files(
                PROJECT_ROOT,
                output_dir,
                SEGMENTER_DIR,
                dry_run=args.dry_run,
                task_repository=task_repository,
                clear_task_metadata=output_dir == SETTINGS.output_dir.resolve(),
            )
            return 0

        output_root = args.output_dir.resolve()
        if args.command == "create":
            source_image = validate_image_path(args.image_path)
            task_dir = create_task_dir(output_root)
            image_path = initialize_task(
                task_dir,
                source_image,
                args.input_mode,
                args.name,
            )
            print(f"任务已创建：{task_dir.name}")
            print(f"任务目录：{task_dir}")
            print(f"任务图像：{image_path}")
            return 0

        if args.image_path is None and not args.task_id:
            raise ValueError("请提供 --task-id，或传入图片路径以创建新任务")

        if args.command in {"segment", "all"} and not 0.0 <= args.threshold <= 1.0:
            raise ValueError("--threshold 必须位于 0 到 1 之间")

        if args.task_id:
            task_dir = get_task_dir(output_root, args.task_id)
            image_path = load_task_image(task_dir)
        else:
            source_image = validate_image_path(args.image_path)
            task_dir = create_task_dir(output_root)
            image_path = initialize_task(task_dir, source_image, args.input_mode)

        if args.command == "classify":
            result = persist_model_result(
                task_dir, image_path, "classification", classify(image_path)
            )
            print_result(result, args.json)
            return 0

        if args.command == "segment":
            run_dir = create_run_dir(task_dir, "segmentation")
            result = persist_model_result(
                task_dir,
                image_path,
                "segmentation",
                segment(image_path, args.threshold, run_dir),
                run_dir,
            )
            print_result(result, args.json)
            return 0

        classification = persist_model_result(
            task_dir, image_path, "classification", classify(image_path)
        )
        segmentation_run_dir = create_run_dir(task_dir, "segmentation")
        segmentation = persist_model_result(
            task_dir,
            image_path,
            "segmentation",
            segment(image_path, args.threshold, segmentation_run_dir),
            segmentation_run_dir,
        )
        result = {
            "image_path": str(image_path),
            "classification": classification,
            "segmentation": segmentation,
            "task_dir": str(task_dir),
            "classification_result_path": classification["model_result_path"],
            "segmentation_result_path": segmentation["model_result_path"],
            "classification_history_path": classification["history_result_path"],
            "segmentation_history_path": segmentation["history_result_path"],
            "combined_result_path": segmentation["frontend_result_path"],
        }
        print_result(result, args.json)
        return 0
    except Exception as exc:
        if task_dir is not None:
            error_path = write_json(
                task_dir / "error.json",
                {
                    "task_id": task_dir.name,
                    "status": "failed",
                    "created_at": datetime.now().astimezone().isoformat(),
                    "command": args.command,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "traceback": traceback.format_exc(),
                },
            )
            print(f"错误日志：{error_path}", file=sys.stderr)
        print(f"处理失败：{exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    '''建立命令行参数解析器'''
    parser = argparse.ArgumentParser(
        description="脑肿瘤图像解释器：可独立运行分类、分割，或一键运行。"
    )
    commands = parser.add_subparsers(dest="command", required=True) # 要求必须指定子命令

    # 添加help子命令
    commands.add_parser("help", help="显示命令说明和使用示例")

    # 添加clear子命令
    clear = commands.add_parser("clear", help="清理 Python 缓存和默认生成结果")
    clear.add_argument( # --dry-run 参数
        "--dry-run",
        action="store_true",
        help="仅列出将清理的文件，不实际删除",
    )
    clear.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"任务结果根目录，默认 {DEFAULT_OUTPUT_DIR}",
    )

    # 添加create子命令
    create = commands.add_parser("create", help="创建任务并保存一次输入图片")
    create.add_argument("image_path", type=Path, help="输入 MRI 图像路径") # image_path 参数
    create.add_argument("--name", help="任务显示名称，并非task任务id") # --name 参数
    create.add_argument( # --input-mode 参数
        "--input-mode",
        choices=("auto", "hardlink", "copy", "reference"),
        default="auto",
        help="输入保存方式：auto 优先硬链接，失败时复制",
    )
    create.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR) # --output-dir 参数

    # 添加classify子命令
    classify_command = commands.add_parser("classify", help="运行 yes/no 分类模型")
    _add_model_arguments(classify_command, with_threshold=False)

    for command_name, help_text in (
        ("segment", "运行 U-Net 分割模型"),
        ("all", "依次运行 分类 和 分割 模型"),
    ):
        command = commands.add_parser(command_name, help=help_text)
        _add_model_arguments(command, with_threshold=True)
    return parser


def _add_model_arguments(
    command: argparse.ArgumentParser, *, with_threshold: bool
) -> None:
    '''为模型运行命令添加通用参数'''
    command.add_argument("image_path", type=Path, nargs="?", help="旧用法；建议改用 --task-id") # image_path 参数
    if with_threshold:
        command.add_argument(
            "--threshold",
            type=float,
            default=SETTINGS.default_segment_threshold,
            help=f"分割阈值，默认 {SETTINGS.default_segment_threshold}",
        ) # --threshold 参数
    command.add_argument("--json", action="store_true", help="输出完整 JSON 结果") # --json 参数
    command.add_argument("--task-id", help="写入已有任务；省略时自动创建新任务") # --task-id 参数
    command.add_argument( # --input-mode 参数
        "--input-mode",
        choices=("auto", "hardlink", "copy", "reference"),
        default="auto",
        help="仅在直接传图片路径时使用",
    )
    command.add_argument( # --output-dir 参数
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"任务结果根目录，默认 {DEFAULT_OUTPUT_DIR}",
    )


def _print_help(parser: argparse.ArgumentParser) -> None:
    '''打印帮助信息和使用示例'''
    parser.print_help()
    print(
        "\n示例：\n"
        "  python Main.py create dataset/yes/Y101.jpg\n"
        "  python Main.py classify --task-id <task_id>\n"
        "  python Main.py segment --task-id <task_id>\n"
        "  python Main.py all --task-id <task_id>\n"
        "  python Main.py create dataset/yes/Y101.jpg --input-mode copy\n"
        "  python Main.py clear --dry-run"
    )


if __name__ == "__main__":
    raise SystemExit(main())
