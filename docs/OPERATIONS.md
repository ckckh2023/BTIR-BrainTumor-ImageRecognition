# BTIR 运维与数据管理

本文说明健康检查、队列状态、异常恢复、SQLite、任务目录、归档、清理、
测试和性能基准。

## 健康检查

### API 存活

```http
GET /healthz
```

只确认 API 进程能够响应，不访问 SQLite、Redis、Worker 或模型文件。
适合进程存活探针。

### 完整就绪状态

```http
GET /readyz
```

检查：

- SQLite 任务数据库
- Redis
- 推理 Worker 注册状态
- 分类与分割模型文件

全部正常时返回 `200`；任一关键组件不可用时返回 `503`，并在
`detail.components` 标出组件状态。

### 运行设备

```http
GET /runtime
```

返回请求设备、实际设备、CPU/CUDA/ROCm 后端、PyTorch 版本、加速设备名称，
以及 SQLite 后端是否可用。

### 队列状态

```http
GET /ops/queue
```

返回：

- `active_workers`
- `queued_jobs`
- `running_jobs`
- `failed_jobs`
- `oldest_wait_seconds`

Redis 不可用时返回 `503`。

## Redis、RQ 与任务恢复

Redis 同时用于：

- RQ 异步任务队列
- 任务结果写回锁
- Worker 注册和队列状态

同一任务已经处于 `queued` 或 `running` 时，重复提交会复用原作业，不会
重复入队。

默认 `BTIR_TASK_JOB_MAX_RETRIES=1`，第一次执行失败后由 RQ 自动重试一次；
第二次仍失败才将任务标记为 `failed`。

任务查询会对照 RQ 状态。`running` 超过
`BTIR_TASK_STALE_AFTER_SECONDS` 仍未结束时，会收敛为 `failed`。

批量巡检活动任务：

```powershell
python Main.py reconcile-tasks
```

限制本次最多检查的任务数：

```powershell
python Main.py reconcile-tasks --limit 100
```

守护脚本默认定期执行同一套巡检，使服务异常重启后的状态不必等待用户查询
才恢复一致。

## 并发写入安全

任务结果写入时使用 Redis 锁，保护 SQLite 元数据、
`frontend_result.json` 和其他共享结果，避免并发模型或异步任务互相覆盖。

SQLite 记录通过事务写入；JSON 结果采用临时文件替换的原子写入方式。读取方
只会看到完整旧文件或完整新文件。

相关配置：

```dotenv
BTIR_TASK_LOCK_TIMEOUT_SECONDS=30
BTIR_TASK_LOCK_WAIT_SECONDS=5
```

锁等待超时后，接口返回 `409 Conflict`，不会绕过锁继续写入。

## SQLite 任务数据库

默认数据库：

```text
data/btir.db
```

保存任务 ID、状态、输入摘要、RQ 作业信息、运行记录、错误信息和归档时间。
图像、掩码与完整结果文件仍保存在文件系统。

首次启动会自动创建数据库。程序按顺序执行 schema migration，并在
`schema_migrations` 表记录已应用版本。升级程序时：

- 不需要手动建表或修改版本号。
- 不要直接编辑 `schema_migrations`。
- 部署前应备份数据库和任务目录。
- 前端与外部服务不得直接查询 SQLite，应统一通过 API。

任务目录存在但 SQLite 没有对应元数据时，任务接口返回 `404`；数据库不可用
时返回 `503`。

## 任务目录

默认结构：

```text
output/
└── 20260715_120000_001/
    ├── input/
    │   └── image.jpg
    ├── classification.json
    ├── segmentation.json
    ├── runs/
    ├── frontend_result.json
    └── error.json

data/
└── btir.db
```

同一模型在一个任务中重复运行时：

- `runs/<model>/` 追加不可变的历史结果。
- 当前模型结果更新为最新一次。
- `frontend_result.json` 更新为最新统一结果。
- 不创建新的任务，也不覆盖已有历史运行目录。

任务文件接口会限制读取范围，并过滤 JSON 中的本机路径字段。不要把任务目录
作为静态目录直接对外暴露。

## 归档策略

归档与永久删除默认关闭：

