"""Streamlit frontend for fault knowledge base QA.

Usage:
    streamlit run src/interface/app.py
"""

import os
import sys

import requests
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import FILE_SERVER_URL
from core.engine import CLARIFY_PREFIX, query_stream
from core.query_parser import parse_query

EXAMPLE_QUESTIONS = [
    "雅湖线历年情况",
    "复奉线2026年第一季度情况",
    "渔兴线2026年1月情况",
    "雅湖线2025年5月8日情况",
    "复奉线2026年山火故障情况",
    "雅湖线历年雷击情况",
    "雅湖线2024年1-6月情况",
    "2026年1000kV线路情况",
    "2025年800kV线路雷击情况",
    "2026年2-6月，800kV线路情况",
    "湖南历年情况",
    "江苏2026年500kV线路情况",
    "江西2025年雷击情况",
    "江苏2026年舞动情况",
    "江西2025年4-6月800kV线路雷击情况",
]


def check_file_server() -> bool:
    """Check whether the report file server is reachable."""
    try:
        resp = requests.get(f"{FILE_SERVER_URL}/health", timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def main() -> None:
    st.set_page_config(page_title="故障知识库问答", page_icon="⚡", layout="wide")
    st.title("⚡ 输电线路故障知识库问答")

    with st.sidebar:
        st.header("服务状态")
        if check_file_server():
            st.success("文件服务器：在线")
        else:
            st.warning("文件服务器：离线（来源链接暂不可打开）\n\n启动：`python3 src/file_server/server.py`")

        st.header("示例问题")
        for example in EXAMPLE_QUESTIONS:
            if st.button(example, use_container_width=True):
                st.session_state["pending_question"] = example

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("请输入故障查询问题…")
    if "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if question:
        # 时间反问多轮衔接：上一轮系统反问时间段时，若用户回复只是时间补充
        # （本身不含线路名，如“历年”“2024年”），把原问题与补充拼接后重新查询；
        # 若回复本身已是完整查询（含线路名），直接使用，不拼接，避免解析混乱
        origin = st.session_state.pop("clarify_origin", None)
        if origin and not parse_query(question).line:
            query_text = f"{origin}，{question}"
        else:
            query_text = question

        st.session_state["messages"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        if origin:
            with st.chat_message("user"):
                st.caption(f"（已合并上轮问题，实际查询：{query_text}）")

        with st.chat_message("assistant"):
            try:
                answer = st.write_stream(query_stream(query_text, raw_question=question))
            except Exception as exc:
                answer = f"查询失败：{exc}"
                st.error(answer)

        # 回答仍是时间反问时，记录原始问题等待用户补充
        if answer.startswith(CLARIFY_PREFIX):
            st.session_state["clarify_origin"] = query_text

        st.session_state["messages"].append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
