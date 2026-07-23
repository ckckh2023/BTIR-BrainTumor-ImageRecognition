# 脑肿瘤 MRI 图像分析后端

本项目提供脑肿瘤 MRI 图像的分类与分割后端能力；  
每次分析以一个独立任务`task_id`为单位：  
任务保存输入图像、模型运行记录、操作痕迹、统一结果 JSON 和错误信息  
> 前端通过任务 ID 调用接口即可

## 当前进度
| 模块 | 状态 | 描述 |
| --- | --- | --- |
| 模型推理 | √ | 分类模型、分割模型均可独立调用 |
| 数据处理 | √ | 已抽出统一预处理、后处理和模型调用入口；归一化、裁剪、数据增强等策略仍待按模型与数据集补充 |
| 任务管理 | √ | 按时间戳创建独立任务目录；支持上传或本机路径创建任务 |
| 结果管理 | √ | 保存当前模型结果、历史运行结果、统一前端结果和错误文件 |
| REST API | √ | 已提供上传建任务、单模型调用、一键运行全部模型、查询任务状态等接口 |
| 接口协议 | x | 当前已有请求/响应模型；待前端开始后共同确定最终 JSON 字段与错误格式 |
| 异步调度 | √ | 使用 Redis 与 RQ 执行后台推理；支持失败自动重试、任务列表查询，以及安全取消 `queued`/`running` 任务 |
| 数据库 | √ | SQLite 保存任务元数据与状态；图像、掩码和前端结果继续保存在文件系统 |

## 开始

### 拉取模型权重

项目中的 `.pth` 模型权重由 Git LFS 管理。首次克隆项目或模型加载报错时，先执行：

```bash
git lfs install
git lfs pull
git lfs status
```

确认以下模型文件不是 Git LFS 指针文本，而是实际二进制权重文件：
models/classification/model/pytorch_model.pth  
models/segmentation/model/best_unet_model.pth  

统一用 Python 3.11 创建并启用虚拟环境后，安装依赖：

```powershell
python -m pip install -r requirements.txt
```

### 本机配置

默认配置可直接运行 如需修改输出目录、模型位置、推理设备或前端跨域地址，复制模板：

```powershell
Copy-Item .env.example .env
```

`requirements.txt` 默认安装 CPU 版 PyTorch，所有成员都可运行

### Linux 服务器部署

以下命令适用于已安装 Python 3.11 的 x86_64 Linux 服务器  
在项目根目录执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

默认依赖为 CPU 版 PyTorch
若服务器使用 GPU，在安装基础依赖后，按显卡类型替换为对应的 PyTorch 后端：

```bash
# NVIDIA CUDA 服务器
python -m accelerator.install --backend cuda

# AMD ROCm 服务器
python -m accelerator.install --backend rocm
```

编辑 `.env` 时，生产环境通常至少需要确认以下配置：

```dotenv
BTIR_DEVICE=auto
BTIR_OUTPUT_DIR=/var/lib/btir/output
BTIR_CORS_ORIGINS=https://你的前端域名
```

