#!/usr/bin/env python3
"""Standalone local-model agent with code, conversion, and skill modes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5-coder:7b"
AUTO_CONTEXT_LIMIT = 80_000
AUTO_CONTEXT_SUFFIXES = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".java", ".cpp", ".c", ".h", ".hpp", ".rs", ".go"}
AUTO_CONTEXT_SKIP_DIRS = {".git", "build", "dist", "node_modules", "__pycache__", ".venv", "venv"}

CONVERT_PROMPT = """You are in Program Language Conversion state.

Convert programs from one language to another while preserving behavior.

Rules:
- Identify source language, target language, runtime assumptions, dependencies, IO behavior, data structures, and edge cases.
- Preserve algorithmic behavior, error handling, numeric semantics, resource ownership, and public APIs where possible.
- Use idiomatic target-language constructs without changing observable behavior.
- If language features have no direct equivalent, explain the mapping and tradeoff.
- Use supplied context and local files as requirements for the conversion.
- Before final output, self-check completeness, compilability, dependency mapping, edge cases, and style.
- Revise weak sections before answering.
"""

SKILL_PROMPT = """You are in Skill Distillation and Plugin state.

Distill reusable skills from user-provided context, examples, workflows, code, or documents. Generate a portable skill, or explain how to insert a supplied skill as a plugin into this agent's workflow.

Rules:
- Extract the trigger conditions, purpose, constraints, workflow, tools, inputs, outputs, examples, and quality checks.
- Generate a concise skill artifact in Markdown by default.
- Include frontmatter with name and description when producing a standalone skill file.
- If the user asks to insert a skill as a plugin, produce the exact file content and where it should be placed, or use code mode if local files must be changed.
- Prefer deterministic, reusable instructions over vague advice.
- Self-check that the skill is specific, triggerable, non-overlapping, and safe.
"""

JUDGE_PROMPT = """You are an LLM-as-a-judge quality gate.

Evaluate the candidate answer against the task, supplied context, active skills, and mode rules.

Check:
- Requirement coverage
- Correctness and behavior preservation
- Missing edge cases or unsafe assumptions
- Consistency with active skills
- Clarity and actionability

If the candidate is acceptable, answer exactly:
PASS

If it needs correction, answer with a revised final answer only.
"""

CODE_PROMPT = """You are in Code Implementation state.

You can inspect and modify local files by emitting exactly one JSON action per response.
Do not use Markdown fences around actions.
Use the user task, supplied context, local workspace files, and local model reasoning first.
Web browsing and package installation are available by default unless the runtime disables them.

Allowed actions:
{"action":"read","path":"relative/path"}
{"action":"write","path":"relative/path","content":"full file content"}
{"action":"append","path":"relative/path","content":"content to append"}
{"action":"delete","path":"relative/path"}
{"action":"list","path":"relative/path"}
{"action":"python_compile","path":"relative/python_file.py"}
{"action":"fetch_url","url":"https://example.com/reference"}
{"action":"install","command":"pip install package-name"}
{"action":"final","message":"summary for the user"}

