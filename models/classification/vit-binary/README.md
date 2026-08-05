# 本地脑肿瘤二分类 ViT

本目录保存 3D 推理流程使用的 V1 FLAIR 分类模型

运行时只读取本地文件，不会联网下载权重

## 模型信息

- 发布仓库 [Songline/BrainTumor_FlairClassifier](https://huggingface.co/Songline/BrainTumor_FlairClassifier)
- 初始化主干 `google/vit-base-patch16-224-in21k`
- 输入模态 FLAIR
- 病例级规则为 25 张轴位有效切片阳性概率均值
- 判定阈值 `0.548381`
- 权重格式 `safetensors`

`model.safetensors` SHA-256

```text
333B18821DD4A8E5B30C6F34A5F476A8D86BFCCCE681510FEBB6E43CEBB22C9A
```

## 锁定评测

| 数据范围 | 分类结果 |
| --- | --- |
| 内部固定测试 | 29 / 30 正确 |
| UCSF-PDGM 外部开发阳性集 | 灵敏度 16 / 20 |
| HBN-SSI 外部开发健康集 | 特异度 12 / 12 |
| UPENN-GBM 最终盲测阳性集 | 灵敏度 9 / 10 |
| OpenNeuro ds003592 最终盲测健康集 | 特异度 10 / 10 |
| 合并最终盲测分类 | 19 / 20 正确 |

## 必需文件

- `config.json`
- `model.safetensors`
- `preprocessor_config.json`

三项文件必须保持来自同一版本
