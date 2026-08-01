# BTIR API 对接说明

本文面向前端联调和接口调用方。开发环境默认地址为
`http://127.0.0.1:8000`，启动服务后也可通过
`http://127.0.0.1:8000/docs` 查看 Swagger 文档。

## 调用流程

```text
POST /auth/register 或 POST /auth/login
    ↓
后续请求携带 Authorization: Bearer <access_token>
    ↓
POST /tasks 上传 2D 图片
或 POST /tasks/3d 上传四模态 3D NIfTI
    ↓
POST /tasks/{task_id}/run-async 提交异步推理
    ↓
GET /tasks/{task_id} 轮询状态和读取最新结果
```

历史页面使用：

```text
GET /tasks 查询任务列表
    ↓
GET /tasks/{task_id}/runs 查询该任务的运行历史

GET /tasks/archived 查询可恢复的归档任务
    ↓
POST /tasks/{task_id}/restore 恢复所选任务
```


## 任务状态

| 状态 | 含义 |
| --- | --- |
| `created` | 任务已创建，尚未提交推理 |
| `queued` | 已进入 RQ 队列 |
| `running` | Worker 正在执行 |
| `cancel_requested` | 已请求在安全阶段停止 |
| `partial` | 只完成了部分模型 |
| `succeeded` | 当前任务 `expected_models` 中的模型均已完成 |
| `failed` | 自动重试耗尽后仍失败 |
| `canceled` | 任务已取消 |

## 接口总览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/auth/register` | 注册账号；受服务器注册开关控制 |
| `POST` | `/auth/login` | 登录并获取访问令牌 |
| `GET` | `/auth/me` | 查询当前登录用户 |
| `POST` | `/tasks` | 上传图片并创建 2D 任务 |
| `POST` | `/tasks/3d` | 上传四模态 NIfTI 并创建 3D 任务 |
| `GET` | `/tasks` | 分页、筛选历史任务 |
| `GET` | `/tasks/archived` | 分页、筛选尚未永久清除的归档任务 |
| `GET` | `/tasks/{task_id}` | 查询任务状态与最新结果 |
| `GET` | `/tasks/{task_id}/runs` | 查询模型运行历史 |
| `GET` | `/tasks/{task_id}/files/{file_path}` | 读取公开结果文件 |
| `POST` | `/tasks/{task_id}/run-async` | 提交完整异步推理 |
| `POST` | `/tasks/{task_id}/retry` | 重新提交最终失败的任务 |
| `POST` | `/tasks/{task_id}/cancel` | 取消或请求停止任务 |
| `DELETE` | `/tasks/{task_id}` | 将指定非活动任务安全移入归档区 |
| `POST` | `/tasks/{task_id}/restore` | 恢复尚未永久清除的归档任务 |
| `GET` | `/healthz` | API 存活检查 |
| `GET` | `/readyz` | 完整依赖就绪检查 |
| `GET` | `/runtime` | 查询实际推理设备 |
| `GET` | `/ops/queue` | 查询 2D、3D 独立队列及合计运行状态 |

## 认证

注册和登录请求：

```http
POST /auth/login
Content-Type: application/json

{"username": "alice", "password": "safe-password"}
```

成功后返回 `access_token`、`user_id` 和 `username`。除健康检查、运行信息和
`/auth/register`、`/auth/login` 外，任务接口都必须携带：

```http
Authorization: Bearer <access_token>
```

用户名长度为 3～32，只允许字母、数字、下划线和连字符。注册是否开放由
`BTIR_REGISTRATION_ENABLED` 控制。任务列表只返回当前用户的数据；访问其他
用户、无归属或不存在的任务统一返回 `404`，避免泄露任务是否存在。

登录和注册受 Redis 固定窗口限流保护，超过限制返回 `429` 并携带
`Retry-After`。Redis 不可用时认证入口返回 `503`，已经登录用户的普通任务请求
不依赖认证限流计数器。账号被禁用或密码被管理员重置后，旧 Token 会立即失效。

## 上传并创建 2D 任务

