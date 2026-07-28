# BTIR 安装与部署

本文说明 Windows 开发环境、Linux 服务器、Redis、GPU 后端、API 与
Worker 的启动方式。所有命令默认在项目根目录执行。

## 环境要求

- Python 3.11
- Git LFS
- Redis 7 或兼容版本
- Windows、Linux x86_64
- 可选：NVIDIA CUDA 或 Linux AMD ROCm

## 模型权重

`.pth` 模型权重由 Git LFS 管理。首次克隆项目或模型加载异常时执行：

```bash
git lfs install
git lfs pull
git lfs status
```

确认以下文件是实际二进制权重，而不是 Git LFS 指针文本：

```text
models/classification/model/pytorch_model.pth
models/segmentation/model/best_unet_model.pth
```

## Windows 开发环境

建议使用独立的 Python 3.11 虚拟环境。以下为 CMD 示例：

```cmd
py -3.11 -m venv E:\btir311
E:\btir311\Scripts\activate.bat
cd /d E:\code-content\code-content\programme\BTIR-BrainTumor-ImageRecognition
python --version
python -m pip install -r requirements.txt
```

提示符显示 `(btir311)` 且 `python --version` 为 Python 3.11 后，再执行
项目命令。

## Linux 服务器环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

基础依赖默认安装 CPU 版 PyTorch。生产环境建议使用独立系统目录保存运行
数据，例如 `/var/lib/btir/output`，不要将任务数据混入代码目录。

## 配置文件

本地开发可以复制配置模板：

```powershell
Copy-Item .env.example .env
```

Linux：

```bash
cp .env.example .env
```

`.env.example` 是完整配置和默认值的权威来源。部署时重点确认：

```dotenv
BTIR_DEVICE=auto
BTIR_OUTPUT_DIR=output
BTIR_REDIS_URL=redis://127.0.0.1:6379/0
BTIR_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
BTIR_TASK_DATABASE_PATH=data/btir.db
BTIR_TASK_QUEUE_NAME=inference
BTIR_WORKER_PRELOAD_MODELS=true
BTIR_LINUX_WORKER_MODE=standard
```

生产环境常见调整：

```dotenv
BTIR_OUTPUT_DIR=/var/lib/btir/output
BTIR_TASK_ARCHIVE_DIR=/var/lib/btir/archive
BTIR_CORS_ORIGINS=https://你的前端域名
```

路径相对于项目根目录解析。前后端分离时，`BTIR_CORS_ORIGINS` 应明确列出
允许访问 API 的前端来源。输出目录与归档目录必须位于同一磁盘卷，任务软删除
和定期归档才能通过完整目录移动保证一致性。

## 启动 Redis

Windows 本地开发可通过 Docker Desktop 启动：

```cmd
docker run --name btir-redis -p 6379:6379 -d redis:7-alpine
docker ps
python -c "from redis import Redis; print(Redis.from_url('redis://127.0.0.1:6379/0').ping())"
```

最后一条命令输出 `True` 表示连接正常。容器已经创建但未运行时：

```cmd
docker start btir-redis
```

Linux 可以使用系统 Redis、容器 Redis 或独立 Redis 服务，但连接地址必须与
`BTIR_REDIS_URL` 一致。

## 开发环境启动

终端 1 启动 API：

```powershell
python -m uvicorn api.app:app --reload
```

终端 2 使用同一虚拟环境启动 Worker：

```powershell
python -m workers.run_worker
```

常用地址：

- 前端页面：<http://127.0.0.1:8000/web/>
- Swagger：<http://127.0.0.1:8000/docs>
- 运行设备：<http://127.0.0.1:8000/runtime>
- 就绪检查：<http://127.0.0.1:8000/readyz>

只查询已有的 SQLite 任务列表和运行历史时，不要求 Worker 正在运行；
上传后需要执行新的异步推理时，Redis 和 Worker 都必须可用。

## 生产环境启动

