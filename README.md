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

## 使用

1. 启动：双击桌面快捷方式「划词翻译」（或运行 `python main.py`）
2. 首次启动会自动弹出**设置窗口**，填入自己的 API Key 后保存
3. 之后程序常驻托盘，快捷键随时可用：

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Alt+T` | 划词翻译：选中文字后按下，弹出置顶译文窗口 |
| `Ctrl+Alt+Z` | 截图翻译：第一次按下框选，调整好后再按一次确认识别 |

截图流程：`Ctrl+Alt+Z` → 拖出选区 → 可拖动内部移动、拖 8 个手柄改大小 → **再按一次 `Ctrl+Alt+Z`** 开始识别翻译。`Esc` 或右键取消。

托盘图标右键菜单：划词翻译 / 截图翻译 / 设置… / 退出。**双击托盘图标打开设置**。

## 配置

按「用户设置文件 > `.env` > 默认值」的顺序读取：

- 用户设置：`%APPDATA%\WinTranslator\settings.json`（**推荐**，由设置界面写入）
- 开发调试：项目根目录 `.env`（参考 `.env.example`，已被 `.gitignore` 忽略）

设置项：API Key、接口地址、模型、超时、两个全局快捷键。设置里带「测试连接」按钮，保存后立即生效（改快捷键无需重启）。

## 分发给别人

**不要直接把项目文件夹拷出去**——里面的 `.env` 是你自己的 API Key，对方会拿它翻译、账单记在你头上。

用打包脚本导出：

```powershell
python tools/package.py                 # 导出到 dist\win-translator
python tools/package.py --out D:\share   # 或指定目录
```

它会：
- **排除 `.env`**（重点）、`.env.example`、`__pycache__`、`.git`、测试脚本
- 附一份给最终用户的 `使用说明.txt`
- **导出后扫描一遍**，确认没有把 API Key 带出去（发现就报错，不全给你发）

对方拿到后：装 Python 3.11+ → `pip install -r requirements.txt` → 按 `使用说明.txt` 建快捷方式 → 首次启动填**他自己的** Key。

> 想彻底免去装 Python，可以再上 PyInstaller 打包成单个 exe，这一步还没做。

## 要求

- API Key 从 .env 读取，不要硬编码
- 先给项目结构和核心代码，不要一次写完整
- 每完成一个模块，等我测试后再继续
