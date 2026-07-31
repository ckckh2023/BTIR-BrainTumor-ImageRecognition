'''启动单进程 RQ 推理 worker'''

from __future__ import annotations

import argparse
import logging
import os
import socket

from rq import SimpleWorker, Worker

from core.settings import SETTINGS
from core.task_definitions import AnalysisMode
from services.inference_service import preload_inference_models
from services.console import print_event
from services.redis_client import get_redis_client
from services.task_queue import get_task_queue

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    modes = (
        (AnalysisMode.TWO_D, AnalysisMode.THREE_D)
        if args.pipeline == "all"
        else (AnalysisMode(args.pipeline),)
    )
    queues = [get_task_queue(mode) for mode in modes]
    worker_class = _get_worker_class()
    if worker_class is SimpleWorker and SETTINGS.worker_preload_models:
        preload_mode = modes[0] if len(modes) == 1 else None
        outcomes = preload_inference_models(preload_mode)
        if any(isinstance(value, str) and value.startswith("failed:") for value in outcomes.values()):
            logger.warning("worker model preload partially failed outcomes=%s", outcomes)
        else:
            logger.info("worker model preload completed outcomes=%s", outcomes)
    elif SETTINGS.worker_preload_models:
        logger.info("worker model preload skipped for standard Linux RQ worker")
    # 使用主机名和进程号保证每次启动的 worker 名称唯一；异常退出后遗留的
    # Redis 注册记录不会再阻止新的 worker 启动
    worker_name = (
        f"btir-inference-{args.pipeline}-{socket.gethostname()}-{os.getpid()}"
    )
    worker = worker_class(
        queues,
        connection=get_redis_client(),
        name=worker_name,
    )
    queue_names = ", ".join(str(queue.name) for queue in queues)
    print_event(f"worker 已启动，监听队列 {queue_names}", level="success")
    worker.work()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 BTIR RQ 推理 Worker")
    parser.add_argument(
        "--pipeline",
        choices=("2d", "3d", "all"),
        default="all",
        help="监听的推理路线；正式部署建议分别启动 2d 和 3d",
    )
    return parser


def _get_worker_class():
    if os.name == "nt" or SETTINGS.linux_worker_mode == "simple":
        return SimpleWorker
    return Worker


if __name__ == "__main__":
    main()