```http
POST /tasks
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | 支持 `.jpg`、`.jpeg`、`.png` |
| `name` | 否 | 任务显示名称 |

成功返回 `201 Created`：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "status": "created",
  "analysis_mode": "2d",
  "input_file": "image.png"
}
```

上传大小和解码后像素数量由 `BTIR_MAX_UPLOAD_BYTES` 与
`BTIR_MAX_IMAGE_PIXELS` 限制。

## 上传并创建 3D 任务

```http
POST /tasks/3d
Content-Type: multipart/form-data
```

一次请求必须同时携带属于同一受试者、同一空间的四个 NIfTI：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `flair` | 是 | FLAIR，`.nii` 或 `.nii.gz` |
| `t1ce` | 是 | 增强 T1，`.nii` 或 `.nii.gz` |
| `t1` | 是 | T1，`.nii` 或 `.nii.gz` |
| `t2` | 是 | T2，`.nii` 或 `.nii.gz` |
| `name` | 否 | 任务显示名称 |

后端会校验四个文件的 shape、affine、spacing 和方向是否一致。文件名无须遵循
BraTS 命名规则，模态由表单字段确定。四个文件总大小由
`BTIR_MAX_3D_UPLOAD_BYTES` 限制，解压后的单个体积还受
`BTIR_MAX_3D_VOXELS` 限制。

成功返回 `201 Created`：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120100_001",
  "status": "created",
  "analysis_mode": "3d",
  "input_files": {
    "flair": "flair.nii.gz",
    "t1ce": "t1ce.nii.gz",
    "t1": "t1.nii.gz",
    "t2": "t2.nii.gz"
  }
}
```

当前 3D 路线固定使用本地 ViT 分析 `FLAIR` 轴向切片，再执行 SuperLightNet
分割。分类概率按全部有效切片取均值；模型权重缺失、加载失败或推理异常时由任务
队列自动重试一次，仍失败则任务返回 `failed`，不会切换其他分类模型。模态可通过
`BTIR_3D_CLASSIFIER_MODALITY` 调整。

## 提交异步推理

```http
POST /tasks/{task_id}/run-async
Content-Type: application/json
```

请求体可以省略。指定分割阈值时：

```json
{
  "threshold": 0.5
}
```

`threshold` 只用于 2D 分割；3D SuperLightNet 使用多类 argmax，不读取该值。
创建任务后，两条路线都调用同一个 `run-async` 接口，后端根据
`analysis_mode` 自动分流。

成功返回 `202 Accepted`。如果同一任务已经处于 `queued` 或 `running`，
后端会复用现有作业，并通过 `reused_existing_job` 标识：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "status": "queued",
  "job": {
    "id": "rq-job-id",
    "queue": "inference",
    "status": "queued",
    "attempt": 0,
    "max_retries": 1,
    "queued_at": "2026-07-28T12:00:01+08:00"
  },
  "reused_existing_job": false
}
```

## 查询任务状态和最新结果

```http
GET /tasks/{task_id}
```

前端可定时轮询，直到进入 `succeeded`、`failed` 或 `canceled`。
2D 成功任务的 `completed_models` 为：

```json
["classification", "segmentation"]
```

3D 成功任务同样为：

```json
["classification", "segmentation"]
```

