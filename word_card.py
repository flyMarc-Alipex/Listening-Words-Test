#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordCard — 悬浮单词助记卡 (tkinter, 离线, 跨平台)

用法:
    python3 word_card.py

词表: 自动扫描同目录下的所有 .txt 词表文件(words.txt、day1-words.txt 等),
    右键菜单「词表」切换。每行一条:英文单词 <Tab> 或 <|> 或 <两个空格> 释义。
已会的词按词表分别记录(如 learned.txt、learned-day1-words.txt),右键菜单可「重置已会记录」。

快捷键: 空格=翻面  ←=上一个  →=下一个  R=随机  S=记正确(只读模式)
底部滑块切换「读写 / 听写」:听写模式播放语音、输入拼写,拼对记正确、拼错/超时记错误。
"""
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import tkinter as tk

APP_DIR = Path(__file__).resolve().parent
WORD_FILE = APP_DIR / "words.txt"
LEARNED_FILE = APP_DIR / "learned.txt"
LAST_FILE = APP_DIR / "last_list.txt"

# 配色(深色)
BG = "#1e1e24"
CARD = "#2a2a33"
LINE = "#3a3a46"
TEXT = "#ececf1"
SUB = "#8a8a9a"
ACCENT = "#7aa2ff"
BTNBG = "#3a3a46"
BTNTEXT = "#ececf1"
BTNACT = "#454552"

SAMPLE_WORDS = """# 格式:英文 <Tab 或 | 或 两个空格> 释义
# 把这份文件的示例词删掉,替换成你自己的词表即可继续使用。
example | 例子, 实例
practice | 练习, 实践
memorize | 记忆, 记住
review | 复习, 回顾
recall | 回想, 回忆
fluent | 流利的
vocabulary | 词汇
pronounce | 发音
sentence | 句子
translate | 翻译
"""


def load_words(path=WORD_FILE):
    if not path.exists():
        path.write_text(SAMPLE_WORDS, encoding="utf-8")
    words = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = None
        for sep in ("\t", "|", "  "):
            if sep in line:
                parts = [p.strip() for p in line.split(sep)]
                break
        if not parts or not parts[0]:
            continue
        w = parts[0]
        rest = parts[1:]
        senses = []  # [(释义, 例句), …],按文件里的顺序一一配对
        for i in range(0, len(rest), 2):
            m = rest[i]
            ex = rest[i + 1] if i + 1 < len(rest) else ""
            if m:
                senses.append((m, ex))
        words.append((w, senses))
    return words


def learned_path_for(word_file):
    # words.txt 沿用旧的 learned.txt;其余词表各自的已会记录为 learned-<词表名>.txt
    if word_file.stem == "words":
        return LEARNED_FILE
    return APP_DIR / f"learned-{word_file.stem}.txt"


def load_learned(path):
    if not path.exists():
        return set()
    return {l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def save_learned(learned, path):
    path.write_text("\n".join(sorted(learned)) + "\n", encoding="utf-8")


def stats_path_for(word_file):
    # 统计文件与词表一一对应;words.txt 的统计为 stats.txt
    if word_file.stem == "words":
        return APP_DIR / "stats.txt"
    return APP_DIR / f"stats-{word_file.stem}.txt"


def load_stats(path):
    """读取 stats 文件,返回 {单词: [正确次数, 错误次数]}。格式:单词 | 正确 | 错误"""
    stats = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                try:
                    stats[parts[0].strip()] = [int(parts[1].strip() or 0),
                                               int(parts[2].strip() or 0)]
                except ValueError:
                    continue
    return stats


def save_stats(path, stats):
    lines = ["# 格式:单词 | 正确次数 | 错误次数"]
    for w in sorted(stats):
        c, e = stats[w]
        lines.append(f"{w}|{c}|{e}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_learned(word_file, word, add=True):
    """手动操作已学会标记:
    add=True  -> 加入已学会,正确次数置 3、错误次数置 0
    add=False -> 移除已学会,正确/错误次数均置 0"""
    learned = load_learned(learned_path_for(word_file))
    stats = load_stats(stats_path_for(word_file))
    if add:
        learned.add(word)
        stats[word] = [3, 0]
    else:
        learned.discard(word)
        stats[word] = [0, 0]
    save_learned(learned, learned_path_for(word_file))
    save_stats(stats_path_for(word_file), stats)


def _apply_learned_many(word_file, words, add=True):
    """批量操作已学会标记(只读写一次文件):
    add=True  -> 全部加入已学会(正确次数置 3、错误次数置 0)
    add=False -> 全部移除已学会(正确/错误次数均置 0)"""
    learned = load_learned(learned_path_for(word_file))
    stats = load_stats(stats_path_for(word_file))
    for w in words:
        if add:
            learned.add(w)
            stats[w] = [3, 0]
        else:
            learned.discard(w)
            stats[w] = [0, 0]
    save_learned(learned, learned_path_for(word_file))
    save_stats(stats_path_for(word_file), stats)


def discover_lists():
    """扫描目录内所有 txt 词表文件(排除 learned* 的已会记录)。"""
    found = []
    for p in sorted(APP_DIR.glob("*.txt")):
        if p.name.startswith("learned") or p.name.startswith("stats"):
            continue
        if p.name == "last_list.txt":
            continue
        if load_words(p):
            found.append(p)
    found.sort(key=lambda p: (p.name != "words.txt"))
    return found


def load_last_list():
    if not LAST_FILE.exists():
        return None
    name = LAST_FILE.read_text(encoding="utf-8").strip()
    return name or None


def save_last_list(name):
    LAST_FILE.write_text(name, encoding="utf-8")


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def _examples_text(senses):
    """把每个释义对应的例句拼成「例①:… 例②:…」多行文本。"""
    lines = []
    for i, (_m, ex) in enumerate(senses, 1):
        tag = CIRCLED[i - 1] if i <= len(CIRCLED) else str(i)
        label = f"例{tag}" if len(senses) > 1 else "例"
        lines.append(f"{label}:{ex}" if ex else f"{label}:(无例句)")
    return "\n".join(lines)


class WordCard:
    def __init__(self, root):
        self.root = root
        self.lists = discover_lists()
        if not self.lists:
            load_words(WORD_FILE)
            self.lists = [WORD_FILE]
        self.list_index = 0
        for i, p in enumerate(self.lists):
            if p.name == "words.txt":
                self.list_index = i
                break
        saved = load_last_list()
        if saved:
            for i, p in enumerate(self.lists):
                if p.name == saved:
                    self.list_index = i
                    break
        self.list_var = tk.IntVar(value=self.list_index)
        self._stats_open = 0  # 打开的统计窗口数量
        self.mode = "read"    # read = 读写模式, dict = 听写模式
        self.mode_scale = None
        self.timer_id = None
        self.time_left = 5
        self._pending = None
        self.paused = False       # 听写倒计时是否暂停
        self.pause_btn = None
        self.audio_proc = None  # 当前正在播放的 say 进程
        self._audio_seq = 0     # 语音代次,丢弃过期语音的回调
        self._dict_word = None  # 当前正在听写的单词(避免同一词重复播放)
        self._load_list()

        self.root.geometry("430x255")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._topmost = True
        self._alpha = 1.0  # 默认不透明;老版 Tk 的透明窗口容易整块白屏
        try:
            self.root.attributes("-topmost", True)
            if self._alpha < 1.0:
                self.root.attributes("-alpha", self._alpha)
        except tk.TclError:
            pass

        self._build()
        self._build_menu()
        self._bind()
        self.show()
        # 强制先渲染一次(修复 macOS 旧版系统 Tk 首次显示空白、点击才出现内容的问题)
        try:
            self.root.update_idletasks()
            self.root.update()
        except tk.TclError:
            pass
        self.root.after(80, self.root.focus_force)
        self.root.after(150, lambda: self._reshow())  # 老版 Tk 渲染兜底:稍后再重绘一次(仅读写模式,避免听写重播)

    def _reshow(self):
        if self.mode == "read":
            self.show()

    def _load_list(self):
        self._cancel_timer()
        self._stop_audio()
        self._dict_word = None
        self.word_file = self.lists[self.list_index]
        self.learned_file = learned_path_for(self.word_file)
        self.stat_file = stats_path_for(self.word_file)
        self.words = load_words(self.word_file)
        self.learned = load_learned(self.learned_file)
        self.stat = load_stats(self.stat_file)
        self.active = [i for i in range(len(self.words)) if self.words[i][0] not in self.learned]
        random.shuffle(self.active)
        self.cur = 0
        self.flipped = False
        self.root.title(f"WordCard · {self.word_file.name}")

    def switch_list(self, i):
        if i < 0 or i >= len(self.lists) or i == self.list_index:
            return
        self.list_index = i
        self.list_var.set(i)
        save_last_list(self.lists[i].name)
        self._load_list()
        self.show()

    # ---------- UI ----------
    def _build(self):
        self.status_lbl = tk.Label(self.root, text="", font=("Helvetica", 10),
                                   bg=BG, fg=SUB)
        self.status_lbl.pack(pady=(8, 0))

        self.card = tk.Frame(self.root, bg=CARD, highlightbackground=LINE,
                             highlightthickness=1, cursor="hand2")
        self.card.pack(padx=12, pady=(6, 8), fill="both", expand=True)
        self.card.bind("<Button-1>", lambda e: self.flip())

        self.word_lbl = tk.Label(self.card, text="", font=("Helvetica", 20, "bold"),
                                 bg=CARD, fg=TEXT, wraplength=350)
        self.word_lbl.pack(pady=(16, 6))

        self.meaning_lbl = tk.Label(self.card, text="", font=("Helvetica", 12),
                                    bg=CARD, fg=ACCENT, wraplength=350)
        self.meaning_lbl.pack(pady=(0, 4))

        self.example_lbl = tk.Label(self.card, text="", font=("Helvetica", 10),
                                    bg=CARD, fg=SUB, wraplength=350, justify="left")
        self.example_lbl.pack(pady=(0, 14))

        # 听写模式的部件(默认隐藏,切到听写模式再显示)
        self.dict_box = tk.Frame(self.card, bg=CARD)
        self.dict_hint = tk.Label(self.dict_box, text="", font=("Helvetica", 11),
                                  bg=CARD, fg=SUB, wraplength=330)
        self.dict_hint.pack(pady=(12, 4))
        self.entry = tk.Entry(self.dict_box, font=("Helvetica", 16), justify="center",
                              bg=CARD, fg=TEXT, insertbackground=TEXT,
                              highlightthickness=1, highlightbackground=LINE)
        self.entry.pack(fill="x", padx=14, ipady=4)
        self.entry.bind("<Return>", lambda e: self.submit_dict())
        self.timer_lbl = tk.Label(self.dict_box, text="", font=("Helvetica", 10),
                                  bg=CARD, fg=ACCENT)
        self.timer_lbl.pack(pady=(6, 2))
        dfb = tk.Frame(self.dict_box, bg=CARD)
        dfb.pack(pady=(0, 10))
        self._make_button(dfb, "重复", self.repeat_dict)
        self._make_button(dfb, "提交", self.submit_dict)
        self.pause_btn = self._make_button(dfb, "暂停", self.toggle_pause)
        self._make_button(dfb, "退出", lambda: self._set_mode("read"))

        btns = tk.Frame(self.root, bg=BG)
        btns.pack(pady=(0, 8))
        for text, cmd in [("上一个", self.prev), ("翻面", self.flip),
                          ("随机", self.random_word), ("下一个", self.next_w),
                          ("已会", self.learn), ("不会", self.forget)]:
            self._make_button(btns, text, cmd)

        # 读写 / 听写 模式切换滑块
        mode_frame = tk.Frame(self.root, bg=BG)
        tk.Label(mode_frame, text="读写", font=("Helvetica", 9), bg=BG, fg=SUB).pack(side="left")
        self.mode_scale = tk.Scale(mode_frame, from_=0, to=1, orient="horizontal", length=90,
                                   showvalue=False, command=self._mode_cmd, bg=BG, fg=TEXT,
                                   troughcolor=LINE, highlightthickness=0, bd=0)
        self.mode_scale.set(0)
        self.mode_scale.pack(side="left", padx=4)
        tk.Label(mode_frame, text="听写", font=("Helvetica", 9), bg=BG, fg=SUB).pack(side="left")
        mode_frame.pack(pady=(0, 6))

    def _make_button(self, parent, text, command):
        """macOS 原生 tk.Button 忽略 bg/fg,改用 Label 自制按钮主题。
        命令在松开时触发,避免失活的置顶窗口吞掉第一次“按下”事件。"""
        btn = tk.Label(parent, text=text, font=("Helvetica", 10), bg=BTNBG,
                       fg=BTNTEXT, padx=9, pady=4, cursor="hand2")
        btn.pack(side="left", padx=2)
        btn.bind("<ButtonPress-1>", lambda e, b=btn: b.configure(bg=BTNACT))
        btn.bind("<ButtonRelease-1>",
                 lambda e, b=btn, c=command: (b.configure(bg=BTNBG), self._safe(c))[1])
        return btn

    def _safe(self, fn):
        """执行按钮命令;出错时弹窗提示并写入日志,避免按钮点了没反应。"""
        try:
            fn()
        except Exception:
            import traceback
            err = traceback.format_exc()
            try:
                log = APP_DIR / "wordcard-error.log"
                log.write_text(err, encoding="utf-8")
            except Exception:
                pass
            try:
                import tkinter.messagebox as mb
                mb.showerror("WordCard 出错了", err)
            except Exception:
                pass
            sys.stderr.write(err)

    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_checkbutton(label="窗口置顶", command=self.toggle_top)
        alpha_menu = tk.Menu(self.menu, tearoff=0)
        for pct in (100, 85, 70, 55):
            alpha_menu.add_radiobutton(label=f"{pct}%",
                                       command=lambda p=pct: self.set_alpha(p))
        self.menu.add_cascade(label="透明度", menu=alpha_menu)
        self.menu.add_separator()
        lists_menu = tk.Menu(self.menu, tearoff=0)
        for i, p in enumerate(self.lists):
            lists_menu.add_radiobutton(label=p.name, variable=self.list_var, value=i,
                                       command=lambda i=i: self.switch_list(i))
        self.menu.add_cascade(label="词表", menu=lists_menu)
        self.menu.add_separator()
        self.menu.add_command(label="简单统计", command=self.open_simple_stats)
        self.menu.add_command(label="详细词表统计", command=self.open_detail_stats)
        self.menu.add_separator()
        self.menu.add_command(label="打开词表文件", command=self.open_word_file)
        self.menu.add_command(label="重置已会记录", command=self.reset_learned)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.root.destroy)

    def _menu_popup(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _bind(self):
        self.root.bind_all("<Button-3>", self._menu_popup)
        self.root.bind_all("<Button-2>", self._menu_popup)
        # 用根窗口绑定而非 bind_all;听写模式下快捷键无效,全权交给输入框打字
        self.root.bind("<space>", lambda e: self.flip() if self.mode != "dict" else None)
        self.root.bind("<Right>", lambda e: self.next_w() if self.mode != "dict" else None)
        self.root.bind("<Left>", lambda e: self.prev() if self.mode != "dict" else None)
        self.root.bind("r", lambda e: self.random_word() if self.mode != "dict" else None)
        self.root.bind("s", lambda e: self.learn() if self.mode != "dict" else None)

    # ---------- 逻辑 ----------
    def current_word(self):
        return self.words[self.active[self.cur]]

    def show(self):
        total = len(self.words)
        if not self.active:
            self.example_lbl.config(text="")
            if self.mode == "dict":
                self.entry.delete(0, "end")
                self.timer_lbl.config(text="")
                self.dict_hint.config(text="全背完了!", fg=TEXT)
            else:
                self.word_lbl.config(text="全背完了!", fg=TEXT)
                self.meaning_lbl.config(text="右键菜单 → 打开词表补充新词", fg=SUB)
            self.status_lbl.config(text=f"{total} 词已全部标记已会")
            return
        w, senses = self.current_word()
        if self.mode == "dict":
            self._setup_dict(w, "；".join(m for m, _ in senses))
            return
        self.word_lbl.config(text=w, fg=TEXT)
        if self.flipped:
            if senses:
                self.meaning_lbl.config(text="\n".join(m for m, _ in senses), fg=ACCENT)
                self.example_lbl.config(text=_examples_text(senses), fg=SUB)
            else:
                self.meaning_lbl.config(text="(原文无提示)", fg=ACCENT)
                self.example_lbl.config(text="")
        else:
            self.meaning_lbl.config(text="— 点击卡片或按空格翻面 —", fg=SUB)
            self.example_lbl.config(text="")
        st = self.stat.get(w)
        extra = f"   对{st[0]} 错{st[1]}" if st else ""
        self.status_lbl.config(
            text=f"{self.cur + 1} / {len(self.active)}  已会 {len(self.learned)} / {total}{extra}")

    def flip(self):
        if self.mode == "dict":
            return
        if self.active:
            self.flipped = not self.flipped
            self.show()

    def next_w(self):
        if not self.active:
            return
        self.flipped = False
        self.cur = (self.cur + 1) % len(self.active)
        self.show()

    def prev(self):
        if not self.active:
            return
        self.flipped = False
        self.cur = (self.cur - 1) % len(self.active)
        self.show()

    def random_word(self):
        if not self.active:
            return
        self.flipped = False
        self.cur = random.randrange(len(self.active))
        self.show()

    def learn(self):
        """已会:该词正确次数 +1;当 正确-错误 >= 3 时自动判为已学会。"""
        if not self.active:
            return
        w = self.current_word()[0]
        self._mark(w, correct=True)
        self._advance_after(w)

    def forget(self):
        """不会:该词错误次数 +1。"""
        if not self.active:
            return
        w = self.current_word()[0]
        self._mark(w, correct=False)
        self._advance_after(w)

    def _mark(self, w, correct):
        st = self.stat.setdefault(w, [0, 0])
        st[0 if correct else 1] += 1
        save_stats(self.stat_file, self.stat)
        if correct and w not in self.learned and st[0] - st[1] >= 3:
            self.learned.add(w)
            save_learned(self.learned, self.learned_file)

    def _advance_after(self, w):
        if w in self.learned:
            self.active.pop(self.cur)  # 已学会的词移出抽取队列
            if not self.active:
                self.cur = 0
            elif self.cur >= len(self.active):
                self.cur = 0
        else:
            self.cur = (self.cur + 1) % len(self.active)
        self.flipped = False
        self.show()

    # ---------- 听写模式 ----------
    def _mode_cmd(self, value):
        try:
            mode = "dict" if int(round(float(value))) == 1 else "read"
        except (TypeError, ValueError):
            mode = "read"
        self._set_mode(mode)

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        self._cancel_timer()
        self._stop_audio()
        self._pending = None
        if mode == "dict":
            self.word_lbl.pack_forget()
            self.meaning_lbl.pack_forget()
            self.example_lbl.pack_forget()
            self.dict_box.pack(fill="both", expand=True, padx=10, pady=6)
            self.paused = False
            if self.pause_btn is not None:
                self.pause_btn.configure(text="暂停")
            if self.mode_scale is not None:
                self.mode_scale.set(1)
        else:
            self.dict_box.pack_forget()
            self.word_lbl.pack(pady=(16, 6))
            self.meaning_lbl.pack(pady=(0, 4))
            self.example_lbl.pack(pady=(0, 14))
            self.paused = False
            if self.mode_scale is not None:
                self.mode_scale.set(0)
        self.show()

    def _setup_dict(self, w, m):
        fresh = (self._dict_word != w)
        self._dict_word = w
        if fresh:
            self.entry.delete(0, "end")
            self.entry.focus_set()
            try:
                self.entry.focus_force()
            except tk.TclError:
                pass
            self.paused = False
            if self.pause_btn is not None:
                self.pause_btn.configure(text="暂停")
            self._play_audio(w, lambda: self._start_timer(w))
        st = self.stat.get(w)
        extra = f"   对{st[0]} 错{st[1]}" if st else ""
        self.status_lbl.config(
            text=f"{self.cur + 1} / {len(self.active)}  听写  已会 {len(self.learned)} / {len(self.words)}{extra}")
        self.dict_hint.config(text="听音频,在框内拼写,回车或点「提交」")

    def _play_audio(self, word, callback=None):
        """后台播放单词读音;播完后在主线程回调 callback。
        macOS 的 `say` 直接播音时,个别长词会在中途被系统截断(如 industry 只念出
        indus);因此先把单词合成到临时 aiff 文件,再用 afplay 完整播放。
        串行化:终止上一个语音进程并等它退出,过期语音的回调会被忽略。"""
        old = self.audio_proc
        self.audio_proc = None
        if old is not None:
            try:
                old.terminate()
                old.wait(timeout=0.5)
            except Exception:
                pass
        self._audio_seq += 1
        seq = self._audio_seq

        def run():
            try:
                if sys.platform == "darwin":
                    time.sleep(0.08)
                    out = Path(tempfile.gettempdir()) / f"wordcard_{seq}.aiff"
                    syn = subprocess.Popen(["say", "-o", str(out), "-r", "160", word],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    syn.wait()
                    if self._audio_seq != seq:
                        try:
                            out.unlink(missing_ok=True)
                        except Exception:
                            pass
                        return
                    proc = subprocess.Popen(["afplay", str(out)],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.audio_proc = proc
                    proc.wait()
                    if self.audio_proc is proc:
                        self.audio_proc = None
                    try:
                        out.unlink(missing_ok=True)
                    except Exception:
                        pass
                else:
                    time.sleep(0.2)
            except Exception:
                pass
            if callback is not None and self._audio_seq == seq:
                try:
                    self.root.after(0, callback)
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _stop_audio(self):
        if self.audio_proc is not None:
            try:
                self.audio_proc.terminate()
            except Exception:
                pass
            self.audio_proc = None

    def _start_timer(self, word=None):
        self._cancel_timer()
        self.time_left = 5
        if self.paused:
            self.timer_lbl.config(text="⏸ 已暂停(⏱5)")
            return
        self.timer_lbl.config(text="⏱ 5")
        self.timer_id = self.root.after(1000, self._tick)

    def _tick(self):
        if self.mode != "dict" or not self.active:
            return
        self.time_left -= 1
        if self.time_left <= 0:
            self.timer_lbl.config(text="⏱ 0")
            self.submit_dict(timeout=True)
            return
        self.timer_lbl.config(text=f"⏱ {self.time_left}")
        self.timer_id = self.root.after(1000, self._tick)

    def _cancel_timer(self):
        if self.timer_id is not None:
            try:
                self.root.after_cancel(self.timer_id)
            except Exception:
                pass
            self.timer_id = None

    def submit_dict(self, timeout=False):
        """听写提交:拼对记正确+1,拼错记错误+1,短暂反馈后进入下一个词。
        超时(timeout=True)只是强制按当前输入提交:输入正确仍记正确,输入错误才记错误。"""
        if not self.active or self._pending:
            return
        w = self.current_word()[0]
        guess = self.entry.get().strip().lower()
        ok = (guess == w.strip().lower())
        if ok:
            msg = "✓ 拼写正确!"
        elif timeout:
            msg = f"✗ 超时,正确:{w}"
        else:
            msg = f"✗ 拼写错误,正确:{w}"
        self._mark(w, ok)
        self._cancel_timer()
        self.timer_lbl.config(text="")
        self.dict_hint.config(text=msg)
        self._pending = w
        self.root.after(1300, self._after_feedback)

    def _after_feedback(self):
        if self.mode != "dict" or not self.active or self._pending is None:
            return
        if self.current_word()[0] != self._pending:
            self._pending = None  # 用户已手动切换,不再自动翻
            return
        w = self._pending
        self._pending = None
        self._advance_after(w)

    def repeat_dict(self):
        if not self.active or self._pending:
            return
        if self.paused:
            self.paused = False
            if self.pause_btn is not None:
                self.pause_btn.configure(text="暂停")
        w = self.current_word()[0]
        self._play_audio(w, lambda: self._start_timer(w))

    def toggle_pause(self):
        """暂停/继续听写倒计时。暂停期间超时不判错,可从容拼写。"""
        if not self.active or self._pending:
            return
        self.paused = not self.paused
        if self.paused:
            self._cancel_timer()
            self.timer_lbl.config(text="⏸ 已暂停")
            if self.pause_btn is not None:
                self.pause_btn.configure(text="继续")
        else:
            self.timer_lbl.config(text=f"⏱ {self.time_left}")
            if self.pause_btn is not None:
                self.pause_btn.configure(text="暂停")
            if not self.timer_id:
                self.timer_id = self.root.after(1000, self._tick)

    # ---------- 窗口控制 ----------
    def toggle_top(self):
        self._topmost = not self._topmost
        self.root.attributes("-topmost", self._topmost)

    def set_alpha(self, pct):
        self._alpha = pct / 100
        try:
            self.root.attributes("-alpha", self._alpha)
        except tk.TclError:
            pass

    def open_word_file(self):
        if not self.word_file.exists():
            load_words(self.word_file)
        if sys.platform == "darwin":
            subprocess.run(["open", str(self.word_file)])
        elif os.name == "nt":
            os.startfile(str(self.word_file))
        else:
            subprocess.run(["xdg-open", str(self.word_file)])

    def reset_learned(self):
        self.learned = set()
        save_learned(self.learned, self.learned_file)
        self.active = [i for i in range(len(self.words))]
        random.shuffle(self.active)
        self.cur = 0
        self.flipped = False
        self.show()

    # ---------- 统计 ----------
    def _find_list(self, name):
        for p in self.lists:
            if p.name == name:
                return p
        return None

    def _reconcile(self):
        """按当前已学会集合重建抽取队列,尽量保留当前所在位置。"""
        curw = None
        if self.active and 0 <= self.cur < len(self.active):
            curw = self.words[self.active[self.cur]][0]
        self.active = [i for i in range(len(self.words)) if self.words[i][0] not in self.learned]
        if curw is not None:
            self.cur = 0
            for i in range(len(self.active)):
                if self.words[self.active[i]][0] == curw:
                    self.cur = i
                    break
            else:
                if self.cur >= len(self.active):
                    self.cur = 0
        else:
            self.cur = 0
        self.flipped = False
        self.show()

    def _on_stats_changed(self, wf):
        """统计窗口改动的是当前词表时,同步刷新主界面。"""
        if wf == self.word_file:
            self.learned = load_learned(self.learned_file)
            self.stat = load_stats(self.stat_file)
            self._reconcile()

    def _situate(self, win):
        try:
            win.geometry(f"+{self.root.winfo_rootx() + 30}+{self.root.winfo_rooty() + 30}")
        except tk.TclError:
            pass

    def _present(self, win):
        """把统计窗口提到主窗口前方并抢走焦点。
        主窗口默认始终置顶,会盖住任何新窗口;这里在统计窗口打开时
        临时关掉主窗口置顶,让统计窗口真正压到前面,关掉后再恢复。"""
        try:
            win.transient(self.root)
            win.attributes("-topmost", True)
            self._stats_open += 1
            if self._stats_open == 1:
                self.root.attributes("-topmost", False)
            win.lift()
            win.focus_force()
            win.update()
        except tk.TclError:
            pass

    def _on_stats_closed(self, win):
        """统计窗口收起后:恢复主窗口置顶并归还焦点。"""
        try:
            self._stats_open = max(0, self._stats_open - 1)
            if self._stats_open == 0:
                self.root.attributes("-topmost", True)
            self._refocus_main()
        except tk.TclError:
            pass

    def _refocus_main(self):
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def open_simple_stats(self):
        """简单统计:所选词表中错误次数最高的 30 个单词。"""
        win = tk.Toplevel(self.root)
        win.title("简单统计 — 错误最多的 30 个词")
        win.geometry("400x480")
        win.configure(bg=BG)
        self._situate(win)
        self._present(win)
        win.bind("<Destroy>", lambda e: self._on_stats_closed(win) if e.widget is win else None)

        var = tk.StringVar(value=self.word_file.name)
        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(top, text="词表:", bg=BG, fg=TEXT, font=("Helvetica", 10)).pack(side="left")
        tk.OptionMenu(top, var, *[p.name for p in self.lists]).pack(side="left", padx=6)

        lb = tk.Listbox(win, font=("Helvetica", 11), bg=CARD, fg=TEXT,
                        selectbackground=ACCENT, activestyle="none")
        lb.pack(fill="both", expand=True, padx=10, pady=8)

        def refresh(*_):
            lb.delete(0, "end")
            wf = self._find_list(var.get())
            if not wf:
                return
            stats = load_stats(stats_path_for(wf))
            rows = sorted(stats.items(), key=lambda kv: (-kv[1][1], kv[1][0]))[:30]
            if not rows:
                lb.insert("end", "(该词表还没有任何错误记录)")
            for w, (c, e) in rows:
                lb.insert("end", f"{w:<20}  错 {e:>3}  对 {c:>3}")
        var.trace_add("write", refresh)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        self._make_button(btns, "刷新", refresh)
        self._make_button(btns, "关闭", win.destroy)
        refresh()

    def open_detail_stats(self):
        """详细词表统计:每词正确/错误次数与正确率/错误率,可手动标记/移除已学会。"""
        win = tk.Toplevel(self.root)
        win.title("详细词表统计")
        win.geometry("500x520")
        win.configure(bg=BG)
        self._situate(win)
        self._present(win)
        win.bind("<Destroy>", lambda e: self._on_stats_closed(win) if e.widget is win else None)

        var = tk.StringVar(value=self.word_file.name)
        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(top, text="词表:", bg=BG, fg=TEXT, font=("Helvetica", 10)).pack(side="left")
        tk.OptionMenu(top, var, *[p.name for p in self.lists]).pack(side="left", padx=6)

        lb = tk.Listbox(win, font=("Helvetica", 10), bg=CARD, fg=TEXT,
                        selectbackground=ACCENT, activestyle="none",
                        selectmode="multiple")
        lb.pack(fill="both", expand=True, padx=10, pady=8)

        def current_file():
            return self._find_list(var.get())

        def refresh(*_):
            lb.delete(0, "end")
            wf = current_file()
            if not wf:
                return
            learned = load_learned(learned_path_for(wf))
            stats = load_stats(stats_path_for(wf))
            for word, _senses in load_words(wf):
                c, e = stats.get(word, [0, 0])
                tot = c + e
                cr = round(c * 100 / tot) if tot else 0
                er = round(e * 100 / tot) if tot else 0
                status = "已学会" if word in learned else "学习中"
                lb.insert("end", f"{word:<18} 对{c:>4} 错{e:>4} 正率{cr:>3}% 错率{er:>3}%  {status}")
        var.trace_add("write", refresh)

        def selected_words():
            sel = lb.curselection()
            if not sel:
                return []
            return [lb.get(i).split()[0] for i in sel]

        def select_all():
            lb.selection_set(0, "end")

        def mark_learned():
            words = selected_words()
            wf = current_file()
            if not words or not wf:
                return
            _apply_learned_many(wf, words, add=True)
            refresh()
            self._on_stats_changed(wf)

        def unmark_learned():
            words = selected_words()
            wf = current_file()
            if not words or not wf:
                return
            _apply_learned_many(wf, words, add=False)
            refresh()
            self._on_stats_changed(wf)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        self._make_button(btns, "全选", select_all)
        self._make_button(btns, "标记为已学会", mark_learned)
        self._make_button(btns, "移除已学会", unmark_learned)
        self._make_button(btns, "刷新", refresh)
        self._make_button(btns, "关闭", win.destroy)
        refresh()


def main():
    try:
        root = tk.Tk()
        WordCard(root)
        root.mainloop()
    except Exception:
        # 启动异常时:写入日志文件 + 弹窗显示详情,避免只看到空白窗口
        import traceback
        import tkinter.messagebox as mb
        err = traceback.format_exc()
        log = APP_DIR / "wordcard-error.log"
        try:
            log.write_text(err, encoding="utf-8")
        except Exception:
            pass
        try:
            mb.showerror("WordCard 出错了", err + "\n\n详情已保存到:\n" + str(log))
        except Exception:
            sys.stderr.write(err)
        sys.stderr.write(err)
        return 1


if __name__ == "__main__":
    main()