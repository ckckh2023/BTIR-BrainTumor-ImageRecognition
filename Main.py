'''命令行入口，支持创建任务、运行分类/分割模型、清理缓存和结果等操作'''

from __future__ import annotations

import argparse
import getpass
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from core.settings import SETTINGS
from contracts.auth import RegisterRequest
from core.task_definitions import InputStorageMode, TaskStatus
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.task_repository import task_repository
from repositories.user_repository import (
    SqliteUserRepository,
    UsernameAlreadyExistsError,
)
from services.archive_service import archive_expired_tasks, purge_expired_archives
from services.auth_service import hash_password
from services.benchmark_service import benchmark_models
from services.cleanup_service import clear_generated_files
from services.console import ConsoleProgress, print_event
from services.presentation import print_result
from services.terminal_game import run_game
from services.task_queue import clear_task_queue_state, reconcile_active_tasks
from services.task_files import (
    create_task_dir,
    get_task_dir,
    initialize_task,
    validate_image_path,
    write_json,
)
from services.task_runner import (
    run_classification,
    run_segmentation,
    run_task_models,
)


# 统一使用项目配置中的路径与默认阈值
PROJECT_ROOT = SETTINGS.project_root
DEFAULT_OUTPUT_DIR = SETTINGS.output_dir
SEGMENTER_DIR = SETTINGS.segmenter_script.parent