启动生产服务时不要使用 `--reload`，并建议先只启动一个工作进程；多个工作进程会分别加载一份模型，占用更多内存或显存：

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
```

建议通过 Nginx 等反向代理对外提供 HTTPS 服务

### Windows 临时虚拟环境

Windows 开发请确认使用 Python 3.11 虚拟环境，而不是系统 Python  
以下为 CMD 示例：

```cmd
py -3.11 -m venv E:\btir311
E:\btir311\Scripts\activate.bat
cd /d E:\code-content\code-content\programme\BTIR-BrainTumor-ImageRecognition
python --version
python -m pip install -r requirements.txt
```

提示符显示 `(btir311)` 且 `python --version` 为 Python 3.11 后，再执行项目命令  

### Redis 任务写入锁

任务结果写入时会使用 Redis 锁保护 SQLite 任务元数据与 `frontend_result.json` 等共享结果，避免分类、分割或后续异步任务同时写回时互相覆盖  
SQLite 任务元数据通过事务写入；结果 JSON 文件采用原子写入，读取方只会看到完整的旧文件或完整的新文件

Redis 是独立服务，本地 Windows 开发可使用 Docker Desktop 启动 Redis：

```cmd
docker run --name btir-redis -p 6379:6379 -d redis:7-alpine
docker ps
python -c "from redis import Redis; print(Redis.from_url('redis://127.0.0.1:6379/0').ping())"
```

最后一条命令输出 `True` 表示 Python 可以连接 Redis  
若容器已创建但未运行，使用 `docker start btir-redis`。

`.env` 中的相关配置如下：

```dotenv
BTIR_REDIS_URL=redis://127.0.0.1:6379/0
BTIR_TASK_LOCK_TIMEOUT_SECONDS=30
BTIR_TASK_LOCK_WAIT_SECONDS=5
BTIR_TASK_QUEUE_NAME=inference
BTIR_TASK_JOB_TIMEOUT_SECONDS=3600
BTIR_TASK_JOB_RESULT_TTL_SECONDS=86400
BTIR_TASK_JOB_MAX_RETRIES=1
BTIR_TASK_STALE_AFTER_SECONDS=3660
BTIR_TASK_RECONCILE_BATCH_SIZE=100
BTIR_WORKER_PRELOAD_MODELS=true
BTIR_TASK_DATABASE_PATH=data/btir.db
BTIR_MAX_UPLOAD_BYTES=20971520
BTIR_MAX_IMAGE_PIXELS=40000000
```

`POST /tasks` 会在落盘时限制上传文件大小，并在图片解码前检查像素数量；默认分别为 20 MiB 和 4,000 万像素。可按部署资源通过上述环境变量调整。

`GET /runtime` 会返回 `task_database_backend` 与 `task_database_available`，用于确认任务数据库是否可用  
任务目录存在但数据库没有对应元数据时，接口返回 HTTP `404`；SQLite 不可用时返回 HTTP `503`

RQ 队列负责运行后台推理任务；同一任务已有 `queued` 或 `running` 作业时，重复提交会复用原作业，不会重复入队。默认首次失败后会立即自动重试一次；第二次失败才标记为 `failed`  
查询任务时会与 RQ 作业状态对账，`running` 超过 `BTIR_TASK_STALE_AFTER_SECONDS` 仍未结束时也会标记为 `failed`  
`reconcile-tasks` 会批量执行同一套对账逻辑，使异常重启后的状态不必等待用户查询即可收敛

启动 API 后，另开一个已启用相同虚拟环境的终端启动 worker：

```cmd
python -m workers.run_worker
```

### SQLite 任务元数据

任务 ID、状态、RQ 作业信息和运行记录保存在 `data/btir.db`。首次启动时会自动创建该文件，无需手动安装数据库服务

Windows 本地开发会自动使用单进程 `SimpleWorker`，默认会在启动阶段预加载模型，因此首次任务不会再承担模型冷启动  
Linux 服务器使用标准 RQ worker；为避免 fork 后 CUDA 初始化风险，默认不预加载，仍由任务进程按需加载
两种模式均一次执行一个推理任务，适合单张 GPU，避免并发模型推理抢占显存

Worker 名称会自动包含主机名和进程号  
即使旧 Worker 异常退出、Redis 尚未清理旧记录，也可以直接重新执行启动命令  

### GPU 加速安装

基础依赖安装完成后，使用内置安装器为当前机器替换对应的 PyTorch 后端：

```powershell
python -m accelerator.install --backend auto
```

可以先确认安装器将执行什么，而不修改环境：

```powershell
python -m accelerator.install --backend auto --dry-run
```

- NVIDIA 显卡：自动选择 CUDA 12.8；也可指定 `--backend cuda`
- AMD 显卡：仅 Linux ROCm 服务器可用，指定 `--backend rocm`
- 无兼容 GPU 或 AMD Windows：选择 CPU。

保持 `.env` 中的 `BTIR_DEVICE=auto`
若服务器有多张 NVIDIA 或 AMD 显卡，指定第一张可写为 `BTIR_DEVICE=cuda:0`

项目内的 `accelerator/` 包统一识别 CPU、NVIDIA CUDA 与 AMD ROCm。安装对应平台的 PyTorch 后，`BTIR_DEVICE=auto` 会自动选择实际可用的后端

安装 CUDA 后，可用以下命令确认当前虚拟环境是否真的识别到 GPU：

```cmd
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"
```

若 `torch.cuda.is_available()` 为 `False`，说明当前环境仍是 CPU 版 PyTorch，或 NVIDIA 驱动与 CUDA 环境不可用  
更换 PyTorch 后需重启 Uvicorn，再访问 `/runtime` 确认 `backend` 为 `cuda`。

### 启动服务

```powershell
python -m uvicorn api.app:app --reload
```

打开接口文档：<http://127.0.0.1:8000/docs>

打开前端页面：<http://127.0.0.1:8000/web/>

查看当前后端实际使用的设备：<http://127.0.0.1:8000/runtime>

推荐先用 Swagger 页面完成联调和接口测试
> 除API调用 也可通过命令行框进行测试，但更推荐api测试  
> [点此命令行使用说明](#命令行运行方式开发调试用)   

### 完整联调流程

1. 确认 Redis 容器运行，且 Redis `ping()` 输出 `True`  
2. 启动 API 后，调用 `GET /runtime`，确认当前 CPU/GPU 后端  
3. 在 Swagger 的 `POST /tasks` 上传一张 `.jpg`、`.jpeg` 或 `.png` 图片，保存响应中的 `task_id`  
4. 另开终端执行 `python -m workers.run_worker`，再调用 `POST /tasks/{task_id}/run-async`  
接口会立即返回 HTTP `202`、`job.id` 和 `queued` 状态；请求体可使用：

   ```json
   {"threshold": 0.5}
   ```

5. 轮询 `GET /tasks/{task_id}`；状态应依次为 `queued`、`running`、`succeeded`  
成功时 `completed_models` 应同时包含 `classification` 与 `segmentation`  
6. 调用 `GET /tasks/{task_id}/files/frontend_result.json`，确认前端结果文件可读取  


### 任务归档与永久删除

归档策略由 `.env` 控制，默认关闭实际执行：

```dotenv
BTIR_TASK_CLEANUP_ENABLED=false
BTIR_SUCCEEDED_TASK_RETENTION_DAYS=30
BTIR_FAILED_TASK_RETENTION_DAYS=7
BTIR_TASK_ARCHIVE_GRACE_DAYS=7
BTIR_TASK_ARCHIVE_DIR=archive
```

归档与永久删除命令默认只预览候选任务，不会移动或删除任何文件：

```cmd
python Main.py archive-tasks
python Main.py purge-archive
python Main.py reconcile-tasks
```

实际执行需要同时设置 `BTIR_TASK_CLEANUP_ENABLED=true` 和显式传入 `--apply`：

```cmd
python Main.py archive-tasks --apply
python Main.py purge-archive --apply
```

归档只处理超过保留期的 `succeeded`、旧版 `completed` 与 `failed` 任务，且会在执行前再次确认任务不是活动状态  
任务会先整体移动至 `archive/tasks/`，保留 `BTIR_TASK_ARCHIVE_GRACE_DAYS` 后才可能由 `purge-archive --apply` 永久删除  
每项实际操作记录在 `archive/audit.jsonl`；模型、Python 缓存和活动任务不会被该流程触碰。

### 自动化测试

不依赖模型、GPU、Redis 或已有任务数据的基础测试可直接执行：

```cmd
python -m unittest discover -s tests -v
```

Redis 可用时，测试会额外运行真实 RQ `SimpleWorker` 的入队、执行和一次失败重试集成测试；Redis 不可用时该组测试会自动跳过

### 推理性能基准

以下命令只使用临时输出目录，不创建任务、不写 SQLite，也不修改 `output/`：

```cmd
python Main.py benchmark "dataset/no/1 no.jpeg" --warm-runs 3 --json
```

输出分别包含分类和分割模型在当前 Python 进程的首次调用耗时，以及连续调用的均值、最小值和 P95 耗时

## API 使用流程

### 服务健康检查

- `GET /healthz`：仅确认 API 进程存活，不访问外部依赖。
- `GET /readyz`：同时检查 SQLite、Redis、推理 worker 注册状态和模型文件；任一不可用时返回 HTTP `503`。
- `GET /ops/queue`：读取推理队列的 worker 数、排队数、运行数、失败数和最早排队等待时间；Redis 不可用时返回 HTTP `503`。

### Windows 进程守护

`scripts/run-supervisor.ps1` 会同时启动 API 与推理 worker；任一进程意外退出时自动重启  
它定期检查 `/healthz`、`/readyz` 和 `/ops/queue`：API 连续健康检查失败时重启 API；仅在 Redis 正常、worker 未注册且没有正在运行的作业时才重启 worker  
每 60 秒还会运行一次 `reconcile-tasks`，自动修复活动任务状态；可通过 `-TaskReconcileSeconds` 调整  
Redis 短暂断连由 RQ worker 自身的退避重连处理

启动前先停止手动运行的 API 与 worker，避免端口或 Redis worker 重复注册：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-supervisor.ps1 -PythonExe E:\btir311\Scripts\python.exe
```

