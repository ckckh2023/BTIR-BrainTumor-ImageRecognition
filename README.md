# 脑肿瘤 MRI 图像分析

BTIR 提供脑肿瘤 MRI 图像分类与分割能力。每次分析以独立
`task_id` 为单位，保存输入图像、异步作业状态、模型运行历史、统一结果和错误信息；

## 当前能力

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 模型推理 | 已完成 | 3D 四模态 NIfTI 使用本地 ViT 患者级分类与 SuperLightNet 分割 |
| 任务管理 | 已完成 | 上传创建任务、异步运行、重试、取消、软删除、恢复、状态查询 |
| 历史查询 | 已完成 | 支持任务筛选、分页和单任务运行历史 |
| 异步调度 | 已完成 | Redis + RQ 单一 3D 推理队列、自动重试、状态对账和安全取消 |
| 数据持久化 | 已完成 | SQLite 保存元数据，文件系统保存图像与完整结果 |
| 运行安全 | 已完成 | Redis 写入锁、SQLite 事务、JSON 原子写入 |
| CPU/GPU | 已完成 | CPU、NVIDIA CUDA、Linux AMD ROCm |
| 接口协议 | 核心流程已完成 | 3D 四模态上传、异步运行和结果展示已对接；高级任务操作界面待补充 |
| 多用户 | 第一阶段已完成 | JWT 隔离、用户配额、强制改密，以及管理员查询、密码重置、任务删除/恢复和审计查询已完成 |

> 升级注意：当前版本已删除 2D 创建与推理能力，只接受四模态 3D 任务。升级已有
> 部署前先备份 `data/btir.db`、活动输出与归档目录；旧 2D 任务不会被自动迁移或
> 删除。开发环境确认无需保留旧数据后，可停止 API 与 Worker，再使用
> `python Main.py clear --dry-run` 和 `python Main.py clear` 重置业务数据。

## 3D 结果查看

3D 任务完成后，在结果文件区域选择“3D查看”，可以：

- 在 FLAIR、T1CE、T1、T2 模态之间切换；
- 使用轴位、冠状位、矢状位三视图或体渲染；
- 叠加 `prediction.nii.gz` 分割掩码，并调整显示透明度；
- 继续使用原有入口下载四模态输入和预测掩码。

查看器按需读取当前模态和掩码，文件仍通过现有的鉴权任务文件接口获取，不新增公开
文件地址。浏览器需要支持 WebGL2。体数据渲染使用固定版本的 NiiVue，引用来源和
BSD-2-Clause 许可证全文见 [第三方软件说明](THIRD_PARTY_NOTICES.md)。

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
models/classification/vit-binary/model.safetensors
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
把最后一条命令生成的随机值写入 `.env` 的 `BTIR_JWT_SECRET_KEY`。服务器终端可直接
执行 `python Main.py user create <username>` 创建普通账号；首次部署可执行
`python Main.py user create <username> --admin` 创建管理员，不需要临时开放公开注册。

3D 任务默认使用仓库内的本地二分类 ViT。它从配置模态提取 25 张轴向切片，
离线完成 `no/yes` 分类并生成病例级平均概率。分类加载或推理失败时不会切换其他
模型，而是由异步任务自动重试一次；仍失败则任务明确标记为 `failed`。该分类流程
不会改变 SuperLightNet 分割输入或结果。

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

终端 2 启动 3D Worker：

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
3. 调用 `POST /tasks/3d`，同时上传 `flair`、`t1ce`、`t1`、`t2` 四个
   `.nii` 或 `.nii.gz` 文件，并保存返回的 `task_id`。
4. `POST /tasks/{task_id}/run-async` 提交任务。任务固定执行本地 ViT
   多切片分类，再执行 SuperLightNet 分割。
5. 轮询 `GET /tasks/{task_id}`，直到状态变为 `succeeded`。
6. 历史和归档接口只返回当前用户自己的任务。

从旧版本升级后，历史任务默认不属于任何用户，也不会被普通账号访问。服务器
操作者确认接收账号后执行：

```powershell
python Main.py claim-legacy-tasks <username>
python Main.py claim-legacy-tasks <username> --apply
```

第一条仅预览，第二条才会写入归属关系。

服务器账号维护使用以下命令，密码通过终端隐藏输入，不会出现在 shell 历史中：

```powershell
python Main.py user create <username>
python Main.py user create <username> --admin
python Main.py user list
python Main.py user set-role <username> admin
python Main.py user set-role <username> user
python Main.py user disable <username>
python Main.py user enable <username>
python Main.py user reset-password <username>
```

角色变更、禁用账号或重置密码都会撤销该用户已经签发的旧 Token；密码被重置后，
用户必须调用 `POST /auth/change-password` 修改临时密码才能继续操作任务。管理员可通过
`GET /admin/users` 和 `GET /admin/tasks` 查询跨用户摘要，还可以重置指定用户密码
或安全删除、恢复其指定任务，并通过 `GET /admin/audit` 查询审计记录；管理员接口
暂不开放跨用户运行和文件下载。HTTP 仍可用于本机和内网
联调；正式公网部署时再由反向代理提供 HTTPS。

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
    │   ├── flair.nii.gz
    │   ├── t1ce.nii.gz
    │   ├── t1.nii.gz
    │   └── t2.nii.gz
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
- `output/`、`data/*.db*`、缓存和本地数据集不提交到版本库；正式 `.pth`
  和 `.safetensors` 权重统一通过 Git LFS 管理。

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
python Main.py run --task-id <task_id>
python Main.py evaluate-3d <BraTS数据集目录>
python Main.py reconcile-tasks
python Main.py clear --dry-run
python Main.py purge --dry-run
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

`purge` 在 `clear` 的基础上额外删除 `logs/` 和 `data/` 目录本身及其全部内容
（包括日志文件、SQLite 数据库等），使项目回到无日志、无数据库的初始状态。
执行前同样必须先停止 API 和 Worker，并先使用 `--dry-run` 检查目标。

## 开发约定

1. 前端和外部服务只通过 API 使用任务，不直接访问 SQLite 或任务目录。
2. 新增模型时，在 `services/inference_service.py` 提供统一入口，并通过 `persist_model_result()` 写入结果。
3. 修改公开字段时，同步检查 `contracts/task.py`、API 路由和
 [API 对接说明](docs/API.md)。
4. 修改持久化字段时同步检查 `core/task_records.py` 和 SQLite migration。
5. 清理和归档先使用预览模式；`clear` 只操作 BTIR 队列、作业和任务锁，禁止
   用 `FLUSHALL` 或 `FLUSHDB` 代替项目清理命令。

## 下一阶段

1. 扩展浏览器端到端测试，覆盖登录、上传、任务操作与 3D 查看。
2. 用患者级、按来源隔离的数据继续校准本地 ViT，优先评估肿瘤召回率、假阴性和
   阈值稳定性；验证前不允许分类结果跳过分割。
3. 在医学依据和输出协议明确后，再增加基于 3D 分割结果的高级分析或诊断路线。
4. 补充管理员敏感操作二次确认、审计日志轮转与保留策略。

## 彩蛋

在项目根目录的交互式终端中执行：

```powershell
python Main.py game
```
