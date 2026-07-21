'''仅供真实 RQ 集成测试调用的轻量作业'''

from __future__ import annotations

from rq import get_current_job


def echo_payload(payload: dict[str, str]) -> dict[str, str]:
    '''返回输入，验证 worker 可导入并执行测试作业'''
    return payload


def fail_once(counter_key: str) -> dict[str, int]:
    '''首次调用失败，第二次调用成功，用于验证 RQ Retry'''
    job = get_current_job()
    if job is None:
        raise RuntimeError("测试作业必须由 RQ worker 执行")
    attempts = job.connection.incr(counter_key)
    if attempts == 1:
        raise RuntimeError("intentional first-attempt failure")
    return {"attempts": attempts}
