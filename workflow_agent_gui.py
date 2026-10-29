#!/usr/bin/env python3
"""Tkinter GUI for Workflow Agent."""

from __future__ import annotations

import argparse
import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import workflow_agent_core as agent


SKILL_DISTILL_TASK = """请从上下文中蒸馏一个可复用 skill，并输出完整 Markdown 文件内容。

要求：
1. 包含 YAML frontmatter，至少包含 name 和 description。
2. description 要写清楚什么时候触发这个 skill。
3. 正文包含目标、适用场景、输入、输出、工作流、质量检查、失败处理和示例。
4. 指令要具体、可执行、可复用，避免空泛建议。
5. 如果上下文中包含现有 skill，请判断是生成新 skill、合并 skill，还是作为插件插入现有工作流。
6. 最后用 LLM-as-a-judge 标准自检：触发条件是否明确、工作流是否完整、是否能应用到 code 和 convert 模式、是否存在安全风险。
"""


class HarnessGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Workflow Agent")
        self.geometry("1180x820")
        self.context_files: list[str] = []
        self.context_dirs: list[str] = []
        self.skill_files: list[str] = []
        self.skill_dirs: list[str] = []
        self.cancel_requested = False
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        page_scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=page_scrollbar.set)
        page_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        root = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=root, anchor="nw")

        def configure_scrollregion(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def configure_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        root.bind("<Configure>", configure_scrollregion)
        canvas.bind("<Configure>", configure_width)
        canvas.bind_all("<MouseWheel>", wheel)

        config = ttk.LabelFrame(root, text="Model and Runtime")
        config.pack(fill=tk.X)

        self.mode_var = tk.StringVar(value="code")
        self.provider_var = tk.StringVar(value="Ollama Local")
        self.base_url_var = tk.StringVar(value=agent.DEFAULT_BASE_URL)
        self.model_var = tk.StringVar(value=agent.DEFAULT_MODEL)
        self.api_key_var = tk.StringVar(value="")
        self.workdir_var = tk.StringVar(value=str(Path.cwd()))
        self.max_steps_var = tk.IntVar(value=12)
        self.temperature_var = tk.DoubleVar(value=0.2)
        self.web_var = tk.BooleanVar(value=True)
        self.install_var = tk.BooleanVar(value=True)
        self.judge_var = tk.BooleanVar(value=True)
        self.yes_write_var = tk.BooleanVar(value=False)
        self.auto_context_var = tk.BooleanVar(value=True)

        ttk.Label(config, text="模式").grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
        mode_box = ttk.Combobox(config, textvariable=self.mode_var, values=("code", "convert", "skill"), width=14, state="readonly")
        mode_box.grid(row=0, column=1, sticky=tk.W, padx=6, pady=4)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._mode_changed())
        ttk.Label(config, text="模型来源").grid(row=0, column=2, sticky=tk.W, padx=6, pady=4)
        provider = ttk.Combobox(config, textvariable=self.provider_var, values=("Ollama Local", "LM Studio Local", "OpenAI", "DeepSeek", "Custom API"), width=18, state="readonly")
        provider.grid(row=0, column=3, sticky=tk.W, padx=6, pady=4)
        provider.bind("<<ComboboxSelected>>", lambda _event: self._apply_provider())
        ttk.Label(config, text="接口地址").grid(row=0, column=4, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(config, textvariable=self.base_url_var, width=34).grid(row=0, column=5, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(config, text="模型").grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
        self.model_combo = ttk.Combobox(config, textvariable=self.model_var, width=32)
        self.model_combo.grid(row=1, column=1, columnspan=2, sticky=tk.EW, padx=6, pady=4)
        ttk.Button(config, text="刷新模型", command=self._refresh_models).grid(row=1, column=3, sticky=tk.W, padx=6, pady=4)
        ttk.Label(config, text="API 密钥").grid(row=1, column=4, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(config, textvariable=self.api_key_var, width=30, show="*").grid(row=1, column=5, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(config, text="工作目录").grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(config, textvariable=self.workdir_var).grid(row=2, column=1, columnspan=3, sticky=tk.EW, padx=6, pady=4)
        ttk.Button(config, text="选择", command=self._choose_workdir).grid(row=2, column=4, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(config, text="允许网页", variable=self.web_var).grid(row=2, column=5, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(config, text="允许安装包", variable=self.install_var).grid(row=2, column=6, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(config, text="LLM 评审", variable=self.judge_var).grid(row=3, column=4, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(config, text="工作目录内直接写入", variable=self.yes_write_var).grid(row=3, column=5, sticky=tk.W, padx=6, pady=4)
        ttk.Button(config, text="导入 opencode JSON", command=self._import_opencode_json).grid(row=3, column=6, sticky=tk.W, padx=6, pady=4)
        ttk.Checkbutton(config, text="自动读取工作目录", variable=self.auto_context_var).grid(row=4, column=4, sticky=tk.W, padx=6, pady=4)

        ttk.Label(config, text="最大步数").grid(row=3, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Spinbox(config, textvariable=self.max_steps_var, from_=1, to=100, width=8).grid(row=3, column=1, sticky=tk.W, padx=6, pady=4)
        ttk.Label(config, text="温度").grid(row=3, column=2, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(config, textvariable=self.temperature_var, width=8).grid(row=3, column=3, sticky=tk.W, padx=6, pady=4)
        config.columnconfigure(5, weight=1)

        context = ttk.LabelFrame(root, text="补充上下文（可选，程序会自动读取工作目录）")
        context.pack(fill=tk.X, pady=(10, 0))
        self.context_text = self._scrolled_text(context, height=3)
        buttons = ttk.Frame(context)
        buttons.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(buttons, text="添加上下文文件", command=self._add_context_file).pack(side=tk.LEFT)
        ttk.Button(buttons, text="添加上下文目录", command=self._add_context_dir).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="清空上下文路径", command=self._clear_context_paths).pack(side=tk.LEFT)
        self.context_paths_var = tk.StringVar(value="未选择上下文文件或目录")
        ttk.Label(buttons, textvariable=self.context_paths_var).pack(side=tk.LEFT, padx=10)

        skills = ttk.LabelFrame(root, text="应用到代码和转换的 Skill")
        skills.pack(fill=tk.X, pady=(10, 0))
        skill_buttons = ttk.Frame(skills)
        skill_buttons.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(skill_buttons, text="添加 Skill 文件", command=self._add_skill_file).pack(side=tk.LEFT)
        ttk.Button(skill_buttons, text="添加 Skill 目录", command=self._add_skill_dir).pack(side=tk.LEFT, padx=6)
        ttk.Button(skill_buttons, text="清空 Skill 路径", command=self._clear_skill_paths).pack(side=tk.LEFT)
        self.skill_paths_var = tk.StringVar(value="未选择 Skill 文件或目录")
        ttk.Label(skill_buttons, textvariable=self.skill_paths_var).pack(side=tk.LEFT, padx=10)

        task_frame = ttk.LabelFrame(root, text="任务")
        task_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.task_text = self._scrolled_text(task_frame, height=7, expand=True)

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, pady=8)
        self.run_button = ttk.Button(action_frame, text="运行 Agent", command=self._run_agent)
        self.run_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(action_frame, text="终止", command=self._stop_agent, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=6)
        ttk.Button(action_frame, text="撤销上次文件修改", command=self._undo_change).pack(side=tk.LEFT, padx=6)
        ttk.Button(action_frame, text="清空输出", command=lambda: self.output_text.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=6)

        output_frame = ttk.LabelFrame(root, text="输出")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.output_text = self._scrolled_text(output_frame, height=22, expand=True)

    def _scrolled_text(self, parent: tk.Widget, height: int, expand: bool = False) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH if expand else tk.X, expand=expand, padx=6, pady=6)
        text = tk.Text(frame, height=height, wrap=tk.WORD, undo=True)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        return text

    def _choose_workdir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.workdir_var.get() or str(Path.cwd()))
        if path:
            self.workdir_var.set(path)

    def _mode_changed(self) -> None:
        if self.mode_var.get() == "skill" and not self.task_text.get("1.0", tk.END).strip():
            self.task_text.insert("1.0", SKILL_DISTILL_TASK)

    def _apply_provider(self) -> None:
        provider = self.provider_var.get()
        presets = {
            "Ollama Local": ("http://localhost:11434/v1", "qwen2.5-coder:7b"),
            "LM Studio Local": ("http://localhost:1234/v1", ""),
            "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "DeepSeek": ("https://api.deepseek.com/v1", "deepseek-chat"),
            "Custom API": (self.base_url_var.get(), self.model_var.get()),
        }
        base_url, model = presets[provider]
        self.base_url_var.set(base_url)
        self.model_var.set(model)

    def _import_opencode_json(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 opencode JSON 配置",
            filetypes=(("JSON files", "*.json *.jsonc"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            config = json.loads(self._strip_json_comments(text))
            model = str(config.get("model", ""))
            provider_id, model_id = self._split_model(model)
            provider_map = config.get("provider", {})
            provider = provider_map.get(provider_id, {}) if isinstance(provider_map, dict) and provider_id else {}
            options = provider.get("options", {}) if isinstance(provider, dict) else {}
            base_url = ""
            api_key = ""
            if isinstance(provider, dict):
                base_url = str(options.get("baseURL") or options.get("baseUrl") or provider.get("api", ""))
                api_key = str(options.get("apiKey", "")) if isinstance(options, dict) else ""
            if base_url:
                self.base_url_var.set(base_url)
            if model_id:
                self.model_var.set(model_id)
            elif model:
                self.model_var.set(model)
            if api_key:
                self.api_key_var.set(api_key)
            self.provider_var.set("Custom API")
            self._append_output(f"已导入 opencode 配置：{path}")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)

    def _strip_json_comments(self, text: str) -> str:
        text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    def _split_model(self, model: str) -> tuple[str, str]:
        if "/" not in model:
            return "", model
        provider_id, model_id = model.split("/", 1)
        return provider_id, model_id

    def _refresh_models(self) -> None:
        self._append_output("正在刷新模型列表...")

        def worker() -> None:
            try:
                models = agent.list_models(self.base_url_var.get().strip(), self.api_key_var.get().strip())
                self.after(0, lambda: self._set_models(models))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("刷新模型失败", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _set_models(self, models: list[str]) -> None:
        self.model_combo.configure(values=models)
        if models and not self.model_var.get().strip():
            self.model_var.set(models[0])
        self._append_output(f"已加载 {len(models)} 个模型。")

    def _add_context_file(self) -> None:
        paths = filedialog.askopenfilenames(title="选择上下文文件")
        self.context_files.extend(paths)
        self._refresh_context_paths()

    def _add_context_dir(self) -> None:
        path = filedialog.askdirectory(title="选择上下文目录")
        if path:
            self.context_dirs.append(path)
            self._refresh_context_paths()

    def _clear_context_paths(self) -> None:
        self.context_files.clear()
        self.context_dirs.clear()
        self._refresh_context_paths()

    def _add_skill_file(self) -> None:
        paths = filedialog.askopenfilenames(title="选择 Skill 文件")
        self.skill_files.extend(paths)
        self._refresh_skill_paths()

    def _add_skill_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 Skill 目录")
        if path:
            self.skill_dirs.append(path)
            self._refresh_skill_paths()

    def _clear_skill_paths(self) -> None:
        self.skill_files.clear()
        self.skill_dirs.clear()
        self._refresh_skill_paths()

    def _refresh_skill_paths(self) -> None:
        count = len(self.skill_files) + len(self.skill_dirs)
        self.skill_paths_var.set(f"已选择 {count} 个 Skill 路径" if count else "未选择 Skill 文件或目录")

    def _refresh_context_paths(self) -> None:
        count = len(self.context_files) + len(self.context_dirs)
        self.context_paths_var.set(f"已选择 {count} 个上下文路径" if count else "未选择上下文文件或目录")

    def _append_output(self, text: str) -> None:
        self.output_text.insert(tk.END, text + "\n")
        self.output_text.see(tk.END)

    def _append_stream(self, text: str) -> None:
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)

    def _append_dialog(self, role: str, content: str) -> None:
        labels = {
            "user": "你",
            "assistant": "Agent 准备执行",
            "tool": "执行结果",
            "judge": "LLM 评审",
            "system": "系统",
        }
        label = labels.get(role, role)
        self._append_output(f"\n{label}\n{content}\n")

    def _confirm(self, message: str) -> bool:
        result: list[bool] = []
        event = threading.Event()

        def ask() -> None:
            result.append(messagebox.askyesno("确认 Agent 操作", message, parent=self))
            event.set()

        self.after(0, ask)
        event.wait()
        return bool(result and result[0])

    def _stop_agent(self) -> None:
        self.cancel_requested = True
        self._append_dialog("system", "已请求终止，当前模型请求或工具步骤结束后停止。")

    def _is_cancelled(self) -> bool:
        return self.cancel_requested

    def _undo_change(self) -> None:
        try:
            message = agent.undo_last_change()
        except Exception as exc:
            message = f"撤销失败：{exc}"
        self._append_dialog("system", message)

    def _args(self) -> argparse.Namespace:
        inline_context = self.context_text.get("1.0", tk.END).strip()
        return argparse.Namespace(
            mode=self.mode_var.get(),
            prompt=[],
            context=[inline_context] if inline_context else [],
            context_file=self.context_files[:],
            context_dir=self.context_dirs[:],
            skill_file=self.skill_files[:],
            skill_dir=self.skill_dirs[:],
            no_judge=not self.judge_var.get(),
            yes_write=self.yes_write_var.get(),
            auto_context=self.auto_context_var.get(),
            no_web=not self.web_var.get(),
            no_install=not self.install_var.get(),
            base_url=self.base_url_var.get().strip(),
            model=self.model_var.get().strip(),
            api_key=self.api_key_var.get().strip(),
            workdir=self.workdir_var.get().strip(),
            max_steps=int(self.max_steps_var.get()),
            temperature=float(self.temperature_var.get()),
        )

    def _run_agent(self) -> None:
        task = self.task_text.get("1.0", tk.END).strip()
        if not task:
            messagebox.showerror("缺少任务", "请输入任务。", parent=self)
            return
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.cancel_requested = False
        self._append_dialog("system", "Agent 正在运行...")

        def worker() -> None:
            try:
                args = self._args()
                if args.mode == "code":
                    output = agent.run_code(args, task, self._confirm, lambda role, content: self.after(0, lambda: self._append_dialog(role, content)), self._is_cancelled)
                elif args.mode == "convert":
                    self.after(0, lambda: self._append_dialog("system", "正在流式生成转换结果..."))
                    self.after(0, lambda: self._append_dialog("assistant", ""))
                    output = agent.run_text_mode(args, task, agent.CONVERT_PROMPT, self._confirm, lambda role, content: self.after(0, lambda: self._append_dialog(role, content)), self._is_cancelled, lambda chunk: self.after(0, lambda: self._append_stream(chunk)))
                else:
                    self.after(0, lambda: self._append_dialog("system", "正在流式生成 Skill..."))
                    self.after(0, lambda: self._append_dialog("assistant", ""))
                    output = agent.run_text_mode(args, task, agent.SKILL_PROMPT, self._confirm, lambda role, content: self.after(0, lambda: self._append_dialog(role, content)), self._is_cancelled, lambda chunk: self.after(0, lambda: self._append_stream(chunk)))
            except Exception as exc:
                output = f"error: {exc}"
            self.after(0, lambda: self._finish(output))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, output: str) -> None:
        self._append_dialog("system", output)
        if output.startswith("error:"):
            self._append_dialog("system", "任务已结束：发生错误。")
        elif self.cancel_requested:
            self._append_dialog("system", "任务已结束：用户已终止。")
        else:
            self._append_dialog("system", "任务已结束：输出完成。")
        self.run_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)


def main() -> None:
    HarnessGui().mainloop()


if __name__ == "__main__":
    main()