def main(argv: list[str] | None = None) -> int:
    '''主函数，解析命令行参数并执行相应操作'''
    command_args = list(sys.argv[1:] if argv is None else argv)
    if command_args == ["game"]:
        return run_game()
    parser = _build_parser()
    args = parser.parse_args(command_args)
    task_dir: Path | None = None

    # 按照对应命令执行指定行为
    try:
        if args.command == "help":
            _print_help(parser)
            return 0

        print_event(f"开始执行 {args.command}")

        if args.command == "clear":
            queue_report = clear_task_queue_state(dry_run=args.dry_run)
            _print_queue_reset_report(queue_report, dry_run=args.dry_run)
            clear_generated_files(
                PROJECT_ROOT,
                SETTINGS.output_dir,
                SETTINGS.task_archive_dir,
                SEGMENTER_DIR,
                dry_run=args.dry_run,
                task_repository=task_repository,
                user_repository=SqliteUserRepository(task_repository),
            )
            return 0

        if args.command == "archive-tasks":
            report = archive_expired_tasks(
                dry_run=not args.apply,
                limit=args.limit,
            )
            _print_archive_report(report)
            return 0

        if args.command == "purge-archive":
            report = purge_expired_archives(
                dry_run=not args.apply,
                limit=args.limit,
            )
            _print_archive_report(report)
            return 0

        if args.command == "reconcile-tasks":
            report = reconcile_active_tasks(limit=args.limit)
            _print_task_reconciliation_report(report)
            return 0

        if args.command == "claim-legacy-tasks":
            _claim_legacy_tasks(args.username, apply=args.apply)
            return 0

        if args.command == "user":
            _manage_user(args)
            return 0

        if args.command == "benchmark":
            result = benchmark_models(
                args.image_path,
                threshold=args.threshold,
                warm_runs=args.warm_runs,
            )
            print_result(result, args.json)
            return 0

        if args.command == "evaluate-3d":
            from services.segmentation_evaluation import (
                evaluate_brats_segmentation,
            )

            progress = ConsoleProgress()
            result = evaluate_brats_segmentation(
                args.dataset_dir,
                predictions_dir=args.predictions_dir,
                limit=args.limit,
                progress_callback=progress.update,
            )
            report_path = write_json(args.report.resolve(), result)
            _print_3d_evaluation_report(result, report_path, as_json=args.json)
            return 1 if result["failed_subjects"] else 0

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

        if args.command in {"segment", "all"} and not 0.0 <= args.threshold <= 1.0:
            raise ValueError("--threshold 必须位于 0 到 1 之间")

        task_dir = get_task_dir(output_root, args.task_id)

        if args.command == "classify":
            progress = ConsoleProgress()
            progress.update("分类推理中", 0)
            model_run = run_classification(task_dir)
            progress.update("分类完成", 100)
            print_result(model_run.result, args.json)
            return 0

        if args.command == "segment":
            progress = ConsoleProgress()
            progress.update("分割推理中", 0)
            model_run = run_segmentation(task_dir, args.threshold)
            progress.update("分割完成", 100)
            print_result(model_run.result, args.json)
            return 0

        progress = ConsoleProgress()
        run_result = run_task_models(
            task_dir,
            args.threshold,
            progress_callback=progress.update,
        )
        image_path = run_result.image_path
        classification = run_result.classification_result
        segmentation = run_result.segmentation_result
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
                    "status": TaskStatus.FAILED.value,
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
    commands.add_parser("game", help="启动终端扫瘤小游戏")

    # 添加clear子命令
    clear = commands.add_parser(
        "clear",
        help="清空账号、任务、归档、BTIR 队列状态和 Python 缓存",
    )
    clear.add_argument( # --dry-run 参数
        "--dry-run",
        action="store_true",
        help="仅列出将清理的文件，不实际删除",
    )
    for command_name, help_text in (
        ("archive-tasks", "将超过保留期的终态任务移入归档区"),
        ("purge-archive", "永久删除超过归档宽限期的任务"),
    ):
        archive_command = commands.add_parser(command_name, help=help_text)
        archive_command.add_argument(
            "--apply",
            action="store_true",
            help="实际执行；省略时仅预览候选任务",
        )
        archive_command.add_argument(
            "--limit",
            type=int,
            default=100,
            choices=range(1, 1001),
            metavar="1-1000",
            help="本次最多处理的任务数，默认 100",
        )

    reconcile = commands.add_parser(
        "reconcile-tasks",
        help="批量同步活动任务与 RQ 作业状态",
    )
    reconcile.add_argument(
        "--limit",
        type=int,
        default=SETTINGS.task_reconcile_batch_size,
        choices=range(1, 1001),
        metavar="1-1000",
        help="本次最多巡检的活动任务数，默认由 BTIR_TASK_RECONCILE_BATCH_SIZE 决定",
    )

    claim_legacy = commands.add_parser(
        "claim-legacy-tasks",
        help="将多用户上线前的无归属任务分配给指定用户",
    )
    claim_legacy.add_argument("username", help="接收历史任务的已注册用户名")
    claim_legacy.add_argument(
        "--apply",
        action="store_true",
        help="实际写入；省略时仅预览数量",
    )

    user = commands.add_parser(
        "user",
        help="在服务器终端创建、查询和维护用户账号",
    )
    user_commands = user.add_subparsers(dest="user_command", required=True)
    user_create = user_commands.add_parser("create", help="创建用户账号")
    user_create.add_argument("username", help="新用户名称")
    user_commands.add_parser("list", help="列出用户账号，不显示密码信息")
    for command_name, help_text in (
        ("enable", "启用用户账号"),
        ("disable", "禁用用户账号并撤销旧 Token"),
        ("reset-password", "重置用户密码并撤销旧 Token"),
    ):
        user_command = user_commands.add_parser(command_name, help=help_text)
        user_command.add_argument("username", help="目标用户名")

    benchmark = commands.add_parser(
        "benchmark",
        help="测量分类与分割模型在当前进程中的首次和连续推理耗时",
    )
    benchmark.add_argument("image_path", type=Path, help="用于基准测试的输入图像")
    benchmark.add_argument(
        "--warm-runs",
        type=int,
        default=3,
        help="首次调用后连续测量次数，默认 3",
    )
    benchmark.add_argument(
        "--threshold",
        type=float,
        default=SETTINGS.default_segment_threshold,
        help=f"分割阈值，默认 {SETTINGS.default_segment_threshold}",
    )
    benchmark.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    evaluate_3d = commands.add_parser(
        "evaluate-3d",
        help="用带 seg 标签的 BraTS 数据集评测 3D 分割 Dice、耗时和显存",
    )
    evaluate_3d.add_argument(
        "dataset_dir",
        type=Path,
        help="包含多个四模态 BraTS 受试者目录的数据集根目录",
    )
    evaluate_3d.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "evaluations" / "segmentation3d-report.json",
        help="JSON 报告路径，默认 output/evaluations/segmentation3d-report.json",
    )
    evaluate_3d.add_argument(
        "--predictions-dir",
        type=Path,
        help="可选；保留每个病例预测 NIfTI 的目录，默认仅保留报告",
    )
    evaluate_3d.add_argument(
        "--limit",
        type=int,
        choices=range(1, 10001),
        metavar="1-10000",
        help="可选；仅评测排序后的前 N 个病例",
    )
    evaluate_3d.add_argument(
        "--json",
        action="store_true",
        help="除保存报告外，同时在控制台输出完整 JSON",
    )

    # 添加create子命令
    create = commands.add_parser("create", help="创建任务并保存一次输入图片")
    create.add_argument("image_path", type=Path, help="输入 MRI 图像路径") # image_path 参数
    create.add_argument("--name", help="任务显示名称，并非task任务id") # --name 参数
    create.add_argument( # --input-mode 参数
        "--input-mode",
        choices=tuple(mode.value for mode in InputStorageMode),
        default=InputStorageMode.AUTO.value,
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
    if with_threshold:
        command.add_argument(
            "--threshold",
            type=float,
            default=SETTINGS.default_segment_threshold,
            help=f"分割阈值，默认 {SETTINGS.default_segment_threshold}",
        ) # --threshold 参数
    command.add_argument("--json", action="store_true", help="输出完整 JSON 结果") # --json 参数
    command.add_argument("--task-id", required=True, help="要运行的已有任务 ID") # --task-id 参数
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
        "  python Main.py clear --dry-run\n"
        "  python Main.py archive-tasks\n"
        "  python Main.py purge-archive\n"
        "  python Main.py reconcile-tasks\n"
        "  python Main.py claim-legacy-tasks <username> --apply\n"
        "  python Main.py user create <username>\n"
        "  python Main.py user list\n"
        "  python Main.py user disable <username>\n"
        "  python Main.py user reset-password <username>\n"
        "  python Main.py benchmark dataset/no/1.jpg --warm-runs 3\n"
        "  python Main.py evaluate-3d <BraTS数据集目录>\n"
        "  python Main.py game\n"
    )


