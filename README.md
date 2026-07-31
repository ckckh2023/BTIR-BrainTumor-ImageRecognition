# 脑肿瘤 MRI 图像分析

BTIR 提供脑肿瘤 MRI 图像分类与分割能力。每次分析以独立
`task_id` 为单位，保存输入图像、异步作业状态、模型运行历史、统一结果和错误信息；

## 当前能力

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 模型推理 | 已完成 | 2D 图片执行分类与分割；3D 四模态 NIfTI 执行实验性切片集成分类与 SuperLightNet 分割 |
| 任务管理 | 已完成 | 上传创建任务、异步运行、重试、取消、软删除、恢复、状态查询 |
| 历史查询 | 已完成 | 支持任务筛选、分页和单任务运行历史 |
| 异步调度 | 已完成 | Redis + RQ，自动重试、状态对账和安全取消 |
| 数据持久化 | 已完成 | SQLite 保存元数据，文件系统保存图像与完整结果 |
| 运行安全 | 已完成 | Redis 写入锁、SQLite 事务、JSON 原子写入 |
| CPU/GPU | 已完成 | CPU、NVIDIA CUDA、Linux AMD ROCm |
| 接口协议 | 核心流程已完成 | 2D/3D 上传、异步运行和结果展示已对接；高级任务操作界面待补充 |
| 多用户 | 基础能力已完成 | JWT 登录、任务隔离和用户任务配额已完成；管理员查询待补充 |

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [API 对接说明](docs/API.md) | 所有接口、参数、响应、错误和前端调用示例 |
| [安装与部署](docs/DEPLOYMENT.md) | Windows 开发、Linux 部署、Redis、GPU、Worker 与进程守护 |
| [运维与数据管理](docs/OPERATIONS.md) | 健康检查、队列、SQLite、归档、清理、测试和基准 |

接口启动后还可以访问 Swagger：<http://127.0.0.1:8000/docs>

## 快速开始

### 1. 获取模型权重

模型权重由 Git LFS 管理：

```bash
git lfs install
git lfs pull
git lfs status
```

确认以下文件是实际模型权重，不是 Git LFS 指针：

```text
models/classification/model/pytorch_model.pth
models/segmentation/model/best_unet_model.pth
models/segmentation3d/model/model_epoch_297.pth
```

### 2. 准备 Python 3.11 环境

启用 Python 3.11 虚拟环境后：