响应中的主要字段：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "name": "示例任务",
  "status": "succeeded",
  "analysis_mode": "2d",
  "expected_models": ["classification", "segmentation"],
  "created_at": "2026-07-28T12:00:00+08:00",
  "updated_at": "2026-07-28T12:00:03+08:00",
  "completed_models": ["classification", "segmentation"],
  "input": {
    "filename": "image.png",
    "storage_mode": "uploaded",
    "size_bytes": 1024,
    "sha256": "..."
  },
  "job": {
    "id": "rq-job-id",
    "queue": "inference",
    "status": "succeeded",
    "attempt": 0,
    "max_retries": 1,
    "queue_wait_ms": 10.0,
    "execution_ms": 633.2
  },
  "error": null,
  "frontend_result": {}
}
```

这里外层 `schema_version: "0.1"` 是任务查询接口版本。任务成功后，
`frontend_result` 自身还有独立的推理结果协议版本：

```json
{
  "schema_version": "1.0",
  "task_id": "20260728_120000_001",
  "analysis_mode": "3d",
  "status": "succeeded",
  "completed_models": ["classification", "segmentation"],
  "input_files": {
    "flair": "flair.nii.gz",
    "t1ce": "t1ce.nii.gz",
    "t1": "t1.nii.gz",
    "t2": "t2.nii.gz"
  },
  "classification": {
    "model": "models/classification/vit-binary",
    "class": "yes",
    "confidence": 0.977611,
    "probabilities": {"no": 0.022389, "yes": 0.977611},
    "threshold": 0.5,
    "method": "vit_binary_multislice_mean",
    "experimental": true,
    "modality": "flair",
    "evaluated_slices": 25,
    "aggregation": "mean_probability"
  },
  "segmentation": {
    "model": "models/segmentation3d/superlightnet",
    "model_metadata": {
      "name": "SuperLightNet",
      "variant": "small",
      "weights": "model_epoch_297.pth"
    },
    "spatial": {},
    "labels": {},
    "regions": {},
    "mask_file": "runs/segmentation/<run_id>/prediction.nii.gz"
  },
  "result_files": {},
  "latest_runs": {},
  "timing": {}
}
```

`frontend_result` 的兼容规则：

- 前端按 `analysis_mode` 选择 2D 或 3D 展示；
- `classification.class`、`classification.confidence` 和
  `segmentation.mask_file` 保持原位置，现有前端无需修改；
- 分类与分割对象均包含稳定的 `model` 标识，3D 分割另外提供
  `model_metadata`；
- 替换模型可以新增模型专属字段，但不能删除或改义版本 `1.0` 的既有字段；
- 需要破坏性修改时必须提升 `frontend_result.schema_version`，并同步前端和本文档。

3D 任务的 `input.filename` 为 `null`，`input.files` 分别给出四个模态的
文件名、大小与 SHA-256。
`frontend_result.classification` 是患者级分类结果，主要字段包括：

- `model`：固定为 `models/classification/vit-binary`；
- `method`：固定为 `vit_binary_multislice_mean`；
- `class`、`confidence`、`probabilities`：兼容前端的二分类结果及概率；
- `threshold`：病例级阳性判定阈值；
- `experimental`：当前固定为 `true`，表示不能作为临床诊断依据；
- `modality`、`axis`：体积来源模态与切片方向；
- `evaluated_slices`、`aggregation`、`evidence_slices`：参与聚合的切片数量、
  聚合方法及最高阳性概率切片摘要。

`frontend_result.segmentation` 提供：

- `model`、`model_metadata`：分割适配器标识及模型名称、变体和权重；
- `mask_file`：预测标签 NIfTI 的任务内相对路径，可通过
  `GET /tasks/{task_id}/files/{file_path}` 下载；
- `spatial`：原始 shape、spacing、orientation 等空间信息；
- `labels`：输出标签定义，采用 BraTS 标签 `0/1/2/4`；
- `regions`：各标签的体素数、体积与占比。

输出 `prediction.nii.gz` 保持原始 shape 和 affine。本地 ViT 患者级分类按实验性
模型返回；上述分类、分割及定量统计都不是肿瘤类型诊断、脑叶定位或临床结论。

失败任务只公开可展示的 `error.code`、`error.message` 和
`error.updated_at`，内部异常详情与本机路径不会通过 API 返回。

## 查询历史任务

```http
GET /tasks
```

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `limit` | `20` | 每页 1–100 条 |
| `offset` | `0` | 跳过的记录数 |
| `status` | 空 | 按任务状态筛选 |
| `q` | 空 | 按任务名称或 `task_id` 搜索，最长 100 字符 |
| `created_from` | 空 | 创建时间下界，ISO 8601 |
| `created_to` | 空 | 创建时间上界，ISO 8601 |

示例：

```http
GET /tasks?q=Patient&status=succeeded&created_from=2026-07-01T00:00:00%2B08:00&created_to=2026-07-31T23:59:59%2B08:00&limit=20&offset=0
```

普通任务列表默认不返回已归档任务。`created_from` 晚于 `created_to`
时返回 `400 Bad Request`。

响应示例：

```json
{
  "schema_version": "0.1",
  "items": [
    {
      "task_id": "20260728_120000_001",
      "name": "Patient A",
      "status": "succeeded",
      "created_at": "2026-07-28T12:00:00+08:00",
      "updated_at": "2026-07-28T12:00:03+08:00",
      "completed_models": ["classification", "segmentation"],
      "input": {
        "filename": "image.png",
        "storage_mode": "uploaded",
        "size_bytes": 1024,
        "sha256": "..."
      },
      "job": null,
      "error": null
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

## 查询归档任务

```http
GET /tasks/archived
```

该接口仅返回尚未永久清除、因而仍可选择恢复的任务。支持与普通任务列表相同的
`limit`、`offset`、`status` 和 `q` 参数，按归档时间倒序排列。

每条记录在普通任务摘要之外增加：

```json
{
  "archived_at": "2026-07-28T12:30:00Z",
  "purge_eligible_at": "2026-08-04T12:30:00Z"
}
```

`purge_eligible_at` 表示任务进入可永久清除期的时间，不代表该时间一到就一定
被删除；在运维实际执行永久清除之前仍可调用恢复接口。

## 查询运行历史

```http
GET /tasks/{task_id}/runs
```

查询参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `model` | 空 | `classification` 或 `segmentation` |
| `limit` | `20` | 每页 1–100 条 |
| `offset` | `0` | 跳过的记录数 |

响应按运行时间倒序排列，只公开稳定元数据，不暴露服务器结果文件路径：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "items": [
    {
      "run_id": "20260728_120003_125",
      "model": "classification",
      "created_at": "2026-07-28T12:00:03+08:00",
      "inference_ms": 204.5
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

## 任务操作

前端可根据任务状态展示操作：

| 当前状态 | 建议操作 |
| --- | --- |
| `created` | 运行、取消、删除 |
| `queued`、`running` | 取消 |
| `cancel_requested` | 等待状态收敛 |
| `failed` | 重试、删除 |
| `partial`、`succeeded` | 再次运行、删除 |
| `canceled` | 删除 |
| 已归档 | 从 `GET /tasks/archived` 列表选择恢复 |

### 重试

最终状态为 `failed` 的任务可以手动重试：

```http
POST /tasks/{task_id}/retry
```

请求体与 `run-async` 相同，可以省略。正在排队或运行的重复请求会复用
已有作业。

### 取消

取消任务：

```http
POST /tasks/{task_id}/cancel
```

- `created` 或尚未执行的作业会直接变为 `canceled`。
- 运行中的任务先变为 `cancel_requested`，Worker 在安全阶段停止。
- 已完成或已失败任务返回 `409 Conflict`。
- 对已取消任务重复调用是幂等的。

### 删除

```http
DELETE /tasks/{task_id}
```

删除采用软删除语义：

- `queued`、`running`、`cancel_requested` 返回 `409 Conflict`。
- 其他非活动状态会获取任务写入锁，将整个任务移动到归档区。
- 设置 `archived_at`，并把操作用户写入 `archive/audit.jsonl`。
- 普通任务列表立即隐藏该任务，任务详情随后返回 `404`。
- 重复删除尚未永久清除的同一任务会返回相同归档信息。

成功响应：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "status": "archived",
  "archived_at": "2026-07-28T12:30:00Z",
  "purge_eligible_at": "2026-08-04T12:30:00Z"
}
```

`purge_eligible_at` 仅表示达到永久清除宽限期，不代表后端会自动永久删除。
永久清除仍受运维配置和 `purge-archive --apply` 控制。

### 恢复

```http
POST /tasks/{task_id}/restore
```

只要任务尚未被永久清除，即使已经超过 `purge_eligible_at`，仍可在实际 purge
执行前恢复。恢复会：

- 获取同一任务的 Redis 写入锁。
- 将完整目录从 `archive/tasks/` 移回活动输出目录。
- 清除 `archived_at`，保留原任务状态和运行历史。
- 更新任务 `updated_at`，避免定期归档立即再次移走刚恢复的任务。
- 写入 `restore_api` 审计记录。

成功响应：

```json
{
  "schema_version": "0.1",
  "task_id": "20260728_120000_001",
  "status": "restored",
  "task_status": "failed",
  "restored_at": "2026-07-30T09:00:00Z"
}
```

恢复后任务重新出现在 `GET /tasks` 中，并可按原状态继续查看、重试或再次运行。
未归档任务请求恢复时返回 `409`；已经永久清除的任务返回 `404`。

### 更换输入图片

当前不提供修改已有任务输入图片的接口。`retry` 和 `run-async` 都继续使用
该任务原始图片。需要更换图片时应重新调用 `POST /tasks` 创建新任务，以免
旧运行历史与新图片混在同一个 `task_id` 下。

## 读取结果文件

```http
GET /tasks/{task_id}/files/{file_path}
```

常用示例：

```http
GET /tasks/{task_id}/files/frontend_result.json
```

后端会校验路径范围，并移除 JSON 中的内部本机路径字段。前端一般优先读取
`GET /tasks/{task_id}` 返回的 `frontend_result`，只有明确需要独立文件时才调用
文件接口。

## 前端调用示例

同源托管时使用相对路径。浏览器会通过 `URLSearchParams` 自动处理时间参数
中的 `+` 等字符：

```javascript
const token = localStorage.getItem("btir_token");
const authHeaders = {Authorization: `Bearer ${token}`};

async function fetchTasks({
  q = "",
  status = "",
  createdFrom = "",
  createdTo = "",
  limit = 20,
  offset = 0,
} = {}) {
  const params = new URLSearchParams({limit, offset});
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (createdFrom) params.set("created_from", new Date(createdFrom).toISOString());
  if (createdTo) params.set("created_to", new Date(createdTo).toISOString());

  const response = await fetch(`/tasks?${params}`, {headers: authHeaders});
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "任务查询失败");
  }
  return response.json();
}

async function fetchTaskRuns(taskId, model = "") {
  const params = new URLSearchParams({limit: 100, offset: 0});
  if (model) params.set("model", model);

  const response = await fetch(
    `/tasks/${encodeURIComponent(taskId)}/runs?${params}`,
    {headers: authHeaders},
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "运行历史查询失败");
  }
  return response.json();
}

async function requestTaskAction(taskId, action) {
  const method = action === "delete" ? "DELETE" : "POST";
  const path = action === "delete"
    ? `/tasks/${encodeURIComponent(taskId)}`
    : `/tasks/${encodeURIComponent(taskId)}/${action}`;
  const response = await fetch(path, {method, headers: authHeaders});
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "任务操作失败");
  }
  return response.json();
}

// requestTaskAction(taskId, "retry")
// requestTaskAction(taskId, "cancel")
// requestTaskAction(taskId, "delete")
// requestTaskAction(taskId, "restore")
```

前后端分开部署时，将相对路径替换为后端完整地址，并在
`BTIR_CORS_ORIGINS` 中加入前端来源。

## 通用错误

| HTTP 状态 | 含义 |
| --- | --- |
| `401` | Token 缺失、无效或已过期 |
| `403` | 注册已关闭或用户已禁用 |
| `400` | 上传、阈值或查询参数不合法 |
| `404` | 任务、无权访问的任务或公开文件不存在 |
| `409` | 当前任务状态不允许操作，或写入锁等待超时 |
| `429` | 当前用户的任务存储或并发运行数量达到上限 |
| `422` | FastAPI 请求字段校验失败 |
| `503` | SQLite、Redis、队列或其他关键依赖不可用 |

错误体通常为：

```json
{
  "detail": "错误说明"
}
```
