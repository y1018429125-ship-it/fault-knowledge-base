# fault-knowledge-base — 故障知识库问答系统

基于向量检索（Qdrant）+ LLM 的输电线路故障报告知识库问答系统，支持线路级/杆塔级故障查询、统计分析与事件卡片提取。

## 环境要求

- Python 3.12
- **需在内网环境**：LLM 与向量服务地址 `172.18.179.2` 仅内网可达
- **需要数据目录**（不在本仓库中，由项目所有者通过 U 盘等方式提供）：
  - `故障报告/` — 故障报告原文（PDF/DOCX）
  - `qdrant_db/` — 向量数据库
  - `pdf_cache/` — PDF 解析缓存
  - `故障报告_WPS备份/` — 报告备份（可选）

## 部署启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 将数据目录放入项目根目录（从 U 盘拷贝）
#    确保项目根目录下存在：故障报告/  qdrant_db/  pdf_cache/

# 3. 启动文件服务（端口 18080，提供报告原文访问）
python src/file_server/server.py

# 4. 启动 API 服务（端口 8503）
python src/interface/api.py

# 5. 启动 Web 问答界面
streamlit run src/interface/app.py
```

## 服务端口

| 端口 | 服务 |
|---|---|
| 8503 | 知识库问答 API |
| 18080 | 报告文件服务 |
| Streamlit 默认 8501 | Web 问答界面 |

## 目录说明

| 目录/文件 | 说明 |
|---|---|
| `src/core/` | 核心模块：解析、切块、检索、路由、生成 |
| `src/interface/` | API 服务与 Streamlit 前端 |
| `src/file_server/` | 报告文件服务 |
| `scripts/` | 数据迁移与索引重建脚本（如 `reindex.py` 重建向量索引） |
| `Project_Skills/` | 统计类查询的 prompt skills |
| `tests/` | 单元测试 |

## 常见问题

- **查询无结果**：检查 `qdrant_db/` 是否已拷贝到项目根目录，且从项目根目录启动服务（代码使用相对路径 `./qdrant_db`）
- **报告原文打不开**：检查 `故障报告/` 目录是否已拷贝，`file_server` 是否已启动