Rules:
- Build context first before editing.
- Treat supplied context as the source of requirements for what must be changed.
- Prefer local context documents over web references.
- Use fetch_url only when references are needed and web access is not disabled.
- Use install only when missing dependencies are required and package installation is not disabled.
- Prefer the smallest correct root-cause change.
- Preserve unrelated user changes.
- After each change, reinforce quality by reviewing the file or running targeted validation.
- If validation or self-review finds defects, correct them and repeat.
- Finish only with a final action when work is complete or blocked.
"""


class AgentError(Exception):
    pass


def load_context(args: argparse.Namespace, root: Path | None = None, callback: ConfirmCallback | None = None) -> str:
    chunks = []
    if root and getattr(args, "auto_context", True):
        auto_context = load_workspace_context(root)
        if auto_context:
            chunks.append(auto_context)
    for index, text in enumerate(args.context, start=1):
        if text.strip():
            chunks.append(f"[inline context {index}]\n{text.strip()}")
    base = root or Path.cwd().resolve()
    for file_name in args.context_file:
        path = resolve_action_path(base, file_name, "read", callback)
        if not path.is_file():
            raise AgentError(f"Context file not found: {file_name}")
        chunks.append(f"[context file: {path.name}]\n{path.read_text(encoding='utf-8')}")
    for directory_name in args.context_dir:
        directory = resolve_action_path(base, directory_name, "list", callback)
        if not directory.is_dir():
            raise AgentError(f"Context directory not found: {directory_name}")
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml"}:
                chunks.append(f"[context file: {path.relative_to(directory)}]\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


def load_workspace_context(root: Path) -> str:
    chunks = ["[auto workspace context]"]
    total = 0
    files = []
    for path in sorted(root.rglob("*")):
        if any(part in AUTO_CONTEXT_SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.suffix.lower() in AUTO_CONTEXT_SUFFIXES:
            files.append(path)
    chunks.append("Files:\n" + "\n".join(str(path.relative_to(root)) for path in files[:200]))
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        section = f"\n[file: {path.relative_to(root)}]\n{text}"
        if total + len(section) > AUTO_CONTEXT_LIMIT:
            chunks.append("\n[auto context truncated]")
            break
        chunks.append(section)
        total += len(section)
    return "\n".join(chunks)


def load_skills(args: argparse.Namespace, root: Path | None = None, callback: ConfirmCallback | None = None) -> str:
    chunks = []
    base = root or Path.cwd().resolve()
    for file_name in args.skill_file:
        path = resolve_action_path(base, file_name, "read", callback)
        if not path.is_file():
            raise AgentError(f"Skill file not found: {file_name}")
        chunks.append(f"[skill file: {path.name}]\n{path.read_text(encoding='utf-8')}")
    for directory_name in args.skill_dir:
        directory = resolve_action_path(base, directory_name, "list", callback)
        if not directory.is_dir():
            raise AgentError(f"Skill directory not found: {directory_name}")
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
                chunks.append(f"[skill file: {path.relative_to(directory)}]\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


def judge_answer(args: argparse.Namespace, mode: str, task: str, context: str, skills: str, candidate: str) -> str:
    if args.no_judge:
        return candidate
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": (
                f"Mode: {mode}\nTask:\n{task}\n\nContext:\n{context or '(none)'}\n\n"
                f"Active skills:\n{skills or '(none)'}\n\nCandidate answer:\n{candidate}"
            ),
        },
    ]
    verdict = chat(args.base_url, args.model, messages, args.temperature, args.api_key).strip()
    return candidate if verdict == "PASS" else verdict


def auth_headers(api_key: str = "") -> dict[str, str]:
    token = api_key.strip() or "local"
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def list_models(base_url: str, api_key: str = "") -> list[str]:
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(url, headers=auth_headers(api_key), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise AgentError(f"Model list request failed: {exc}") from exc
    models = payload.get("data", [])
    ids = [str(item.get("id")) for item in models if item.get("id")]
    if not ids:
        raise AgentError(f"No models found in response: {payload}")
    return sorted(ids)


def chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    api_key: str = "",
    stream_callback: "StreamCallback | None" = None,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream_callback is not None,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=auth_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            if stream_callback:
                return read_stream(response, stream_callback)
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise AgentError(f"Local model request failed: {exc}") from exc
    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AgentError(f"Unexpected model response: {payload}") from exc


def read_stream(response: Any, stream_callback: "StreamCallback") -> str:
    chunks = []
    saw_content = False
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            payload = json.loads(data)
            delta = payload["choices"][0].get("delta", {})
            content = delta.get("content", "")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            content = ""
        if content:
            saw_content = True
            chunks.append(content)
            stream_callback(content)
    if not saw_content:
        stream_callback("\n[未收到可显示的流式文本增量]\n")
    return "".join(chunks).strip()


ConfirmCallback = Callable[[str], bool]
EventCallback = Callable[[str, str], None]
CancelCallback = Callable[[], bool]
StreamCallback = Callable[[str], None]


UNDO_STACK: list[tuple[Path, str | None]] = []


def emit(callback: EventCallback | None, role: str, content: str) -> None:
    if callback:
        callback(role, content)


def ensure_not_cancelled(callback: CancelCallback | None = None) -> None:
    if callback and callback():
        raise AgentError("Operation cancelled by user.")


def snapshot_path(path: Path) -> None:
    if path.exists() and path.is_file():
        UNDO_STACK.append((path, path.read_text(encoding="utf-8")))
    else:
        UNDO_STACK.append((path, None))


def undo_last_change() -> str:
    if not UNDO_STACK:
        return "没有可撤销的文件修改。"
    path, previous = UNDO_STACK.pop()
    if previous is None:
        if path.exists() and path.is_file():
            path.unlink()
        return f"已撤销：删除新建文件 {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(previous, encoding="utf-8")
    return f"已撤销：恢复 {path}"


def confirm(message: str, callback: ConfirmCallback | None = None) -> bool:
    if callback:
        return callback(message)
    raise AgentError(f"Confirmation callback required: {message}")


def is_inside(root: Path, path: Path) -> bool:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    return resolved_root in [resolved_path, *resolved_path.parents]


def safe_path(root: Path, requested: str) -> Path:
    path = (root / requested).resolve()
    if not is_inside(root, path):
        raise AgentError(f"Refusing path outside workspace: {requested}")
    return path


def resolve_action_path(root: Path, requested: str, operation: str, callback: ConfirmCallback | None = None, yes_write: bool = False) -> Path:
    raw = Path(requested)
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    outside = not is_inside(root, path)
    if outside and not confirm(f"Allow {operation} outside workspace: {path}?", callback):
        raise AgentError(f"User denied external path access: {path}")
    if operation in {"write", "delete"} and not (yes_write and not outside) and not confirm(f"Allow {operation} file: {path}?", callback):
        raise AgentError(f"User denied {operation}: {path}")
    return path


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        raise AgentError(f"Model did not return a JSON action: {text}")
    return json.loads(match.group(0))


def extract_actions(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    actions = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict) and "action" in value:
            actions.append(value)
        index = start + end
    if actions:
        return actions
    return [extract_json(text)]


def action_summary(action: dict[str, Any]) -> str:
    name = str(action.get("action", "unknown"))
    if name in {"read", "write", "append", "delete", "list", "python_compile"}:
        return f"{name}: {action.get('path', '')}"
    if name == "fetch_url":
        return f"fetch_url: {action.get('url', '')}"
    if name == "install":
        return f"install: {action.get('command', '')}"
    if name == "final":
        return "final answer"
    return name


def action_progress(action: dict[str, Any]) -> str:
    name = str(action.get("action", "unknown"))
    if name == "read":
        return f"正在读取文件：{action.get('path', '')}"
    if name == "write":
        return f"正在写入文件：{action.get('path', '')}"
    if name == "append":
        return f"正在追加内容：{action.get('path', '')}"
    if name == "delete":
        return f"正在删除文件：{action.get('path', '')}"
    if name == "list":
        return f"正在查看目录：{action.get('path', '.')}"
    if name == "python_compile":
        return f"正在检查 Python 语法：{action.get('path', '')}"
    if name == "fetch_url":
        return f"正在读取网页参考：{action.get('url', '')}"
    if name == "install":
        return f"正在安装依赖：{action.get('command', '')}"
    if name == "final":
        return "正在整理最终结果。"
    return f"正在执行动作：{name}"


def fetch_url(url: str) -> str:
    if not url.startswith(("https://", "http://")):
        raise AgentError(f"Unsupported URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "workflow-agent/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read(500_000)
    except urllib.error.URLError as exc:
        raise AgentError(f"URL fetch failed: {exc}") from exc
    text = data.decode("utf-8", errors="replace")
    return f"Content-Type: {content_type}\n\n{text}"


def install_package(command: str, root: Path) -> str:
    allowed_prefixes = (
        "pip install ",
        "python -m pip install ",
        "npm install ",
        "pnpm add ",
        "yarn add ",
        "cargo add ",
        "go get ",
    )
    normalized = command.strip()
    if not normalized.lower().startswith(allowed_prefixes):
        raise AgentError(f"Unsupported install command: {command}")
    result = subprocess.run(normalized, cwd=root, shell=True, text=True, capture_output=True, timeout=600)
    output = (result.stdout + result.stderr).strip()
    return f"exit={result.returncode}\n{output}"


def run_action(action: dict[str, Any], root: Path, args: argparse.Namespace, callback: ConfirmCallback | None = None) -> tuple[bool, str]:
    name = action.get("action")
    if name == "final":
        return True, str(action.get("message", ""))
    if name == "read":
        path = resolve_action_path(root, str(action["path"]), "read", callback, args.yes_write)
        return False, path.read_text(encoding="utf-8")
    if name == "write":
        path = resolve_action_path(root, str(action["path"]), "write", callback, args.yes_write)
        snapshot_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(action.get("content", "")), encoding="utf-8")
        return False, f"Wrote {path}"
    if name == "append":
        path = resolve_action_path(root, str(action["path"]), "write", callback, args.yes_write)
        snapshot_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(str(action.get("content", "")))
        return False, f"Appended {path}"
    if name == "delete":
        path = resolve_action_path(root, str(action["path"]), "delete", callback, args.yes_write)
        if path.is_dir():
            raise AgentError("Directory deletion is not supported by this safe tool.")
        if path.exists():
            snapshot_path(path)
            path.unlink()
        return False, f"Deleted {path}"
    if name == "list":
        path = resolve_action_path(root, str(action.get("path", ".")), "list", callback, args.yes_write)
        entries = sorted(item.name + ("/" if item.is_dir() else "") for item in path.iterdir())
        return False, "\n".join(entries)
    if name == "python_compile":
        path = resolve_action_path(root, str(action["path"]), "read", callback, args.yes_write)
        if path.suffix != ".py":
            raise AgentError("python_compile only accepts .py files.")
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            return False, f"Python syntax error in {path.relative_to(root)}: {exc}"
        return False, f"Python syntax ok: {path.relative_to(root)}"
    if name == "fetch_url":
        if args.no_web:
            raise AgentError("fetch_url is disabled by --no-web.")
        return False, fetch_url(str(action["url"]))
    if name == "install":
        if args.no_install:
            raise AgentError("install is disabled by --no-install.")
        return False, install_package(str(action["command"]), root)
    raise AgentError(f"Unknown action: {name}")


def run_text_mode(
    args: argparse.Namespace,
    text: str,
    system_prompt: str,
    callback: ConfirmCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_callback: CancelCallback | None = None,
    stream_callback: StreamCallback | None = None,
) -> str:
    ensure_not_cancelled(cancel_callback)
    context = load_context(args, callback=callback)
    skills = load_skills(args, callback=callback) if system_prompt == CONVERT_PROMPT else ""
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    if context:
        messages.append({"role": "user", "content": f"Additional context:\n{context}"})
    if skills:
        messages.append({"role": "user", "content": f"Active skills to apply:\n{skills}"})
    messages.append({"role": "user", "content": text})
    emit(event_callback, "user", text)
    ensure_not_cancelled(cancel_callback)
    candidate = chat(args.base_url, args.model, messages, args.temperature, args.api_key, stream_callback)
    if not stream_callback:
        emit(event_callback, "assistant", candidate)
    mode = "convert" if system_prompt == CONVERT_PROMPT else "skill"
    judged = judge_answer(args, mode, text, context, skills, candidate)
    if judged != candidate:
        emit(event_callback, "judge", judged)
    return judged


def run_code(
    args: argparse.Namespace,
    text: str,
    callback: ConfirmCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> str:
    ensure_not_cancelled(cancel_callback)
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    context = load_context(args, root, callback)
    skills = load_skills(args, root, callback)
    capabilities = ["local file operations", "python syntax checks"]
    if not args.no_web:
        capabilities.append("external web references via fetch_url")
    if not args.no_install:
        capabilities.append("package installation via install")
    user_content = f"Workspace: {root}\nEnabled capabilities: {', '.join(capabilities)}\nTask: {text}"
    if context:
        user_content += f"\n\nSupplied context that defines or constrains required changes:\n{context}"
    if skills:
        user_content += f"\n\nActive skills that must be applied during implementation:\n{skills}"
    messages = [
        {"role": "system", "content": CODE_PROMPT},
        {"role": "user", "content": user_content},
    ]
    emit(event_callback, "user", text)
    for step in range(1, args.max_steps + 1):
        ensure_not_cancelled(cancel_callback)
        emit(event_callback, "system", f"第 {step} 步：正在请求模型分析下一步操作...")
        response = chat(args.base_url, args.model, messages, args.temperature, args.api_key)
        messages.append({"role": "assistant", "content": response})
        observations = []
        try:
            emit(event_callback, "system", f"第 {step} 步：正在解析模型计划...")
            actions = extract_actions(response)
        except Exception as exc:
            actions = []
            observations.append(f"Action parsing failed at step {step}: {exc}. Return one valid JSON action or several adjacent JSON actions.")
        for action in actions:
            ensure_not_cancelled(cancel_callback)
            emit(event_callback, "assistant", action_progress(action))
            try:
                done, observation = run_action(action, root, args, callback)
            except Exception as exc:
                observation = f"Action failed at step {step}: {exc}. Correct the action and continue."
                done = False
            observations.append(observation)
            emit(event_callback, "tool", observation)
            if done:
                emit(event_callback, "system", "正在进行 LLM-as-a-judge 质量评审...")
                judged = judge_answer(args, "code", text, context, skills, observation)
                if judged != observation:
                    emit(event_callback, "judge", judged)
                return judged
        messages.append({"role": "user", "content": f"Observation from step {step}:\n" + "\n\n".join(observations)})
    raise AgentError("Reached max steps before final answer.")