日志写入 `logs/supervisor.log`、`logs/api.stdout.log`、`logs/api.stderr.log`、`logs/worker.stdout.log`、`logs/worker.stderr.log` 和 `logs/reconcile.log`
需要开机自动运行时，可将这条命令配置为 Windows 任务计划程序的启动操作，并设置“失败后重启任务”

### Linux 进程守护

Linux 使用同职责的 Bash 脚本；传入虚拟环境中的 Python 路径：

```bash
bash scripts/run-supervisor.sh /opt/btir/.venv/bin/python
```

脚本需要 `curl` 才能执行 HTTP 健康检查；没有 `curl` 时仍会在 API 或 worker 进程退出后自动重启  
它默认每 60 秒运行一次任务巡检，可通过环境变量 `BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS` 调整  
生产环境可将该命令作为 systemd 服务的启动命令，由 systemd 在守护脚本本身退出时重新拉起

### 1. 上传图片并创建任务

`POST /tasks`

请求类型为 `multipart/form-data`：

- `file`：必填，目前支持 `.jpg`、`.jpeg`、`.png`
- `name`：可选，任务显示名称

> 成功后返回 `task_id`。之后的模型接口都传入这个 ID，不需要重复上传图片

### 2. 调用模型

正常分析流程建议使用一键运行接口：