```powershell
python --version
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`requirements.txt` 默认安装 CPU 版 PyTorch。需要运行测试时改用
`python -m pip install -r requirements-dev.txt`。GPU 安装必须在基础依赖之后
执行，完整顺序参见[安装与部署](docs/DEPLOYMENT.md)。
把最后一条命令生成的随机值写入 `.env` 的 `BTIR_JWT_SECRET_KEY`。首次创建账号时
临时设置 `BTIR_REGISTRATION_ENABLED=true`，账号创建完成后建议改回 `false` 并重启 API。

### 3. 启动 Redis

本地 Windows 可以使用 Docker Desktop：

```powershell
docker run --name btir-redis -p 6379:6379 -d redis:7-alpine
python -c "from redis import Redis; print(Redis.from_url('redis://127.0.0.1:6379/0').ping())"
```

容器已经创建时：

```powershell
docker start btir-redis
```

连接测试输出 `True` 后继续。

### 4. 启动 API 和 Worker

终端 1：

```powershell
python -m uvicorn api.app:app --reload
```

终端 2：

```powershell
python -m workers.run_worker
```

Linux 已准备好项目内 `.venv` 时，也可以一条命令同时托管 API 与 Worker。
该脚本不会启动 Docker 或 Redis；若 Redis 运行在 Docker 中，请先启动 Docker 和 Redis 容器：

```bash
bash scripts/run-supervisor.sh
```

若依赖安装在服务器的全局 Python 3.11 中，也可以直接指定解释器，不要求创建
项目 `.venv`：

```bash
bash scripts/run-supervisor.sh /usr/bin/python3.11
```

项目根目录的 `.env` 可以由系统环境变量替代，但 API 必须获得安全的
`BTIR_JWT_SECRET_KEY`，否则会拒绝启动。Linux 中已经导出的 `BTIR_*` 环境变量
优先于 `.env` 中的同名配置。通过 systemd 启动时不要依赖用户 shell 配置，应在
service 中使用 `Environment=` 或 `EnvironmentFile=` 注入，
具体示例参见[安装与部署](docs/DEPLOYMENT.md)。

打开：

- 前端页面：<http://127.0.0.1:8000/web/>
- Swagger：<http://127.0.0.1:8000/docs>
- 运行设备：<http://127.0.0.1:8000/runtime>
- 完整就绪状态：<http://127.0.0.1:8000/readyz>

只查询 SQLite 中已有任务时不要求 Worker 正在运行；创建新的推理结果需要 Redis 和 Worker。

## 最短联调流程

1. 调用 `POST /auth/register` 创建账号，或通过 `POST /auth/login` 登录。
2. 后续任务请求携带 `Authorization: Bearer <access_token>`。
3. 选择输入路线并保存返回的 `task_id`：

   - 2D：`POST /tasks` 上传 `.jpg`、`.jpeg` 或 `.png`。
   - 3D：`POST /tasks/3d` 同时上传 `flair`、`t1ce`、`t1`、`t2`
     四个 `.nii` 或 `.nii.gz` 文件。

4. `POST /tasks/{task_id}/run-async` 提交任务。2D 任务执行单图分类与分割；
   3D 任务先执行实验性 2D 切片集成分类，再执行 SuperLightNet 分割。当前
   分类结果不会跳过分割。
5. 轮询 `GET /tasks/{task_id}`，直到状态变为 `succeeded`。
6. 历史和归档接口只返回当前用户自己的任务。

从旧版本升级后，历史任务默认不属于任何用户，也不会被普通账号访问。服务器
操作者确认接收账号后执行：

```powershell
python Main.py claim-legacy-tasks <username>
python Main.py claim-legacy-tasks <username> --apply
```

第一条仅预览，第二条才会写入归属关系。

完整请求、响应和前端 `fetch` 示例参见 [API 对接说明](docs/API.md)。

## 自动化测试

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

测试使用临时任务目录，不读取或修改已有任务数据。Redis 可用时会运行真实 RQ 集成测试；Redis 不可用时对应集成用例按原有规则跳过。

## 数据存储

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

- SQLite 保存任务元数据、状态、作业信息和运行记录。
- 文件系统保存输入图像、掩码和完整结果。
- 同一模型重复运行时追加 `runs/<model>/` 历史，并更新最新结果。
- `output/`、`data/*.db*`、模型权重、缓存和本地数据集不提交到版本库。

归档、永久删除和数据库迁移规则参见
[运维与数据管理](docs/OPERATIONS.md)。

## 项目结构

```text
api/             # FastAPI 应用与路由
contracts/       # API 请求和响应模型
core/            # 配置、任务状态和持久化记录
repositories/    # 任务仓储契约与 SQLite 实现
services/        # 任务、推理、队列、锁、归档等业务逻辑
workers/         # RQ 推理作业与 Worker 入口
accelerator/     # CPU、CUDA、ROCm 适配与安装
processing/      # 通用预处理和后处理
models/          # 分类、分割模型实现与权重
frontend/        # 随 API 托管的前端文件
scripts/         # Linux 进程守护
tests/           # 自动化测试
Main.py          # 开发调试命令入口
```

后端主要分层：

```text
API 路由 → 服务层 → 仓储契约 → SQLite
                 ↘ Redis / RQ Worker
```

## 开发调试命令

查看完整帮助：

```powershell
python Main.py help
```

常用命令：

```powershell
python Main.py create <image_path> --name demo
python Main.py classify --task-id <task_id>
python Main.py segment --task-id <task_id>
python Main.py all --task-id <task_id>
python Main.py benchmark <image_path> --warm-runs 3 --json
python Main.py evaluate-3d <BraTS数据集目录>
python Main.py reconcile-tasks
python Main.py clear --dry-run
python Main.py archive-tasks
python Main.py purge-archive
```

命令行模型调用仅用于开发调试；正式前端流程使用异步 API。
`evaluate-3d` 会发现数据集根目录下包含四模态和 `*_seg.nii[.gz]` 的病例，
逐例计算 BraTS WT、TC、ET Dice，同时记录耗时和 CUDA 峰值显存。默认报告写入
`output/evaluations/segmentation3d-report.json`，不保留大型预测掩码；需要人工
复核时可增加 `--predictions-dir <目录>`。

前端统一结果 `frontend_result.json` 使用独立的 `schema_version: "1.0"`。
分类和分割对象都保留稳定的 `model` 标识；更换模型实现时不得改变既有字段语义，
需要新增字段时保持向后兼容。完整字段见 [API 对接说明](docs/API.md)。

`clear` 是开发环境全量重置命令：实际执行会清空用户账号、活动任务、归档、
归档审计、全部任务记录、BTIR 推理队列/作业/任务锁和 Python 缓存，使业务数据
回到首次启动前的空白状态；`.env`、模型权重和其他 Redis 应用的数据仍会保留。
执行前必须先停止 API 和 Worker，并先使用 `--dry-run` 检查目标。Redis 不可用
或仍存在活动 Worker 时，实际清理会拒绝执行。

## 开发约定

1. 前端和外部服务只通过 API 使用任务，不直接访问 SQLite 或任务目录。
2. 新增模型时，在 `services/inference_service.py` 提供统一入口，并通过 `persist_model_result()` 写入结果。
3. 修改公开字段时，同步检查 `contracts/task.py`、API 路由和
 [API 对接说明](docs/API.md)。
4. 修改持久化字段时同步检查 `core/task_records.py` 和 SQLite migration。
5. 清理和归档先使用预览模式；`clear` 只操作 BTIR 队列、作业和任务锁，禁止
   用 `FLUSHALL` 或 `FLUSHDB` 代替项目清理命令。

## 下一阶段

1. 补充前端自动化测试，并完善任务取消、再次运行和运行历史界面。
2. 用经过患者级验证的原生体积分类模型替换 3D 路线当前的实验性切片集成分类。
3. 在医学依据和输出协议明确后，再增加基于 3D 分割结果的高级分析或诊断路线。
4. 补充登录限流、审计管理与管理员查询。

## 彩蛋

在项目根目录的交互式终端中执行：

```powershell
python Main.py game
```
