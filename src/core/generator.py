"""LLM generator for fault knowledge base answers."""

import json
import os
from typing import Any

import requests

from config import LLM_ENDPOINT, LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT
from core.postprocess import postprocess_answer


SKILL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "Project_Skills",
    "prompt-skills",
)


def load_skill_prompt(skill: str | None) -> str:
    """Load prompt template for a skill."""
    if skill is None:
        skill = "default"

    path = os.path.join(SKILL_DIR, skill, "prompt.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    # Fallback to default
    default_path = os.path.join(SKILL_DIR, "default", "prompt.txt")
    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    return "你是一个输电线路故障知识库助手。请根据上下文回答用户问题。"


def _format_context(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into context string for LLM."""
    parts = []
    for idx, chunk in enumerate(chunks, 1):
        payload = chunk.get("payload", chunk)
        text = payload.get("text", "")
        report_name = payload.get("report_name", "")
        file_url = payload.get("file_server_url", "")
        meta_lines = []
        for k, v in payload.items():
            if k in ("text", "file_server_url"):
                continue
            meta_lines.append(f"{k}: {v}")
        meta = "\n".join(meta_lines)
        parts.append(
            f"[文档片段 {idx}]\n来源文件：{report_name}\n文件链接：{file_url}\n"
            f"引用格式：[{report_name}]({file_url})\n元数据：\n{meta}\n内容：\n{text}\n"
        )
    return "\n".join(parts)


def generate(
    question: str,
    skill: str | None,
    retrieved_chunks: list[dict[str, Any]],
    tower: str | None = None,
    stats_text: str | None = None,
) -> str:
    """Generate an answer using the configured LLM.

    Args:
        question: User question.
        skill: Detected skill name.
        retrieved_chunks: List of retrieved chunks with payload.
        tower: Optional tower number to highlight.
        stats_text: Optional deterministic stats table (程序化预聚合) to
            inject ahead of chunks; counts/rankings must follow it.

    Returns:
        Generated answer string.
    """
    system_prompt = load_skill_prompt(skill)
    context = _format_context(retrieved_chunks)

    user_content = f"用户问题：{question}\n\n"
    if stats_text:
        user_content += f"{stats_text}\n\n"
    user_content += f"检索到的相关文档片段：\n\n{context}"

    response = requests.post(
        LLM_ENDPOINT,
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "stream": False,
        },
        timeout=LLM_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    answer = data["choices"][0]["message"]["content"].strip()
    return postprocess_answer(answer, tower=tower)


def generate_stream(
    question: str,
    skill: str | None,
    retrieved_chunks: list[dict[str, Any]],
    tower: str | None = None,
    stats_text: str | None = None,
):
    """Stream generate an answer."""
    system_prompt = load_skill_prompt(skill)
    context = _format_context(retrieved_chunks)
    user_content = f"用户问题：{question}\n\n"
    if stats_text:
        user_content += f"{stats_text}\n\n"
    user_content += f"检索到的相关文档片段：\n\n{context}"

    response = requests.post(
        LLM_ENDPOINT,
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "stream": True,
        },
        timeout=LLM_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()
    buffer = ""
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if line.startswith("data: "):
            chunk = line[6:]
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
                delta = obj["choices"][0]["delta"].get("content", "")
                if delta:
                    buffer += delta
                    # Yield processed chunks safely
                    if "\n" in buffer:
                        parts = buffer.split("\n")
                        for part in parts[:-1]:
                            yield postprocess_answer(part + "\n", tower=tower)
                        buffer = parts[-1]
            except Exception:
                continue
    if buffer:
        yield postprocess_answer(buffer, tower=tower)