```text
POST /tasks/{task_id}/run-async
```

该接口会依次执行分类和分割，并将两项结果合并至同一份 `frontend_result.json`请求体可省略；省略时分割阈值默认是 `0.5`  
如需指定阈值：

```json
{
  "threshold": 0.5
}
```

### 3. 查询任务结果

```text
GET /tasks/{task_id}
```

返回任务状态、已完成模型列表和当前统一结果
任务完成后，`completed_models` 应包含：

```json
["classification", "segmentation"]
```

失败任务会返回可展示的 `error.code`、`error.message` 与作业 `attempt`、`max_retries`；内部异常详情不会经 API 返回

### 4. 重试、取消任务与任务列表

自动重试耗尽后，可使用下列接口为失败任务提交一个新的作业：

```text
POST /tasks/{task_id}/retry
```

请求体可省略，也可传入新的分割阈值  
仅 `failed` 任务可手动重试；重复请求正在排队或运行的重试任务时，会复用同一作业

取消异步任务使用：

```text
POST /tasks/{task_id}/cancel
```

`created` 或尚未执行的作业会立即变为 `canceled`  
对运行中的作业，接口先返回 `cancel_requested`；worker 会在分类完成、分割开始前停止  
若分割已经开始，本次推理会安全完成，避免强制终止造成结果文件不完整。重复取消已取消任务是幂等的；已完成或已失败任务会返回 `409 Conflict`