生产 API 不使用 `--reload`：

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
```

另一个受控进程启动 Worker：

```bash
python -m workers.run_worker
```

建议：

- 先使用一个 API 进程和一个推理 Worker 验证部署。
- 单张 GPU 默认只运行一个 Worker，避免并发模型推理争抢显存。
- 使用 Nginx 等反向代理提供 HTTPS。
- 将 API、Worker 和守护脚本交给 systemd、任务计划程序或其他进程管理器。
- 启动后检查 `/healthz`、`/readyz`、`/runtime` 和 `/ops/queue`。

## GPU 后端

安装基础依赖后，可以让项目自动选择适合当前机器的 PyTorch：

```powershell
python -m accelerator.install --backend auto
```

先预览将执行的操作：

```powershell
python -m accelerator.install --backend auto --dry-run
```

明确指定后端：

```bash
# NVIDIA CUDA
python -m accelerator.install --backend cuda

# Linux AMD ROCm
python -m accelerator.install --backend rocm

# CPU
python -m accelerator.install --backend cpu
```

说明：

- NVIDIA 自动选择项目支持的 CUDA 版本。
- AMD ROCm 仅支持 Linux；AMD Windows 使用 CPU。
- `BTIR_DEVICE=auto` 会在已正确安装后端时自动选择 GPU。
- 多张 GPU 可通过 `BTIR_DEVICE=cuda:0` 指定设备。

验证 CUDA：

```cmd
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"
```

更换 PyTorch 后端后需重启 API 和 Worker，再通过 `/runtime` 核对实际
`backend`。

## Worker 预热模式

Windows 使用单进程 `SimpleWorker`，默认在启动阶段预加载模型，把第一次
任务的模型冷启动移到 Worker 启动阶段。

Linux 默认使用标准 RQ Worker：

```dotenv
BTIR_LINUX_WORKER_MODE=standard
```

标准模式会跳过模型预加载，避免 fork 后 CUDA 初始化风险。Linux GPU
服务器需要预热时可改为：

```dotenv
BTIR_LINUX_WORKER_MODE=simple
BTIR_WORKER_PRELOAD_MODELS=true
```

`simple` 不 fork，一次执行一个任务，应由 systemd 或项目守护脚本在进程
异常退出时重新拉起。

Worker 名称包含主机名和进程号。旧 Worker 异常退出后可以直接重新执行
启动命令；Redis 中短暂保留的旧注册不会阻止新 Worker 启动。

## Windows 进程守护

启动前停止手动运行的 API 与 Worker，避免端口占用和重复注册：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-supervisor.ps1 -PythonExe E:\btir311\Scripts\python.exe
```

脚本会：

- 同时管理 API 与 Worker，进程退出时自动重启。
- 检查 `/healthz`、`/readyz` 和 `/ops/queue`。
- Redis 正常、Worker 未注册且没有运行中作业时重启 Worker。
- 默认每 60 秒运行一次 `reconcile-tasks`。

任务巡检周期可通过 `-TaskReconcileSeconds` 调整。日志写入：

```text
logs/supervisor.log
logs/api.stdout.log
logs/api.stderr.log
logs/worker.stdout.log
logs/worker.stderr.log
logs/reconcile.log
```

需要开机启动时，可将命令加入 Windows 任务计划程序，并配置失败后重启。

## Linux 进程守护

`run-supervisor.sh` 是 Linux 的一键运行入口。项目根目录已经存在
`.venv/bin/python` 时直接执行：

```bash
cd /opt/btir
bash scripts/run-supervisor.sh
```

也可以显式传入 Python：

```bash
bash scripts/run-supervisor.sh /opt/btir/.venv/bin/python
```

Python 查找顺序：

1. 命令参数
2. `BTIR_PYTHON_EXE`
3. 当前已激活的 `VIRTUAL_ENV`
4. 项目内 `.venv/bin/python`

启动前脚本会检查：

