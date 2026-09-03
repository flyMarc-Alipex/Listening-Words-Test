#!/bin/bash
# WordCard — macOS 双击启动悬浮单词卡
# 首次运行若提示"无法打开",请在 Finder 里右键 → 打开。
cd "$(dirname "$0")" || exit 1

# 静默默认 macOS 系统 Tk 的弃用警告
export TK_SILENCE_DEPRECATION=1

# 优先使用 python.org 安装的 Python(自带正常可用的 Tk),
# 找不到时回退到系统 python3。
PY=""
for py in /Library/Frameworks/Python.framework/Versions/*/bin/python3.*; do
    [ -x "$py" ] && PY="$py" && break
done
[ -z "$PY" ] && PY="python3"

exec "$PY" word_card.py