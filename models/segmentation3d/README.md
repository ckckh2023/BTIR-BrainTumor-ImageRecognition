# SuperLightNet 3D 分割适配

本目录封装项目的四模态 3D 脑肿瘤分割路线<br>
网络实现与预训练权重来自
[WTU-MIS-Laboratory/SuperLightNet](https://github.com/WTU-MIS-Laboratory/SuperLightNet)，
项目侧只维护确定性推理、输入校验、空间还原和任务系统适配

## 输入契约

- 必须同时提供 `flair`、`t1ce`、`t1`、`t2` 四个 3D NIfTI；
- 四个模态的 shape、affine、spacing 和 orientation 必须一致；
- 模态由 API 表单字段确定，不依赖上传文件名；
- 模型通道顺序固定为 `flair, t1ce, t1, t2`

## 输出契约

- 输出文件为多类标签 `prediction.nii.gz`；
- shape、affine、qform 和 sform 继承原始输入空间；
- 标签遵循 BraTS：`0=background`、`1=NCR/NET`、`2=ED`、`4=ET`；
- 同时返回每个标签的体素数、体积和占比

当前适配器负责分割与定量统计<br>
本地 ViT 分类器通过独立任务流程执行，分类结果与分割统计共同写入统一结果

## 实现说明

`inference.py` 使用 `128×128×128` MONAI 滑窗恢复完整体积，并固定 SuperLightNet
内部方向选择<br>
默认快速模式会启用 CUDA 的 cuDNN benchmark 与 TF32；如需逐体素可复现
评测，可将 `BTIR_3D_FAST_INFERENCE=false`<br>
模型训练时仍保留原始的随机方向增强行为

## 分割评测

数据集根目录下每个病例需包含四模态文件及唯一的 `*_seg.nii[.gz]` 标签
在项目根目录运行：

```powershell
python Main.py evaluate-3d <BraTS数据集目录>
```

命令逐例验证预测与真值的 shape、affine 和 BraTS `0/1/2/4` 标签，计算
`WT={1,2,4}`、`TC={1,4}`、`ET={4}` 的 Dice，并记录耗时和 CUDA 峰值显存<br>
双空区域不计入该区域数据集均值，避免空标签人为抬高成绩<br>
默认只保留 JSON 报告；通过 `--predictions-dir <目录>` 可以同时保留预测掩码

对外分发或参赛提交前，应再次核对上游仓库、论文与权重的授权条件，并保留来源说明
