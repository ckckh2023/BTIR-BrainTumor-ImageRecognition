# SuperLightNet 3D 分割适配

本目录封装项目的四模态 3D 脑肿瘤分割路线。网络实现与预训练权重来自
[WTU-MIS-Laboratory/SuperLightNet](https://github.com/WTU-MIS-Laboratory/SuperLightNet)，
项目侧只维护确定性推理、输入校验、空间还原和任务系统适配。

## 输入契约

- 必须同时提供 `flair`、`t1ce`、`t1`、`t2` 四个 3D NIfTI；
- 四个模态的 shape、affine、spacing 和 orientation 必须一致；
- 模态由 API 表单字段确定，不依赖上传文件名；
- 模型通道顺序固定为 `flair, t1ce, t1, t2`。

## 输出契约

- 输出文件为多类标签 `prediction.nii.gz`；
- shape、affine、qform 和 sform 继承原始输入空间；
- 标签遵循 BraTS：`0=background`、`1=NCR/NET`、`2=ED`、`4=ET`；
- 同时返回每个标签的体素数、体积和占比。

当前路线仅提供分割与可复核的定量统计，不输出肿瘤类型诊断、脑叶定位或临床
结论。3D 分类模型应作为独立模型接入，不能复用现有单张图片的 2D 分类器。

## 实现说明

`inference.py` 使用 `128×128×128` MONAI 滑窗恢复完整体积，并在推理模式下
固定 SuperLightNet 内部方向选择，避免同一输入重复运行得到不同结果。模型训练
时仍保留原始的随机方向增强行为。

对外分发或参赛提交前，应再次核对上游仓库、论文与权重的授权条件，并保留来源
说明。
