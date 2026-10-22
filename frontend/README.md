# 前端目录

```text
frontend/
├── *.html          页面模板，保留原有访问地址
├── styles/
│   ├── theme.css   颜色、字体、主题变量与基础样式
│   ├── controls.css 公共图标按钮及交互状态
│   ├── auth.css    登录、修改密码共用的表单布局
│   └── *.css       与同名页面对应的样式
├── scripts/
│   ├── theme-init.js   首次渲染的主题初始化
│   ├── workspace-init.js 工作区恢复的首次渲染状态
│   ├── volume_viewer.js  3D 查看器适配层
│   └── *.js           与同名页面对应的交互逻辑
├── components/     现有 Vue 组件
└── vendor/         第三方库及其原始文件
```

页面先加载 `scripts/theme-init.js`，再加载 `styles/theme.css`、
`styles/controls.css` 和页面样式。页面交互脚本放在正文末尾。

主题按钮、客户端下载入口统一使用 `.btir-icon-button`。
公共文件负责按钮的颜色、尺寸、圆角、hover、active 和键盘焦点状态；
页面样式只负责定位，不另写同类按钮的外观覆盖规则。

静态页面继续通过 `/web/`、`/login/` 两个挂载入口提供。
报告弹窗中的样式地址和 3D 查看器的第三方库地址须同步考虑资源目录变化。