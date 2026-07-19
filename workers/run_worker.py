'''启动单进程 RQ 推理 worker'''

from __future__ import annotations

import os
import socket

from rq import SimpleWorker, Worker

from services.task_queue import get_queue_redis, get_task_queue


def main() -> None:
    queue = get_task_queue()
    worker_class = SimpleWorker if os.name == "nt" else Worker
    # 使用主机名和进程号保证每次启动的 worker 名称唯一；异常退出后遗留的
    # Redis 注册记录不会再阻止新的 worker 启动
    worker_name = f"btir-inference-{socket.gethostname()}-{os.getpid()}"
    worker = worker_class(
        [queue],
        connection=get_queue_redis(),
        name=worker_name,
    )
    worker.work()


if __name__ == "__main__":
    main()
