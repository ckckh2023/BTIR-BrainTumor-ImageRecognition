# BTIR 安装与部署

本文说明 Windows 开发环境、Linux 服务器、Redis、GPU 后端、API 与 Worker 的启动方式<br>
所有命令默认在项目根目录执行

## 环境要求

- Python 3.11
- Git LFS
- Redis 7 或兼容版本
- Windows、Linux x86_64
- 可选：NVIDIA CUDA 或 Linux AMD ROCm

## 模型权重

`.pth` 和 `.safetensors` 模型权重由 Git LFS 管理<br>
首次克隆项目或模型加载异常时执行：

```bash
git lfs install
git lfs pull
git lfs status
```

确认以下文件是实际二进制权重，而不是 Git LFS 指针文本：

```text
models/classification/vit-binary/model.safetensors
models/segmentation3d/model/model_epoch_297.pth
```

3D 路线还依赖 `nibabel`、`einops`、`MONAI 1.3`、`transformers` 与
`safetensors`，均已写入 `requirements.txt`，不需要单独复制原模型的训练环境
默认 ViT 模型完整保存在 `models/classification/vit-binary/`，运行时强制离线
加载<br>
目录必须保留 `config.json`、`model.safetensors` 与
`preprocessor_config.json`；缺少任一文件时 3D 分类任务会重试一次，仍失败则返回
`failed`，不会切换到其他分类模型

## Windows 开发环境

建议使用独立的 Python 3.11 虚拟环境<br>
以下为 CMD 示例：

```cmd
cd /d X:\path\to\BTIR-BrainTumor-ImageRecognition
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python --version
python -m pip install -r requirements.txt
```

提示符显示 `(.venv)` 且 `python --version` 为 Python 3.11 后，再执行项目命令
虚拟环境也可以放在项目目录之外；激活后不要在脚本中写死其绝对路径

## Linux 服务器环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

基础依赖默认安装 NVIDIA CUDA 12.1 版 PyTorch<br>
CPU 或 Linux AMD ROCm 服务器
需在基础依赖安装后按“GPU 后端”一节显式切换<br>
生产环境建议使用独立系统目录
保存运行数据，例如 `/var/lib/btir/output`，不要将任务数据混入代码目录

## 配置文件

本地开发可以复制配置模板：

```powershell
Copy-Item .env.example .env
```

Linux：

```bash
cp .env.example .env
```

`.env.example` 提供常用配置、默认值和可选模型路径覆盖<br>
未列出的高级配置以 `.env.example` 为准<br>
部署时重点确认：

```dotenv
BTIR_DEVICE=auto
BTIR_OUTPUT_DIR=output
BTIR_REDIS_URL=redis://127.0.0.1:6379/0
BTIR_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
BTIR_TASK_DATABASE_PATH=data/btir.db
BTIR_TASK_QUEUE_NAME=inference-3d
BTIR_WORKER_PRELOAD_MODELS=true
BTIR_LINUX_WORKER_MODE=standard
BTIR_JWT_SECRET_KEY=至少32字节的随机字符串
BTIR_REGISTRATION_ENABLED=false
BTIR_AUTH_LOGIN_USER_ATTEMPTS=10
BTIR_AUTH_LOGIN_IP_ATTEMPTS=60
BTIR_AUTH_LOGIN_WINDOW_SECONDS=300
BTIR_AUTH_REGISTRATION_IP_ATTEMPTS=5
BTIR_AUTH_REGISTRATION_WINDOW_SECONDS=3600
BTIR_MAX_TASKS_PER_USER=1000
BTIR_MAX_ACTIVE_TASKS_PER_USER=2
BTIR_TASK_CANCEL_CHECK_INTERVAL_SECONDS=0.5
BTIR_MAX_3D_UPLOAD_BYTES=536870912
BTIR_MAX_3D_VOXELS=20000000
BTIR_3D_SEGMENTER_OVERLAP=0.5
BTIR_3D_FAST_INFERENCE=true
BTIR_VIT_CLASSIFIER_MODEL_DIR=models/classification/vit-binary
BTIR_VIT_CLASSIFIER_MAX_SLICES=25
BTIR_VIT_CLASSIFIER_BATCH_SIZE=25
BTIR_VIT_CLASSIFIER_THRESHOLD=0.5
BTIR_3D_CLASSIFIER_MODALITY=flair
BTIR_AI_ANALYSIS_ENABLED=false
BTIR_AI_API_KEY=仅部署环境设置，不提交到仓库
BTIR_AI_BASE_URL=https://api.deepseek.com
BTIR_AI_MODEL=deepseek-v4-flash
BTIR_AI_TIMEOUT_SECONDS=20
BTIR_AI_MAX_RETRIES=1
BTIR_AI_MAX_TOKENS=700
BTIR_AI_TEMPERATURE=0.2
```

