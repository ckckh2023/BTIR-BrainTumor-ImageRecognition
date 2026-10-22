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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [推理进程] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    print_event("正在连接推理队列")
    queue = get_task_queue()
    worker_class = _get_worker_class()
    if worker_class is SimpleWorker and SETTINGS.worker_preload_models:
        print_event("正在预加载推理模型，首次加载可能需要较长时间")
        outcomes = preload_inference_models()
        if any(isinstance(value, str) and value.startswith("failed:") for value in outcomes.values()):
            logger.warning("部分推理模型预加载失败，结果=%s", outcomes)
        else:
            logger.info("推理模型预加载完成，结果=%s", outcomes)
    elif SETTINGS.worker_preload_models:
        logger.info("当前使用 Linux 标准 RQ 推理进程，已跳过模型预加载")
    '''生成唯一 Worker 名称'''
    worker_name = (
        f"btir-inference-3d-{socket.gethostname()}-{os.getpid()}"
    )
    worker = worker_class(
        [queue],
        connection=get_redis_client(),
        name=worker_name,
    )
    print_event(f"推理进程已启动，监听队列 {queue.name}", level="success")
    worker.work()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 BTIR RQ 推理进程")
    return parser


def _get_worker_class():
    if os.name == "nt" or SETTINGS.linux_worker_mode == "simple":
        return SimpleWorker
    return Worker


if __name__ == "__main__":
    main()