- Python 必须为 3.11。
- FastAPI、Redis、RQ 和 Uvicorn 依赖可导入。
- API 端口未被其他进程占用。
- 同一项目没有另一个 supervisor 正在运行。
- Redis 是否可访问；Redis 暂时不可用不会阻止 API 启动，supervisor 会持续
  重启退出的 Worker，直到 Redis 恢复。

运行期间会：

- 同时启动并监控 API 与 Worker。
- 进程退出后按退避时间重新启动。
- 连续健康检查失败后重启 API。
- Redis 正常、Worker 未注册且无运行中作业时安全重启 Worker。
- 默认每 60 秒执行 `reconcile-tasks`。
- 将标准输出、错误和巡检结果写入 `logs/`。
- 收到 `SIGINT` 或 `SIGTERM` 时先请求子进程正常退出，超过宽限期才强制停止。

按 `Ctrl+C` 可以停止 supervisor、API 和 Worker。该脚本不会执行任务归档或
永久删除。

项目根目录的 `.env` 是可选配置，不是启动必需文件。Python 应用会读取它，
但进程中已经存在的系统环境变量优先级更高。supervisor 自身使用的
`BTIR_API_*`、`BTIR_PYTHON_EXE` 和 `BTIR_SUPERVISOR_*` 不从 `.env` 读取，
必须在运行脚本前通过 shell 或 systemd 注入：

```bash
export BTIR_API_HOST=127.0.0.1
export BTIR_API_PORT=8000
export BTIR_SUPERVISOR_RESTART_DELAY_SECONDS=10
export BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS=15
export BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS=120
export BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS=60
export BTIR_SUPERVISOR_RECONCILE_TIMEOUT_SECONDS=120
export BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS=300
export BTIR_SUPERVISOR_API_FAILURE_THRESHOLD=3
bash scripts/run-supervisor.sh
```

存在 `curl` 时执行 HTTP 健康检查；没有 `curl` 时仍保留进程退出重启和任务
状态巡检。存在 `flock` 时使用文件锁阻止重复启动，否则回退到 PID 检查。

### 通过 systemd 托管

supervisor 能管理 API 和 Worker，但它自身仍应交给 systemd。示例
`/etc/systemd/system/btir.service`：

```ini
[Unit]
Description=BTIR API and inference worker
After=network.target redis.service
Wants=redis.service

[Service]
Type=simple
User=btir
WorkingDirectory=/opt/btir
EnvironmentFile=-/etc/btir/btir.env
ExecStart=/bin/bash /opt/btir/scripts/run-supervisor.sh /opt/btir/.venv/bin/python
Restart=always
RestartSec=10
KillMode=control-group
TimeoutStopSec=330

[Install]
WantedBy=multi-user.target
```

`EnvironmentFile` 行开头的 `-` 表示配置文件不存在时仍允许服务启动。服务器
使用系统级配置时，可把所需 `BTIR_*` 变量写入 `/etc/btir/btir.env`；不要依赖
交互式 shell 的 `.bashrc`，systemd 服务默认不会继承它。

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now btir
sudo systemctl status btir
```

查看日志：

```bash
journalctl -u btir -f
tail -f /opt/btir/logs/supervisor.log
```

生产环境应另外配置 logrotate，避免项目 `logs/` 持续增长。永久清除使用独立
systemd timer 或 cron，不加入 supervisor 主循环。

## 部署验证

1. Redis `ping()` 返回 `True`。
2. `GET /healthz` 返回 `200`。
3. `GET /readyz` 的 SQLite、Redis、Worker 和模型检查均为 `ok`。
4. `GET /runtime` 显示预期的 CPU、CUDA 或 ROCm 后端。
5. 上传测试图片，调用 `POST /tasks/{task_id}/run-async`。
6. 轮询任务直到 `succeeded`，确认分类与分割结果均存在。

运行时监控、归档和异常恢复参见 [运维说明](OPERATIONS.md)。