可以生成 JWT 密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

API 缺少安全的 `BTIR_JWT_SECRET_KEY` 时会拒绝启动<br>
账号可以直接在服务器终端
创建，无需临时开放公开注册：

```bash
python Main.py user create <username>
python Main.py user create <username> --admin
python Main.py user list
python Main.py user set-role <username> admin
python Main.py user set-role <username> user
python Main.py user disable <username>
python Main.py user enable <username>
python Main.py user reset-password <username>
```

`--admin` 仅用于首次部署或明确授权的管理员账号；公开注册始终创建普通用户
用户名登录和唯一约束不区分字母大小写，但保留创建时的显示形式<br>
升级旧数据库时，
如果已有仅大小写不同的重复账号，数据库迁移会拒绝继续；应先备份并人工合并冲突账号
角色变更、禁用账号或重置密码会递增 Token 版本，使已经签发的旧 Token 立即
失效<br>
重置后的密码是临时密码，用户登录后必须通过 `/auth/change-password` 设置
自己的新密码才能操作任务<br>
登录和注册已有 Redis 应用层限流；生产环境仍建议在
反向代理层增加第二层频率限制

生产环境常见调整：

```dotenv
BTIR_OUTPUT_DIR=/var/lib/btir/output
BTIR_TASK_ARCHIVE_DIR=/var/lib/btir/archive
BTIR_CORS_ORIGINS=https://你的前端域名
```

路径相对于项目根目录解析<br>
前后端分离时，`BTIR_CORS_ORIGINS` 应明确列出
允许访问 API 的前端来源<br>
输出目录与归档目录必须位于同一磁盘卷，任务软删除
和定期归档才能通过完整目录移动保证一致性

### 可选 AI 综合分析

默认 `BTIR_AI_ANALYSIS_ENABLED=false`，因此不会产生任何外部请求<br>
启用后在
部署机器的 `.env` 中设置 `BTIR_AI_API_KEY`，密钥不得写入代码、前端或提交到仓库
服务只发送白名单字段：本地分类的类别/概率/阈值/切片摘要，以及分割区域的体素数、体积和
占比；不会发送原始 MRI、NIfTI、文件名、任务 ID、用户名或服务器路径
同一份白名单数据还会在本地生成以分割为主的 `model_consensus`，并作为外部综合说明的
确定性基线

AI 服务超时、限流、网络错误、空响应或不符合协议的 JSON 都会被记录为“综合分析暂不可用”，
不会影响本地分类和分割任务的成功状态<br>

`BTIR_3D_FAST_INFERENCE=true` 会为 CUDA 推理启用 cuDNN benchmark 与 TF32，以降低
滑窗分割耗时；默认启用<br>
需要对模型版本进行逐体素可复现比对时设为 `false`，并在报告中
记录所用模式<br>
CPU 推理不受该开关影响

## 启动 Redis

Windows 本地开发可通过 Docker Desktop 启动：

```cmd
docker run --name btir-redis -p 6379:6379 -d redis:7-alpine
docker ps
python -c "from redis import Redis; print(Redis.from_url('redis://127.0.0.1:6379/0').ping())"
```

最后一条命令输出 `True` 表示连接正常<br>
容器已经创建但未运行时：

```cmd
docker start btir-redis
```

Linux 可以使用系统 Redis、容器 Redis 或独立 Redis 服务，但连接地址必须与
`BTIR_REDIS_URL` 一致

## 开发环境启动

终端 1 启动 API：

```powershell
python -m uvicorn api.app:app --reload
```

终端 2 使用同一虚拟环境启动 3D Worker：

```powershell
python -m workers.run_worker
```

常用地址：