分页查询任务使用：

```text
GET /tasks?limit=20&offset=0&status=failed
```

`status` 可省略；`limit` 范围为 1 到 100。响应中的 `items` 只包含任务摘要，不包含完整推理结果

## 任务目录

每次创建任务均在 `output/` 下创建时间戳目录：

```text
output/
└── 20260715_120000_001/       # task_id
    ├── input/
    │   └── image.jpg           # 上传或复制后的输入图像
    ├── classification.json      # 最新分类模型结果
    ├── segmentation.json        # 最新分割模型结果
    ├── runs/                   # 模型调用的历史结果
    ├── frontend_result.json    # 供前端读取的统一结果
    └── error.json              # 调用失败时的错误记录（如存在）

data/
└── btir.db                     # 本机 SQLite 任务元数据（不提交）
```

同一模型在同一任务内重复运行时：

- `runs/<model>/` 追加一次新的历史运行记录；
- 当前模型结果与 `frontend_result.json` 更新为最新结果；
> 不会创建新的任务，也不会覆盖历史运行目录

## 代码结构

```text
api/app.py                    # FastAPI 应用组装、CORS、静态前端
api/routes/tasks.py           # 任务创建、推理、结果文件接口
api/routes/runtime.py         # 运行环境状态接口
contracts/task.py             # API 请求/响应数据模型
repositories/task_repository.py # 任务仓储契约与默认实例
repositories/sqlite_task_repository.py # SQLite 任务仓储实现
core/task_records.py          # SQLite 持久化任务记录的 Pydantic 模型
services/task_files.py        # 任务目录、输入图像和原子 JSON 写入
services/task_results.py      # 模型结果、历史结果和前端结果的持久化
services/task_runner.py       # 分类、分割和完整推理的统一编排
services/task_state.py        # 任务状态、RQ 作业状态和运行记录
services/task_lock.py         # Redis 任务结果写入锁
services/redis_client.py      # Redis 客户端唯一创建入口
services/task_queue.py        # RQ 作业提交与队列连接
services/archive_service.py   # 任务归档与归档区永久删除
services/inference_service.py # 分类/分割模型的统一调用入口
services/cleanup_service.py   # 清理生成的缓存与结果
services/presentation.py      # CLI 输出格式化
accelerator/                  # CPU / CUDA / ROCm 设备适配包
processing/                   # 通用预处理、后处理
models/                       # 各模型的推理实现
workers/inference_jobs.py     # RQ 后台推理作业
workers/run_worker.py         # 启动 RQ worker
tests/                        # 不依赖模型、GPU、Redis 的回归测试
Main.py                       # 命令行入口
output/                       # 运行生成的数据
```

## 命令行运行方式（开发调试用）

```powershell
python Main.py help
python Main.py create <image_path> --name demo
python Main.py classify --task-id <task_id>
python Main.py segment --task-id <task_id>
python Main.py all <image_path>
python Main.py clear --dry-run
python Main.py clear --output-dir D:\btir-output --dry-run
python Main.py archive-tasks
python Main.py purge-archive
python Main.py game
```

### 彩蛋（扫瘤）

在项目根目录、交互式终端中执行：

```powershell
python Main.py game
```

> 内容是什么你猜猜~

## 协定

1. 不直接读取或修改其他任务目录；所有模型调用均通过 `task_id` 定位任务
2. 新增模型时，在 `services/inference_service.py` 提供统一入口，并通过 `persist_model_result()` 写入结果，避免自行拼接 JSON
3. 修改前端字段前，先同步修改 `contracts/task.py`、`api/routes/tasks.py` 和本 README 的接口说明；任务持久化字段同时检查 `core/task_records.py`
4. `output/`、`data/*.db*`、模型权重、缓存和本地数据集属于本地产物，避免提交到版本库

## 下一阶段

1. 确认 `frontend_result.json` 的字段与错误格式
