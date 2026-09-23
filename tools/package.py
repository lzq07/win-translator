"""把项目导出成可分发的目录（不含你的 API Key）。

用法：
    python tools/package.py                    # 输出到 dist\\win-translator
    python tools/package.py --out D:\\share     # 自定义输出目录
    python tools/package.py --include-tests    # 连 test_*.py 一起打包
    python tools/package.py --overwrite        # 目标已存在时先清空

导出后会自动扫描一遍，确认没有把 API Key 带出去。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "dist" / "win-translator"

# 整个目录跳过
EXCLUDE_DIRS = {
    ".codebuddy",
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "venv",
    ".vscode",
}

# 单个文件跳过（.env 是重点，里面是你的 API Key）
EXCLUDE_FILES = {
    ".env",
    ".env.example",  # 给最终用户不需要，且容易误导他们去手填文件
    ".gitignore",
    "snip_test.png",
}

# 疑似 API Key 的特征（用于导出后的泄露扫描）
# 注意：要能区分真实 Key 和 .env.example 里的占位符 sk-your-api-key-here
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"DEEPSEEK_API_KEY\s*=\s*sk-[A-Za-z0-9]{20,}"),
)

USER_GUIDE = """划词 & 截图翻译 —— 使用说明
================================

一、安装
1. 安装 Python 3.11 或更高版本：https://www.python.org/downloads/
   安装时务必勾选 "Add python.exe to PATH"。
2. 在本文件夹里打开命令行，执行：
       pip install -r requirements.txt

二、创建桌面快捷方式
       python tools\\make_icon.py
       powershell -ExecutionPolicy Bypass -File tools\\create_shortcut.ps1
   桌面上会出现「划词翻译」图标。
   （也可以直接运行 python main.py，会有日志输出，方便排查问题。）

三、首次使用
双击桌面图标启动，程序会常驻在屏幕右下角的托盘里。
第一次启动会自动弹出设置窗口，填入**你自己的** API Key 后保存。
之后双击托盘图标可以再次打开设置，右键托盘可以退出。

四、快捷键
    Ctrl+Alt+T    划词翻译：选中文字后按下，弹出译文窗口
    Ctrl+Alt+Z    截图翻译：第一次按下框选区域，调整好后再按一次开始识别
两个快捷键都能在设置里改成你喜欢的组合。

五、截图怎么用
按 Ctrl+Alt+Z 后屏幕变暗，拖动鼠标框出要识别的区域。
松开后可以继续调整：拖动选区内部移动，拖动 8 个手柄改大小。
满意后再按一次 Ctrl+Alt+Z，开始识别并翻译。Esc 或右键取消。

六、去哪里拿 API Key
在 DeepSeek 后台（platform.deepseek.com）创建，复制后粘贴进设置窗口。
本工具只把 Key 保存在你自己的电脑上：
    %%APPDATA%%\\WinTranslator\\settings.json
不会上传到任何第三方，也不会写进本文件夹。

七、常见问题
- 双击没反应：可能已经有一个实例在运行，去托盘确认。
- 快捷键没反应：如果被操作的程序是以管理员身份运行的，
  请用管理员权限启动本工具。
- 截图翻译识别不出文字：把框选区域拉大一些，
  或先把页面放大（Ctrl + 加号）再截图。
- 想看详细报错：改用命令行运行 python main.py。
"""


def should_include(path: Path, include_tests: bool) -> bool:
    """判断文件是否应该被打包。"""
    name = path.name
    if name in EXCLUDE_FILES:
        return False
    if name.endswith((".pyc", ".pyo")):
        return False
    if name.startswith("test_") and not include_tests:
        return False
    return True


def copy_project(out_dir: Path, include_tests: bool) -> list[Path]:
    """遍历项目并复制需要的文件。

    Args:
        out_dir: 目标目录（已确保存在）。
        include_tests: 是否包含 test_*.py。

    Returns:
        list[Path]: 被复制的文件列表。
    """
    copied: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        # 就地剪掉不需要深入的子目录
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)

        for filename in sorted(filenames):
            source = Path(dirpath) / filename
            if not should_include(source, include_tests):
                continue
            target = out_dir / source.relative_to(PROJECT_ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
    return copied


def scan_secrets(out_dir: Path) -> list[str]:
    """扫描导出目录，确认没有把 API Key 带出去。

    Args:
        out_dir: 导出目录。

    Returns:
        list[str]: 命中疑似 Key 的相对路径列表。
    """
    hits: list[str] = []
    for file in sorted(out_dir.rglob("*")):
        if not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 二进制文件（图标等）跳过
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(str(file.relative_to(out_dir)))
                break
    return hits


def human_size(num_bytes: int) -> str:
    """把字节数转成易读的字符串。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出可分发的目录（不含 API Key）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录")
    parser.add_argument(
        "--include-tests", action="store_true", help="连 test_*.py 一起打包"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="目标已存在时先清空再导出"
    )
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    if out_dir == PROJECT_ROOT:
        print(f"输出目录不能是项目根目录：{out_dir}")
        return 1
    if out_dir.exists() and any(out_dir.iterdir()):
        if not args.overwrite:
            print(f"目标目录非空：{out_dir}")
            print("加 --overwrite 覆盖，或换一个 --out 目录。")
            return 1
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = copy_project(out_dir, args.include_tests)
    if not copied:
        print("没有复制任何文件，请检查项目目录。")
        return 1

    guide = out_dir / "使用说明.txt"
    guide.write_text(USER_GUIDE.replace("%%APPDATA%%", "%APPDATA%"), encoding="utf-8")

    total = sum(f.stat().st_size for f in copied) + guide.stat().st_size
    print(f"已导出 {len(copied)} 个文件 -> {out_dir}（{human_size(total)}）")
    print(f"已生成 {guide.name}")

    # 安全检查：确认没有把 Key 带出去
    hits = scan_secrets(out_dir)
    if hits:
        print()
        print("!! 警告：以下文件里疑似包含 API Key，请不要直接分发：")
        for name in hits:
            print(f"   - {name}")
        return 1

    print("泄露扫描：未发现 API Key，可以安全分发。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
