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
- 3D 推理 Worker 注册状态
- 分类与分割模型文件

全部正常时返回 `200`；任一关键组件不可用时返回 `503`，并在
`detail.components.inference_worker` 等字段标出组件状态。

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
- `queues.3d`：提供队列名和上述指标

Redis 不可用时返回 `503`。

## Redis、RQ 与任务恢复

Redis 同时用于：

- RQ 异步任务队列
- 任务结果写回锁
- 同一用户活动任务配额的并发锁
- Worker 注册和队列状态

所有任务进入 `BTIR_TASK_QUEUE_NAME` 指定的 3D 推理队列。同一任务的去重、
取消、重试和状态对账规则保持不变。

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

从单用户版本升级后，原任务的 `user_id` 为空，默认不会向任何普通账号开放。
先注册接收账号，再由服务器操作者预览并确认认领：

```powershell
python Main.py claim-legacy-tasks <username>
python Main.py claim-legacy-tasks <username> --apply
```

认领只处理仍为空的归属，不会覆盖已经属于其他用户的任务。

## 任务目录

默认结构：

```text
output/
└── 20260715_120000_001/
    ├── input/
    │   ├── flair.nii.gz
    │   ├── t1.nii.gz
    │   ├── t1ce.nii.gz
    │   └── t2.nii.gz
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

批量归档与永久删除默认允许执行，但不会自动或定时运行：

```dotenv
BTIR_TASK_CLEANUP_ENABLED=true
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

如需在维护期间完全禁止批量归档与永久删除，可将开关设为 `false`。不带
`--apply` 的命令始终只做预览。

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

会立即将指定非活动任务移入同一归档区，审计操作记为 `archive_api`，并记录
发起操作的 `actor_user_id` 和任务所有者 `target_user_id`。管理员也可以使用
`DELETE /admin/users/{user_id}/tasks/{task_id}` 执行相同的安全删除；后端会先复核
任务归属。该接口
不受 `BTIR_TASK_CLEANUP_ENABLED` 开关限制，因为它来自用户明确操作；但后续
永久清除仍必须启用清理并执行 `purge-archive --apply`。

排队、运行或等待取消的任务不能软删除。应先取消并等待状态变为
`canceled`，再重新请求删除。

恢复尚未永久清除的任务：

```http
POST /tasks/{task_id}/restore
```

管理员恢复指定用户任务时使用：

```http
POST /admin/users/{user_id}/tasks/{task_id}/restore
```

恢复会将完整目录移回输出区、清除 `archived_at`、刷新 `updated_at` 并记录
带 `actor_user_id` 和 `target_user_id` 的 `restore_api` 审计。只要 purge 尚未实际执行，超过宽限日期的任务仍可恢复；
永久清除后文件和 SQLite 记录都不存在，无法恢复。

管理员可使用 `GET /admin/audit` 按操作、管理员、目标用户、任务和时间范围筛选
`audit.jsonl`，接口只返回结构化审计字段，不返回密码或任务文件内容。认证事件还会记录
操作结果和来源 IP。审计追加使用跨进程文件锁，锁文件为同目录下的 `audit.lock`。

### 自动永久清除建议

当前程序不会仅因到达 `purge_eligible_at` 就自行永久删除。生产环境建议由
Windows 任务计划程序或 Linux systemd timer/cron 在低峰期每天执行一次：

```powershell
python Main.py purge-archive --apply --limit 100
```

同时必须明确配置：

```dotenv
BTIR_TASK_CLEANUP_ENABLED=true
```

推荐按“每天固定时间扫描”而非让 API 进程精确等待每个任务的截止时刻：

- 服务停机后，下次定时运行会自动补处理已经到期的任务。
- 多个 API 进程不会重复创建删除定时器。
- 定时任务可独立停用，方便维护和数据恢复。
- `--limit` 可以限制单次永久删除数量。
- 每次清除仍经过归档时间复核、任务锁和审计。

例如每日 03:00 执行时，某任务到期后会在下一次 03:00 被永久删除。若团队
希望继续保留人工确认，则不要创建这个定时任务，维持手动预览与执行即可。

Linux `run-supervisor.sh` 只负责 API、Worker、健康检查和
`reconcile-tasks`，不会调用 `archive-tasks` 或 `purge-archive`，避免进程
守护与永久数据删除耦合。

## 手动清理

`clear` 是开发调试用的全量任务重置命令。执行前先停止 API 与 Worker，避免
运行中的作业在清理后重新写入结果，然后预览：

```powershell
python Main.py clear --dry-run
```

确认后执行：

```powershell
python Main.py clear
```

实际执行会删除：

- SQLite 中的全部用户账号；
- `BTIR_OUTPUT_DIR` 下的活动任务；
- `BTIR_TASK_ARCHIVE_DIR` 下的归档任务、待清除目录和归档审计；
- SQLite 中的全部任务记录；
- `BTIR_TASK_QUEUE_NAME` 对应的 RQ 队列、作业注册表、作业结果及
  `btir:task:*:write` 任务锁、`btir:user:*:quota` 用户配额锁；
- Python 与工具缓存。

清理后业务数据与首次启动前一致，需要重新注册账号；数据库表结构、`.env`、
模型权重以及 Redis 中其他应用的数据不会被删除。`clear` 不接受临时
`--output-dir`，只处理配置中明确指定的输出与归档目录。它与按保留期运行的
归档策略不同，也不会调用 Redis 的 `FLUSHALL` 或 `FLUSHDB`。

`--dry-run` 会显示活动 Worker 数量但不修改任何数据。实际执行要求 Redis 可用
且不存在活动推理 Worker，以避免运行中任务在清理后重新写回。

## 自动化测试

运行全量测试：

```powershell
python -m pip install -r requirements-dev.txt
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

## 3D 分割评估

```powershell
python Main.py evaluate-3d <BraTS数据集目录>
```

该命令按病例计算 WT、TC、ET Dice，并记录各病例耗时与 CUDA 峰值显存。
默认报告写入 `output/evaluations/segmentation3d-report.json`。比较不同设备或
模型版本时，应使用相同的病例集合、模型权重和运行配置。

## 常见现象

### 页面一直显示排队

先检查：

1. `GET /ops/queue` 是否存在活动 Worker。
2. Redis 是否可用。
3. 检查 Worker 是否监听 `.env` 中的 `BTIR_TASK_QUEUE_NAME`。
4. Worker 日志中是否收到对应 `task_id`。
5. 运行时间是否超过 `BTIR_TASK_STALE_AFTER_SECONDS`。

### 第一次推理明显更慢

通常是模型加载、CUDA 初始化或首次算子执行造成的冷启动。Windows 默认在
Worker 启动阶段预热；Linux 标准 Worker 默认不预热。具体模式参见
[安装与部署](DEPLOYMENT.md#worker-预热模式)。

### 列表能看到任务但详情不存在

普通任务列表已经默认排除归档记录。如果仍出现，应检查任务目录、SQLite
记录与 `BTIR_OUTPUT_DIR` 是否属于同一部署环境。