- 前端页面：<http://127.0.0.1:8000/web/>
- Swagger：<http://127.0.0.1:8000/docs>
- 运行设备：<http://127.0.0.1:8000/runtime>
- 就绪检查：<http://127.0.0.1:8000/readyz>

只查询已有的 SQLite 任务列表和运行历史时，不要求 Worker 正在运行；
上传后需要执行新的异步推理时，Redis 和 Worker 都必须可用

## 生产环境启动

生产 API 不使用 `--reload`：

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
```

使用受控进程启动 Worker：

```bash
python -m workers.run_worker
```

建议：

- 使用一个 API 进程和一个 3D Worker；需要增加吞吐时再根据显存实测扩容 Worker
- 多个 Worker 可能同时使用同一张 GPU，扩容前必须用实际模型验证合计显存
- 3D 四模态任务会占用更多显存与执行时间，任务超时应保留默认的 3600 秒
  或根据服务器实测调高
- 使用 Nginx 等反向代理提供 HTTPS
- 将 API、Worker 和守护脚本交给 systemd、任务计划程序或其他进程管理器
- 启动后检查 `/healthz`、`/readyz`、`/runtime` 和 `/ops/queue`

应用不会强制 HTTPS，`http://127.0.0.1:8000` 可继续用于本机测试<br>
只有服务正式
暴露到公网时才需要在 Nginx 等反向代理上终止 TLS<br>
认证限流按客户端 IP 统计；
Nginx 与 Uvicorn 位于同一服务器时，应仅信任本机代理传入的转发头，例如：

```bash
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1
```

## GPU 后端

`requirements.txt` 默认提供 NVIDIA CUDA 12.1 版 PyTorch<br>
安装基础依赖后，
也可以让项目自动选择适合当前机器的 PyTorch：

```powershell
python -m accelerator.install --backend auto
```

后端切换命令应当最后执行<br>
再次运行 `pip install -r requirements.txt` 会恢复
默认 CUDA 12.1 版 PyTorch；CPU 或 ROCm 环境需要重新执行对应的后端安装命令
安装器会同时保持项目锁定的 NumPy 与 Pillow 版本，避免重装 Torch 时升级公共
二进制依赖

先预览将执行的操作：

```powershell
python -m accelerator.install --backend auto --dry-run
```

明确指定后端：

```bash
# NVIDIA CUDA 12.1（团队服务器默认）
python -m accelerator.install --backend cuda

# Linux AMD ROCm
python -m accelerator.install --backend rocm

# CPU
python -m accelerator.install --backend cpu
```

说明：

- 默认 NVIDIA 后端为 CUDA 12.1；`auto` 检测到 `nvidia-smi` 时选择该后端
- AMD ROCm 仅支持 Linux；AMD Windows 使用 CPU
- `BTIR_DEVICE=auto` 会在已正确安装后端时自动选择 GPU
- 多张 GPU 可通过 `BTIR_DEVICE=cuda:0` 指定设备
- SuperLightNet 3D 路线支持 CPU 和 NVIDIA CUDA；CPU 可用于功能验证，
  正式体积推理建议使用 CUDA
- 3D 路线固定使用本地 ViT 对 FLAIR 轴向切片分类，并对全部切片概率取均值
  权重缺失、加载失败或推理异常时由 RQ 自动重试一次，仍失败则任务失败，不切换
  其他分类模型<br>
  分类成功后继续执行 3D 分割
- 当前实现采用 `128×128×128` 滑窗和可配置重叠率，已在 8 GB 显存的
  RTX 5070 Laptop GPU 上完成 `240×240×155` 体积验证，因此不要求把
  整个原始体积一次性放入显存<br>
  显存余量充足时窗口结果会直接在 GPU 汇总；
  余量不足或汇总发生 OOM 时自动回退到 CPU 汇总<br>
  实际耗时与显卡、重叠率和
  输入尺寸有关

验证 CUDA：

```cmd
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"
```

更换 PyTorch 后端后需重启 API 和 Worker，再通过 `/runtime` 核对实际
`backend`

## Worker 预热模式

Windows 使用单进程 `SimpleWorker`，默认在启动阶段预加载本地 ViT 与
SuperLightNet，把第一次任务的模型冷启动移到 Worker 启动阶段

Linux 默认使用标准 RQ Worker：

