# 本地脑肿瘤二分类 ViT

本目录保存 3D 推理路线使用的本地 2D 切片分类器<br>
运行时只读取本目录，不会联网下载模型

## 模型来源

- 上游模型：`dima806/brain_tumor_detection`
- 固定版本：`d33cfd06151ffbc5aad051534137a00961134b46`
- 基础模型：`google/vit-base-patch16-224-in21k`
- 上游示例：[Brain Tumor Detection Example](https://www.kaggle.com/code/dima806/brain-tumor-detection-example)
- 许可证：Apache-2.0

`model.safetensors` 的 SHA-256：

```text
328D473DC39C1BF82C114F2FF542642D67C2A7F5743A7BEBA5A830849068AD8C
```

## 运行要求

以下文件缺一不可：

- `config.json`
- `model.safetensors`
- `preprocessor_config.json`

权重由 Git LFS 管理，克隆项目后若文件不完整，请执行 `git lfs pull`

项目从配置的 3D 模态中抽取轴向切片，逐批执行二分类，再对切片概率取平均得到病例级结果