def _print_3d_evaluation_report(
    report: dict,
    report_path: Path,
    *,
    as_json: bool,
) -> None:
    '''输出简明 3D 评测摘要，并保留完整 JSON 报告路径'''

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "3D 分割评测："
            f"成功 {report['successful_subjects']} 例，"
            f"失败 {report['failed_subjects']} 例"
        )
        dice_summary = report["summary"]["dice"]
        for region in ("WT", "TC", "ET"):
            statistics = dice_summary[region]
            value = statistics["mean"]
            value_text = "不可评估" if value is None else f"{value:.4f}"
            print(
                f"  {region} Dice 均值：{value_text}"
                f"（{statistics['evaluated_cases']} 例）"
            )
        timing = report["summary"]["inference_ms"]
        if timing["mean"] is not None:
            print(f"  单病例平均耗时：{timing['mean'] / 1000:.3f} 秒")
        memory = report["summary"]["peak_gpu_memory_mb"]
        if memory["max"] is not None:
            print(f"  GPU 峰值显存：{memory['max']:.1f} MiB")
    print(f"完整报告：{report_path}")


def _print_archive_report(report) -> None:
    '''输出归档或永久删除的预览/执行结果'''
    action = "将处理" if report.dry_run else "已处理"
    print(f"{action} {report.operation} 任务：{len(report.processed_task_ids)} 条")
    for task_id in report.processed_task_ids:
        print(f"  {task_id}")
    if report.skipped_task_ids:
        print(f"跳过任务：{len(report.skipped_task_ids)} 条")
        for task_id in report.skipped_task_ids:
            print(f"  {task_id}")


