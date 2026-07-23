'''启动单进程 RQ 推理 worker'''

from __future__ import annotations

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


def main() -> None:
    queue = get_task_queue()
    worker_class = SimpleWorker if os.name == "nt" else Worker
    if os.name == "nt" and SETTINGS.worker_preload_models:
        outcomes = preload_inference_models()
        if any(isinstance(value, str) and value.startswith("failed:") for value in outcomes.values()):
            logger.warning("worker model preload partially failed outcomes=%s", outcomes)
        else:
            logger.info("worker model preload completed outcomes=%s", outcomes)
    elif SETTINGS.worker_preload_models:
        logger.info("worker model preload skipped for standard Linux RQ worker")
    # 使用主机名和进程号保证每次启动的 worker 名称唯一；异常退出后遗留的
    # Redis 注册记录不会再阻止新的 worker 启动
    worker_name = f"btir-inference-{socket.gethostname()}-{os.getpid()}"
    worker = worker_class(
        [queue],
        connection=get_redis_client(),
        name=worker_name,
    )
    print_event(f"worker 已启动，监听队列 {SETTINGS.task_queue_name}", level="success")
    worker.work()


if __name__ == "__main__":
    main()
