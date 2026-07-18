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
| 异步调度 | x | 当前模型调用为同步执行；后续增加排队、运行进度、失败重试和任务取消 |
| 数据库 | x | 前端需要任务列表、筛选或多人访问时，保存任务元数据与状态；图像和掩码继续存文件系统或对象存储 |

## 开始

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

## API 使用流程

### 1. 上传图片并创建任务

`POST /tasks`

请求类型为 `multipart/form-data`：

- `file`：必填，目前支持 `.jpg`、`.jpeg`、`.png`
- `name`：可选，任务显示名称

> 成功后返回 `task_id`。之后的模型接口都传入这个 ID，不需要重复上传图片

同时也保留了本机路径传图片建任务接口：

`POST /tasks/from-path`

其 JSON 请求体示例：

```json
{
  "image_path": "E:/dataset/example.jpg",
  "name": "local-test",
  "input_mode": "auto"
}
```

> `from-path` 适合后端开发机调试，前端正式接入应使用上传接口

### 2. 调用模型

正常分析流程建议使用一键运行接口：

```text
POST /tasks/{task_id}/run
```

该接口会依次执行分类和分割，并将两项结果合并至同一份 `frontend_result.json`请求体可省略；省略时分割阈值默认是 `0.5`  
如需指定阈值：

```json
{
  "threshold": 0.5
}
```

单模型接口保留给调试、重复运行单个模型或前端按需分析：

```text
POST /tasks/{task_id}/classify
POST /tasks/{task_id}/segment
```

分割接口请求体可指定阈值：

```json
{
  "threshold": 0.5
}
```

> 当前接口为同步调用：请求会等待模型完成后再返回，因此模型耗时较长时

### 3. 查询任务结果

```text
GET /tasks/{task_id}
```

返回任务状态、已完成模型列表和当前统一结果
任务完成后，`completed_models` 应包含：

```json
["classification", "segmentation"]
```

## 任务目录

每次创建任务均在 `output/` 下创建时间戳目录：

```text
output/
└── 20260715_120000_001/       # task_id
    ├── input/
    │   └── image.jpg           # 上传或复制后的输入图像
    ├── task.json               # 任务元数据与状态
    ├── classification/         # 最新分类模型结果
    ├── segmentation/           # 最新分割模型结果
    ├── runs/                   # 模型调用的历史结果
    ├── frontend_result.json    # 供前端读取的统一结果
    └── error.json              # 调用失败时的错误记录（如存在）
```

同一模型在同一任务内重复运行时：

- `runs/<model>/` 追加一次新的历史运行记录；
- 当前模型结果与 `frontend_result.json` 更新为最新结果；
> 不会创建新的任务，也不会覆盖历史运行目录

## 代码结构

```text
api/app.py                    # FastAPI 路由
contracts/task.py             # API 请求/响应数据模型
services/task_service.py      # 任务创建、结果写入、统一结果合并
services/inference_service.py # 分类/分割模型的统一调用入口
services/cleanup_service.py   # 清理生成的缓存与结果
services/presentation.py      # CLI 输出格式化
accelerator/                  # CPU / CUDA / ROCm 设备适配包
processing/                   # 通用预处理、后处理
models/                       # 各模型的推理实现
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
```

## 协定

1. 不直接读取或修改其他任务目录；所有模型调用均通过 `task_id` 定位任务
2. 新增模型时，在 `services/inference_service.py` 提供统一入口，并通过 `persist_model_result()` 写入结果，避免自行拼接 JSON
3. 修改前端字段前，先同步修改 `contracts/task.py`、`services/task_service.py` 和本 README 的接口说明
4. `output/`、模型权重、缓存和本地数据集属于本地产物，避免提交到版本库

## 下一阶段

1. 确认 `frontend_result.json` 的字段与错误格式
2. 模型调用改为异步任务，增加 `queued / running / succeeded / failed` 状态