```dotenv
BTIR_LINUX_WORKER_MODE=standard
```

标准模式会跳过模型预加载，避免 fork 后 CUDA 初始化风险<br>
Linux GPU
服务器需要预热时可改为：

```dotenv
BTIR_LINUX_WORKER_MODE=simple
BTIR_WORKER_PRELOAD_MODELS=true
```

`simple` 不 fork，一次执行一个任务，应由 systemd 或项目守护脚本在进程
异常退出时重新拉起<br>
Worker 会复用自身的模型缓存；标准 Worker 每项作业使用
子进程，模型会在该作业中按需加载<br>
Worker 只监听 `BTIR_TASK_QUEUE_NAME`
指定的 3D 推理队列

Worker 名称包含主机名和进程号<br>
旧 Worker 异常退出后可以直接重新执行
启动命令；Redis 中短暂保留的旧注册不会阻止新 Worker 启动

## Linux 进程守护

`run-supervisor.sh` 是 Linux 的一键运行入口<br>
项目根目录已经存在
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

- Python 必须为 3.11
- FastAPI、Redis、RQ 和 Uvicorn 依赖可导入
- API 端口未被其他进程占用
- 同一项目没有另一个 supervisor 正在运行
- Redis 是否可访问；Redis 暂时不可用不会阻止 API 启动，supervisor 会持续
  重启退出的 Worker，直到 Redis 恢复

运行期间会：

- 同时启动并监控 API 与 3D Worker
- 进程退出后按退避时间重新启动
- 连续健康检查失败后重启 API
- Redis 正常但 Worker 未注册时，单独重启 Worker
- 默认每 60 秒执行 `reconcile-tasks`
- 将标准输出、错误和巡检结果写入 `logs/`
- 收到 `SIGINT` 或 `SIGTERM` 时先请求子进程正常退出，超过宽限期才强制停止

按 `Ctrl+C` 可以停止 supervisor、API 和 Worker<br>
该脚本不会执行任务归档或
永久删除

项目根目录的 `.env` 可以由系统环境变量替代，但 API 必须获得
`BTIR_JWT_SECRET_KEY`<br>
Python 应用会读取 `.env`，但进程中已经存在的系统环境
变量优先级更高<br>
supervisor 自身使用的
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
状态巡检<br>
存在 `flock` 时使用文件锁阻止重复启动，否则回退到 PID 检查

### 通过 systemd 托管

supervisor 能管理 API 和 Worker，但它自身仍应交给 systemd<br>
示例
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
EnvironmentFile=/etc/btir/btir.env
ExecStart=/bin/bash /opt/btir/scripts/run-supervisor.sh /opt/btir/.venv/bin/python
Restart=always
RestartSec=10
KillMode=control-group
TimeoutStopSec=330

[Install]
WantedBy=multi-user.target
```

服务器使用系统级配置时，可把所需 `BTIR_*` 变量写入
`/etc/btir/btir.env`；该文件至少应包含 `BTIR_JWT_SECRET_KEY`<br>
不要依赖交互式
shell 的 `.bashrc`，systemd 服务默认不会继承它

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

审计日志使用应用内按大小轮转和保留策略，配置项见 `.env.example` 中的 `BTIR_AUDIT_LOG_*`
生产环境仍应另外配置 logrotate，避免项目 `logs/` 持续增长<br>
永久清除使用独立
systemd timer 或 cron，不加入 supervisor 主循环

## 部署验证

1. Redis `ping()` 返回 `True`
2. `GET /healthz` 返回 `200`
3. `GET /readyz` 的 SQLite、Redis、Worker 和模型检查均为 `ok`
4. `GET /runtime` 显示预期的 CPU、CUDA 或 ROCm 后端
5. 通过页面拖入病例文件夹或 ZIP，或上传一组四模态 NIfTI；随后调用
   `POST /tasks/{task_id}/run-async`
6. 轮询任务直到 `succeeded`，确认分类与分割结果均存在
7. 有带 `seg` 标签的 BraTS 验证集时，执行
   `python Main.py evaluate-3d <数据集目录>`，记录 WT/TC/ET Dice、分类检测指标、
   耗时和峰值显存，作为模型升级前后的固定基线

运行时监控、归档和异常恢复参见 [运维说明](OPERATIONS.md)
