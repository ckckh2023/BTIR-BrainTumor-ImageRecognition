# 第三方软件说明

## 脑肿瘤 FLAIR 二分类 ViT

- 模型：本项目自训练的 `no/yes` 二分类 ViT
- 发布仓库：https://huggingface.co/Songline/BrainTumor_FlairClassifier
- 初始化主干：`google/vit-base-patch16-224-in21k`
- 本项目用途：对 3D MRI 提取的 FLAIR 轴向切片执行本地 `no/yes` 二分类。
- 本地适配器与权重：`models/classification/vit_binary.py` 与
  `models/classification/vit-binary/`

自训练权重按发布仓库页面声明的许可证使用；初始化主干
`google/vit-base-patch16-224-in21k` 遵循其上游许可证（Apache-2.0）。
许可证全文：https://www.apache.org/licenses/LICENSE-2.0

## NiiVue

- 项目：NiiVue
- 使用版本：`@niivue/niivue 0.69.0`
- 上游仓库：https://github.com/niivue/niivue
- 官方文档：https://niivue.com/docs/
- 本项目用途：在浏览器中解析并显示 NIfTI 体数据、三视图、体渲染和分割掩码叠加。
- 本地分发文件：`frontend/vendor/niivue.umd.js`
- 分发文件 SHA-256：`47B896B77EC4A5BE3EF1949C33AD393B6F45629921F326C279000BCF51BDB4AF`
- 许可证：BSD-2-Clause

BTIR 自己的任务、鉴权、文件请求、模态切换和界面控制逻辑位于
`frontend/volume_viewer.js`；NiiVue 仅作为体数据渲染与交互内核使用。

### NiiVue BSD-2-Clause License

Copyright (c) 2021, Niivue

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