```dotenv
BTIR_TASK_CLEANUP_ENABLED=false
BTIR_SUCCEEDED_TASK_RETENTION_DAYS=30
BTIR_FAILED_TASK_RETENTION_DAYS=7
BTIR_TASK_ARCHIVE_GRACE_DAYS=7
BTIR_TASK_ARCHIVE_DIR=archive
```

默认只预览候选任务，不移动或删除数据：

```powershell
python Main.py archive-tasks
python Main.py purge-archive
```

实际执行必须同时满足：

1. `BTIR_TASK_CLEANUP_ENABLED=true`
2. 命令明确传入 `--apply`

```powershell
python Main.py archive-tasks --apply
python Main.py purge-archive --apply
```

处理规则：

- 只归档超过保留期的 `succeeded`、`failed` 和 `canceled` 终态任务。
- 操作前再次确认任务不是活动状态。
- 先将整个任务目录移动到 `archive/tasks/`。
- 超过 `BTIR_TASK_ARCHIVE_GRACE_DAYS` 后才可永久删除。
- 每项实际操作记录在 `archive/audit.jsonl`。
- 模型、Python 缓存和活动任务不会被归档流程处理。

`BTIR_OUTPUT_DIR` 与 `BTIR_TASK_ARCHIVE_DIR` 必须位于同一磁盘卷；生产环境
可分别设置为 `/var/lib/btir/output` 和 `/var/lib/btir/archive`。

可以限制单次候选数量：

```powershell
python Main.py archive-tasks --limit 100
python Main.py purge-archive --limit 100
```

普通 `GET /tasks` 默认排除已归档记录，避免列表存在但活动任务文件已经移走。

### 指定任务软删除

前端调用：

```http
DELETE /tasks/{task_id}
```

会立即将指定非活动任务移入同一归档区，审计操作记为 `archive_api`。该接口
不受 `BTIR_TASK_CLEANUP_ENABLED` 开关限制，因为它来自用户明确操作；但后续
永久清除仍必须启用清理并执行 `purge-archive --apply`。

排队、运行或等待取消的任务不能软删除。应先取消并等待状态变为
`canceled`，再重新请求删除。

## 手动清理

先预览：

```powershell
python Main.py clear --dry-run
```

指定其他输出目录时：

```powershell
python Main.py clear --output-dir D:\btir-output --dry-run
```

`clear` 是开发期手动清理工具，与任务归档策略不同。执行前始终先使用
`--dry-run` 确认目标；不要用 Redis 的 `FLUSHALL`、`FLUSHDB` 或类似命令替代
项目清理流程。

## 自动化测试

运行全量测试：

```powershell
python -m unittest discover -s tests -v
```

基础测试使用临时目录，不依赖已有任务数据。Redis 可用时会额外运行真实 RQ
`SimpleWorker` 的入队、执行和失败重试集成测试；Redis 不可用时该组测试按
原有规则跳过。

部署前至少确认：

- 全量测试通过。
- `/readyz` 返回 `200`。
- `/ops/queue` 能看到活动 Worker。
- 上传、异步运行、轮询和结果读取流程完成一次。

## 推理性能基准

```powershell
python Main.py benchmark "dataset/no/1 no.jpeg" --warm-runs 3 --json
```

基准命令使用临时输出目录，不创建任务、不写 SQLite，也不修改 `output/`。
输出包含：

- 分类和分割首次调用耗时
- 连续调用均值
- 最小值
- P95

比较不同设备或部署方式时，应使用相同图像、相同预热次数和相同模型权重。

## 常见现象

### 页面一直显示排队

先检查：

1. `GET /ops/queue` 是否存在活动 Worker。
2. Redis 是否可用。
3. Worker 是否监听 `.env` 中的 `BTIR_TASK_QUEUE_NAME`。
4. Worker 日志中是否收到对应 `task_id`。
5. 运行时间是否超过 `BTIR_TASK_STALE_AFTER_SECONDS`。

### 第一次推理明显更慢

通常是模型加载、CUDA 初始化或首次算子执行造成的冷启动。Windows 默认在
Worker 启动阶段预热；Linux 标准 Worker 默认不预热。具体模式参见
[安装与部署](DEPLOYMENT.md#worker-预热模式)。

### 列表能看到任务但详情不存在

普通任务列表已经默认排除归档记录。如果仍出现，应检查任务目录、SQLite
记录与 `BTIR_OUTPUT_DIR` 是否属于同一部署环境。
