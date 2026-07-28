# BTIR API 对接说明

本文面向前端联调和接口调用方。开发环境默认地址为
`http://127.0.0.1:8000`，启动服务后也可通过
`http://127.0.0.1:8000/docs` 查看 Swagger 文档。

## 调用流程

```text
POST /tasks 上传图片
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
```

前端只调用 API，不直接读取 SQLite 或服务器任务目录。

## 任务状态

| 状态 | 含义 |
| --- | --- |
| `created` | 任务已创建，尚未提交推理 |
| `queued` | 已进入 RQ 队列 |
| `running` | Worker 正在执行 |
| `cancel_requested` | 已请求在安全阶段停止 |
| `partial` | 只完成了部分模型 |
| `succeeded` | 分类和分割均已完成 |
| `failed` | 自动重试耗尽后仍失败 |
| `canceled` | 任务已取消 |

## 接口总览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/tasks` | 上传图片并创建任务 |
| `GET` | `/tasks` | 分页、筛选历史任务 |
| `GET` | `/tasks/{task_id}` | 查询任务状态与最新结果 |
| `GET` | `/tasks/{task_id}/runs` | 查询模型运行历史 |
| `GET` | `/tasks/{task_id}/files/{file_path}` | 读取公开结果文件 |
| `POST` | `/tasks/{task_id}/run-async` | 提交完整异步推理 |
| `POST` | `/tasks/{task_id}/retry` | 重新提交最终失败的任务 |
| `POST` | `/tasks/{task_id}/cancel` | 取消或请求停止任务 |
| `GET` | `/healthz` | API 存活检查 |
| `GET` | `/readyz` | 完整依赖就绪检查 |
| `GET` | `/runtime` | 查询实际推理设备 |
| `GET` | `/ops/queue` | 查询队列运行状态 |

## 上传并创建任务

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
  "input_file": "image.png"
}
```

上传大小和解码后像素数量由 `BTIR_MAX_UPLOAD_BYTES` 与
`BTIR_MAX_IMAGE_PIXELS` 限制。

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
成功任务的 `completed_models` 应包含：

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

## 重试和取消

最终状态为 `failed` 的任务可以手动重试：

```http
POST /tasks/{task_id}/retry
```

请求体与 `run-async` 相同，可以省略。正在排队或运行的重复请求会复用
已有作业。

取消任务：

```http
POST /tasks/{task_id}/cancel
```

- `created` 或尚未执行的作业会直接变为 `canceled`。
- 运行中的任务先变为 `cancel_requested`，Worker 在安全阶段停止。
- 已完成或已失败任务返回 `409 Conflict`。
- 对已取消任务重复调用是幂等的。

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

  const response = await fetch(`/tasks?${params}`);
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
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "运行历史查询失败");
  }
  return response.json();
}
```

前后端分开部署时，将相对路径替换为后端完整地址，并在
`BTIR_CORS_ORIGINS` 中加入前端来源。

## 通用错误

| HTTP 状态 | 含义 |
| --- | --- |
| `400` | 上传、阈值或查询参数不合法 |
| `404` | 任务或公开文件不存在 |
| `409` | 当前任务状态不允许操作，或写入锁等待超时 |
| `422` | FastAPI 请求字段校验失败 |
| `503` | SQLite、Redis、队列或其他关键依赖不可用 |

错误体通常为：

```json
{
  "detail": "错误说明"
}
```
