'''启动单进程 RQ 推理 worker'''

from __future__ import annotations

import argparse
import logging
import os
import socket

from rq import SimpleWorker, Worker

from core.settings import SETTINGS
from services.inference_service import preload_inference_models
from services.console import print_event
from services.redis_client import get_redis_client
from services.task_queue import get_task_queue

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    _build_parser().parse_args(argv)
    queues = [get_task_queue()]
    worker_class = _get_worker_class()
    if worker_class is SimpleWorker and SETTINGS.worker_preload_models:
        outcomes = preload_inference_models()
        if any(isinstance(value, str) and value.startswith("failed:") for value in outcomes.values()):
            logger.warning("worker model preload partially failed outcomes=%s", outcomes)
        else:
            logger.info("worker model preload completed outcomes=%s", outcomes)
    elif SETTINGS.worker_preload_models:
        logger.info("worker model preload skipped for standard Linux RQ worker")
    # 使用主机名和进程号保证每次启动的 worker 名称唯一；异常退出后遗留的
    # Redis 注册记录不会再阻止新的 worker 启动
    worker_name = (
        f"btir-inference-3d-{socket.gethostname()}-{os.getpid()}"
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
    return parser


def _get_worker_class():
    if os.name == "nt" or SETTINGS.linux_worker_mode == "simple":
        return SimpleWorker
    return Worker


if __name__ == "__main__":
    main()
