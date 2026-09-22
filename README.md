# Windows 划词 & 截图翻译工具

## 目标

1. 选中文字后，按 Ctrl+Alt+T 翻译并弹窗显示。
2. 按 Ctrl+Alt+Z 截图框选，OCR 识别后翻译。

## 技术栈

- Python 3.11+
- PyQt6 做界面
- keyboard 做全局快捷键
- pyperclip 读剪贴板
- Windows 内置 OCR (Windows.Media.Ocr) 做图片识别
- DeepSeek API (OpenAI 兼容) 做翻译

## 现有环境

- Windows 10/11
- VSCode + CodeBuddy 插件已安装
- DeepSeek API Key 已配置

## 要求

- API Key 从 .env 读取，不要硬编码
- 先给项目结构和核心代码，不要一次写完整
- 每完成一个模块，等我测试后再继续