def _print_task_reconciliation_report(report) -> None:
    '''仅在存在活动任务时输出巡检摘要，供 supervisor 日志记录'''
    if report.scanned_task_count == 0 and not report.skipped_task_ids:
        return
    print(
        f"已巡检活动任务：{report.scanned_task_count} 条；"
        f"状态已修复：{len(report.changed_task_ids)} 条"
    )
    for task_id in report.changed_task_ids:
        print(f"  {task_id}")
    if report.skipped_task_ids:
        print(f"正在写入而跳过：{len(report.skipped_task_ids)} 条")


def _print_queue_reset_report(report, *, dry_run: bool) -> None:
    '''输出 clear 对本项目 Redis 状态的处理范围'''
    action = "将清理" if dry_run else "已清理"
    print(
        f"{action} Redis 队列 {', '.join(report.queue_names)}："
        f"排队作业 {report.queued_job_count} 条，"
        f"注册表作业 {report.registry_job_count} 条，"
        f"任务锁 {report.task_lock_count} 个"
    )
    if report.active_worker_count:
        print(f"检测到活动推理 Worker：{report.active_worker_count} 个")


def _claim_legacy_tasks(username: str, *, apply: bool) -> None:
    if not isinstance(task_repository, SqliteTaskRepository):
        raise RuntimeError("历史任务认领仅支持 SQLite 任务仓储")

    user = SqliteUserRepository(task_repository).get_by_username(username)
    if user is None:
        raise ValueError(f"用户 '{username}' 不存在，请先完成注册")

    pending = task_repository.count_unowned_tasks()
    if not apply:
        print(f"将把 {pending} 条无归属历史任务分配给用户：{username}")
        print("当前为预览；确认后追加 --apply")
        return

    changed = task_repository.assign_unowned_tasks(user.user_id)
    print(f"已把 {changed} 条无归属历史任务分配给用户：{username}")


def _sqlite_user_repository() -> SqliteUserRepository:
    if not isinstance(task_repository, SqliteTaskRepository):
        raise RuntimeError("用户管理命令仅支持 SQLite 用户仓储")
    return SqliteUserRepository(task_repository)


def _read_new_password(username: str) -> str:
    password = getpass.getpass("输入新密码：")
    confirmation = getpass.getpass("再次输入新密码：")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致")
    return RegisterRequest(username=username, password=password).password


def _manage_user(args: argparse.Namespace) -> None:
    repository = _sqlite_user_repository()
    command = args.user_command

    if command == "list":
        users = repository.list_users()
        if not users:
            print("暂无用户账号")
            return
        print(f"用户账号：{len(users)} 个")
        for user in users:
            status_text = "启用" if user.is_active else "禁用"
            print(f"  {user.username}\t{status_text}\t{user.created_at.isoformat()}")
        return

    username = args.username
    if command == "create":
        password = _read_new_password(username)
        try:
            user = repository.create_user(username, hash_password(password))
        except UsernameAlreadyExistsError:
            raise ValueError(f"用户 '{username}' 已存在") from None
        print(f"用户已创建：{user.username}")
        return

    existing = repository.get_by_username(username)
    if existing is None:
        raise ValueError(f"用户 '{username}' 不存在")

    if command == "reset-password":
        password = _read_new_password(username)
        repository.update_password(username, hash_password(password))
        print(f"用户密码已重置，旧 Token 已失效：{username}")
        return

    is_active = command == "enable"
    if existing.is_active == is_active:
        print(f"用户已经处于{'启用' if is_active else '禁用'}状态：{username}")
        return
    repository.set_active(username, is_active)
    if is_active:
        print(f"用户已启用：{username}")
    else:
        print(f"用户已禁用，旧 Token 已失效：{username}")


if __name__ == "__main__":
    raise SystemExit(main())
