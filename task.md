# Task：故障知识库文档知识问答 v1

> **本文档定位：任务执行单**。每次派任务时按此模板填写，记录本次任务的上下文、目标、验收标准、验证命令和交付物。
> 系统设计原理、四层优化策略、完整技术实现细节、已知问题与解决方案等基线信息，详见 `requirements.md`。

---

## 何时更新本文档

| 修改场景 | 更新位置 |
|---------|---------|
| 本次修改了哪些文件 | Context → 相关模块/文件 |
| 修改导致已知限制变化 | Context → 已知限制 |
| 新增/修改验证用例或命令 | Acceptance criteria / 验证命令 |
| 修改了技术栈（新增依赖等） | 技术栈速查 |
| 本次任务的验收结果 | Acceptance criteria → 勾选状态 |

> 涉及设计原理、架构决策的变更，**不更新**本文档，更新 `requirements.md`。

---

## Context（背景）

- 仓库定位：Python 独立项目，桌面 `/Users/yfzx/Desktop/故障知识库/` 目录
- 相关模块/文件：PDF/DOC/DOCX/WPS 解析、元数据提取、文档分块、Qdrant 向量库、检索编排、大模型生成、文件服务器、前端界面
- 已知限制：
  - Embedding 复用 bge-m3，OpenAI Compatible API（已验证 Forecast 项目连通）
  - 大模型复用 gemma-4-31B-it，OpenAI Compatible API（已验证 Forecast 项目连通）
  - 向量库使用 Qdrant 本地文件存储
  - 285 份报告中存在 PDF、DOC/DOCX、WPS 多种格式
  - DOC/WPS 需 LibreOffice `soffice` 预处理
  - 项目从零开始，无现有代码可复用
  - 运维单位需统一到省级
  - 电压等级需归一化输出
  - 输出每条事件必须带来源文件超链接
  - 临时分析文件使用后必须删除，保持项目目录简洁

---

## Goal（目标）

基于 285 份输电线路故障报告，构建**故障知识库的第一个核心功能 — 文档知识问答**（v1）。

系统核心能力为基于 Embedding 语义路由 + Skill 化架构回答故障查询问题，支持按线路、杆塔、时间、省份、电压等级、故障类型精准检索并生成可溯源的回答。

**后续扩展预留**：排序统计、对比统计、故障类型归纳、MCP 服务化。当前代码架构需支持 tools 注册机制和接口层分离，为后续扩展预留接入点。

---

## Acceptance criteria（验收标准）

- [x] 285 份报告可被正确解析，PDF 用 pdfplumber，DOCX 用 python-docx，DOC/WPS 用 LibreOffice soffice（WPS 已统一转为 DOCX 入库，原件备份于 `故障报告_WPS备份/`）
- [x] 每块附加完整元数据（年份、季度、月份、日期、省份、线路、电压等级、杆塔号、故障类型、来源文件）
- [x] 省份统一到省级（如湖北超高压公司 → 湖北）
- [x] 电压等级归一化（±800kV → 800kV，500千伏 → 500kV）
- [x] 元数据预筛选 + 向量检索可召回相关文档块
- [x] 线路级查询优先召回含线路信息的块，杆塔级查询通过后处理高亮杆塔号
- [x] 大模型生成的回答按时间排序分点回答，包含准确数值和来源超链接
- [x] `single_line_stats` 能完整还原某线路在某时段的全部故障事件
- [x] `single_tower_stats` 支持条件叠加（线路、年份、杆塔号、故障类型），杆塔号后处理高亮
- [x] `multi_line_stats` 能枚举符合条件的线路清单并聚合
- [x] `ranking_stats` 能输出排序结果并附带具体故障时间
- [x] `compare_stats` 能按不同维度对比并输出表格或分章节结果
- [x] `default` 兜底能处理通用数值提取、线路确认等查询
- [x] Embedding 语义路由：核心 Skill 示例问题正确路由到对应 Skill（相似度 ≥ 0.75），通用问题回退到 `default`
- [x] Prompt Skill 化：`generator` 正确从 `Project_Skills/prompt-skills/` 加载模板
- [x] 提供简单前端界面（Streamlit/Gradio）用于问答测试
- [x] 文件服务器可启动并提供原始报告静态访问

**端到端测试用例**（示例）：

| Skill | 示例问题 | 验证重点 |
|-------|---------|---------|
| `single_line_stats` | "泰吴线2025年雷击故障情况" | 按时间排序列出每次事件的时间、杆塔、概述、来源 |
| `single_line_stats` | "廻津5263线2026年7月故障" | 按月份过滤，列出全部事件 |
| `single_tower_stats` | "泰吴线106号塔2025年雷击故障" | 线路 + 杆塔号 + 故障类型条件叠加 |
| `single_tower_stats` | "泰吴线2025年106号杆塔" | 杆塔号多种表述统一识别 |
| `multi_line_stats` | "2025年湖北500kV线路雷击故障" | 按省份 + 电压 + 故障类型过滤 |
| `multi_line_stats` | "2026年7月国网江苏电力异物短路故障" | 按省份 + 月份 + 故障类型过滤 |
| `ranking_stats` | "2025年湖北遭受雷击故障最多的前三条线路" | Top-3 排序 + 具体时间 |
| `compare_stats` | "2025年湖北雷击和风偏故障哪个更多" | 两类故障数量对比 |
| `default` | "江苏有哪些线路发生过山火" | 通用检索 + 列举 |
| `default` | "这份报告的主要内容是什么" | 通用摘要 |

**Skill 路由验证用例**：

| Skill | 测试问题 | 期望匹配 | 最低相似度 |
|-------|---------|---------|-----------|
| `single_line_stats` | "泰吴线2025年雷击故障情况" | `single_line_stats` | ≥ 0.75 |
| `single_tower_stats` | "泰吴线106号塔2025年雷击故障" | `single_tower_stats` | ≥ 0.75 |
| `multi_line_stats` | "2025年湖北500kV线路雷击故障" | `multi_line_stats` | ≥ 0.75 |
| `ranking_stats` | "2025年湖北雷击故障最多的前三条线路" | `ranking_stats` | ≥ 0.75 |
| `compare_stats` | "2025年湖北雷击和风偏故障哪个更多" | `compare_stats` | ≥ 0.75 |
| `default` | "这份报告的主要内容是什么" | `default` | ≥ 0.75 |

**验证命令**：

```bash
# 以下命令均在项目根目录执行；直接引用 core/router 模块需 PYTHONPATH=src

# 解析测试（任意一份 PDF）
PYTHONPATH=src python3 -c "from core.parser import parse_report; print(parse_report('故障报告/国网江苏电力500kV泰吴线2025年7月15日雷击故障分析报告.pdf'))"

# 元数据提取测试
PYTHONPATH=src python3 -c "from core.metadata import extract_metadata; print(extract_metadata('故障报告/国网江苏电力500kV泰吴线2025年7月15日雷击故障分析报告.pdf'))"

# Skill 路由验证
PYTHONPATH=src python3 -c "from router.semantic_router import route; print(route('泰吴线2025年雷击故障情况'))"

# 单线路查询
PYTHONPATH=src python3 -c "from core.engine import query; print(query('泰吴线2025年雷击故障情况'))"

# 全量重建索引
python3 scripts/reindex.py

# 启动文件服务器
python3 src/file_server/server.py

# 启动前端
streamlit run src/interface/app.py

# 启动知识库 API（FastAPI，端口 8503，供外部项目调用）
python3 src/interface/api.py
```

---

## Constraints（约束）

- [ ] 不泄露 secrets（.env、key、token、credentials）
- [ ] 最小化改动，不重构无关代码
- [ ] 新增依赖需说明必要性
- [ ] 系统组件源码必须存放于 `/Users/yfzx/Desktop/故障知识库/src/`（core、router、interface、file_server）；`tests/`、`scripts/` 按惯例独立顶层
- [ ] 临时分析文件使用后删除
- [ ] 严格遵守 `skills/coding-protocol.md` 的 Scout → Builder → Verifier 流程
- [ ] 影响范围 > 3 个文件，自动触发 `skills/ulw-loop.md` 分轮次推进
- [ ] 不直接复用 Forecast 项目源码，仅参考架构思想

---

## Delivery（必须交付）

1. **计划**：3-7 步执行计划，每步含验证方式
2. **代码改动**：实际新建/修改的文件和内容
3. **关键 diff**：影响最大的改动对比
4. **验证输出**：测试命令的实际运行结果

---

## 附加说明

### 编码规范

- 严格遵守 `skills/coding-protocol.md` 的质量流程
- 长任务按 `skills/ulw-loop.md` 切成多轮，每轮只改 1 个改动点
- 每轮结束必须有验证日志，否则不得进入下一轮

### 技术栈速查

- 语言：Python 3.12
- 依赖管理：venv 虚拟环境（`env_fault`，位于项目目录内）
- PDF 解析：pdfplumber 0.11.9
- DOCX 解析：python-docx
- DOC/WPS 解析：LibreOffice soffice
- 向量数据库：Qdrant（本地文件模式）
  - 客户端：qdrant-client
  - 存储路径：`./qdrant_db/`
- HTTP 请求：requests 2.33.1
- 大模型 API：OpenAI Compatible
  - Endpoint：`http://172.18.179.2:20017/v1/chat/completions`
  - 模型名：`gemma-4-31B-it`
- Embedding：bge-m3
  - Endpoint：`http://172.18.179.2:20013/v1/embeddings`
  - 向量维度：1024
- 前端：Streamlit
- 文件服务器：Python http.server 或 FastAPI
- HTTP API：FastAPI 0.141.1 + uvicorn 0.52.1（2026-08-11 新增，对外服务化第一版）

### 数据来源

- 路径：`/Users/yfzx/Desktop/故障知识库/故障报告/`
- 内容：输电线路故障分析报告（285 份）
- 时间跨度：2012 ~ 2026 年（以 2026 年为主，202 份）
- 格式分布：PDF 220 份，DOC 43 份，DOCX 22 份（含 7 份由 WPS 转换，原件备份于 `故障报告_WPS备份/`）

### 项目目录结构

```
/Users/yfzx/Desktop/故障知识库/
├── 故障报告/                      # 285 份原始报告
├── env_fault/                     # Python 虚拟环境
├── qdrant_db/                     # Qdrant 本地向量库
├── Project_Skills/                # Skill 目录
│   ├── prompt-skills/
│   │   ├── single_line_stats/
│   │   ├── single_tower_stats/
│   │   ├── multi_line_stats/
│   │   ├── ranking_stats/
│   │   ├── compare_stats/
│   │   ├── fault_type_stats/
│   │   └── default/
│   └── test/
│       └── scripts/
├── logs/                          # 运行日志
├── scripts/                       # 工具脚本
│   ├── reindex.py
│   ├── convert_wps.py
│   ├── extract_event_cards.py
│   └── regression.py
├── tests/                         # 测试代码
│   ├── test_parser.py
│   ├── test_metadata.py
│   ├── test_chunker.py
│   ├── test_vector_store.py
│   ├── test_index.py
│   ├── test_retriever.py
│   ├── test_routing.py
│   ├── test_generator.py
│   ├── test_core_skills.py
│   ├── test_end_to_end.py
│   ├── test_ranking.py
│   ├── test_compare.py
│   └── test_fault_type.py
├── src/                           # 系统组件源码目录
│   ├── config.py
│   ├── core/
│   │   ├── parser.py
│   │   ├── metadata.py
│   │   ├── chunker.py
│   │   ├── embedding.py
│   │   ├── vector_store.py
│   │   ├── engine.py
│   │   ├── event_card.py
│   │   ├── qa_logger.py
│   │   ├── query_parser.py
│   │   ├── retriever.py
│   │   ├── postprocess.py
│   │   ├── router_adapter.py
│   │   └── generator.py
│   ├── router/
│   │   └── semantic_router.py
│   ├── file_server/
│   │   └── server.py
│   └── interface/
│       ├── app.py
│       └── api.py                 # FastAPI 对外 HTTP API（端口 8503）
├── 故障报告_WPS备份/              # WPS 原件备份
├── requirements.md                # 需求规格说明书
└── task.md                        # 本文件
```

### 故障类型速查表

主要类型：`雷击`、`异物短路`、`风偏`、`山火`、`鸟害/鸟粪`、`舞动`、`冰害/冰闪`、`脱冰跳跃`、`绕击`、`雪闪`、`断线`、`外力破坏`、`其他`

### 时间查询规则

- `2023年至2025年`：包含 2023、2024、2025 全年
- 季度/月份查询必须同时指定年份
- 未指定年份时默认按 2026 年查询

### 电压等级规则

- `±800千伏` / `±800kV` / `800kV` / `800千伏` → 800kV
- `500kV` / `500千伏` → 500kV
- `1000kV` / `1000千伏` → 1000kV
- 输出统一使用 `数字kV` 格式

### 省份规则

- 运维单位统一归到省级
- "国网湖北电力" / "湖北超高压公司" → 湖北
- "国网江苏电力" / "国网江苏公司" → 江苏

### 入库策略

- **增量入库**：支持后续新增报告的增量入库
- **去重机制**：根据 `report_id`（文件路径 SHA256）去重，避免重复解析
- 业务去重：同一天 + 同一线路 + 同类型 + 同杆塔 = 一次故障事件

### 协作规范（AI 助手执行约束）

**端到端测试授权规则**

端到端测试每次运行可能耗时数分钟，且消耗外部 API 资源（LLM + Embedding）。**未经用户明确授权，不得擅自运行全量端到端测试。**

每次需要运行前，必须询问用户："是否需要运行端到端测试验证？"

日常代码改动后的验证应优先使用轻量级方式：
- 语法检查：`python3 -m py_compile src/xxx.py`
- 单元测试：针对单个函数或模块的独立测试
- 单条用例验证：仅运行一个关心的查询用例

---

## 当前任务状态

- [x] 需求讨论完成
- [x] requirements.md 编写完成
- [x] task.md 编写完成
- [x] 代码开发完成（2026-07-24）
- [x] 全量索引完成：285/285 报告，901 个块（2026-07-24）
- [x] 全量验收测试通过：路由 10/10、问答内容 10/10（2026-07-24）

**v1 已交付。** 验收过程中修复的问题：
1. 路由漏判："线路+年+月"句式相似度不足 → 补充 `single_line_stats/examples.txt` 例句
2. postprocess Bug：Markdown 标题 `## 1.` 被误判为杆塔号 → 修正 `normalize_tower_format` 正则

**2026-07-27 维护轮**：
1. 删除 8 个会清空生产索引的旧测试脚本，新建 `tests/test_acceptance.py`（32 用例、只读、带索引保护断言）
2. 修复 `query_parser._extract_quarters` 中文数字崩溃（"第二季度"等）
3. 修正 2 份错标报告：雅湖线 2023-05-08 → 实为 2025-05-08（改名重入库）；牡方线 2026-05-05 报告删除。索引块数基线 901 → 898
4. 强化 `single_line_stats` / `default` Prompt：ISO 日期、电压必填、故障类型归一化名；补充 `examples.txt` 修复"线路+年份（不带类型）"路由漏判
5. 线路级 8 用例验收 8/8 通过
6. 新增"历年"查询支持（`all_years` 不加年份过滤）+ 无时间线路查询反问机制（engine 返回时间段反问，前端自动拼接用户补充重查）。线路级 10 用例 10/10 通过
7. 历年查询召回完整性：`retriever` 对历年线路查询改走 `fetch_by_filter`（元数据全量拉取，上限 40 块），解决向量 top_k 挤掉事件块问题；前端反问合并逻辑修复（回复含线路名时不拼接）
8. 文件服务器 Word 内联预览：DOC/DOCX 请求即时转 PDF 缓存于 `pdf_cache/`（持久目录），已预转换 65/65 份；转换失败兜底为原文档下载
9. 7 份 WPS 统一改为 PDF 入库（替代原 DOCX 中间格式，原件仍在 `故障报告_WPS备份/`），索引块数基线 898 → 907；来源链接变为原生 PDF 内联打开。新增文档的统一入库流程（PDF 直接用 / Word 转缓存 / WPS 转 PDF+备份）待后续专门开发
10. 历年查询 LLM 超时修复：`fetch_by_filter` 新增 `chunk_types` 参数，历年线路查询只取 summary/event 块（排除 detail 块），上下文 103,081 字符（36 块）→ 18,000 字符（9 块），端到端耗时 >120s 超时 → 55.3s，9 起事件完整
11. 新增 QA 日志：每次问答写一行 JSON 到 `logs/qa.jsonl`（`core/qa_logger.py`），记录原始/合并问题、skill、路由相似度、all_years、分阶段时延（route/parse/retrieve/gen_first_token/gen_total/total）、num_chunks、context_chars、answer 全文、error；`engine.query`/`query_stream` 全路径埋点（含反问/警告/空结果早退），前端传 `raw_question` 区分反问合并

**2026-07-27/28 事件卡改造轮**（ULW 8 轮，解决 summary 块位置截断导致的信息丢失）：

12. 事件卡提取模块 `core/event_card.py`：索引时对每份报告调用 LLM 抽取 7 字段结构化卡片（故障时间/故障杆塔/雷击细分/故障原因/故障时天气/重合闸情况/概述），"短则照抄原文、长则浓缩"；替代旧 `text[:2000]` 位置截断 summary。10 份试提取 10/10 通过
13. 入库接入 + 全量重建：`chunker.chunk_report` 支持 `summary_text_override`；`engine._index_report_with_client` 提取失败降级旧 summary（WARN 日志）。284/284 报告全部生成事件卡，0 降级，索引块数基线 907 → 908（旧库备份于 `qdrant_db_backup_20260727/`）
14. 正文时间优先：`apply_card_datetime` 以卡片"故障时间"覆盖元数据 year/month/quarter/date（精确到秒，正文与文件名冲突时以正文为准，如官熙Ⅰ线文件名 05-21 vs 正文 05-20 18:57:09）
15. 检索分层：列举类技能（multi_line/ranking/compare + 历年 single_line/single_tower）走 `fetch_by_filter(chunk_types=["summary"])` 纯事件卡保证清单完整性；聚焦查询维持向量混合召回（卡 + detail 块）保证单事件细节深度
16. 回答 prompt 模板增强：single_line/single_tower 新增故障原因、故障时天气、重合闸情况必填字段；4 个模板统一"雷击（绕击/反击）"细分标注规则；`LLM_MAX_TOKENS` 2048 → 4096，修复 9 事件历年回答在 max_tokens 处截断（2650 字符 7 条 → 3794 字符 9 条完整）

**2026-07-28 回归验收轮**（轮次 7，`scripts/regression.py`，7 用例）：

17. 路由漏判修复：`single_line_stats/examples.txt` 补 3 例（罗马数字线路+年月句式）、`single_tower_stats/examples.txt` 补 4 例（线路+杆塔号不带时间句式）；两条漏判问题（sim 0.719/0.726 < 0.75）修复后路由正确，既有 8 用例路由回归 10/10 不受影响
18. 生成超时调整：`LLM_TIMEOUT = 300` 写入 config（原硬编码 120s 两处，generate/generate_stream）；根因是 compare_stats 双侧大年份查询召回 47 张事件卡，全量枚举输出在 120s 内无法完成
19. 反问文案修复：`engine._check_missing_time` 杆塔目标"2911号号杆塔"→"2911号杆塔"（`query.tower` 本身已带"号"）；删除临时文件 `logs/event_card_trial.md`；旧索引备份 `qdrant_db_backup_20260727/` 已于 2026-07-29 清理删除

**2026-07-28 程序化预聚合轮**（方案B，根治列举类计数不可靠 + 召回上限截断）：

20. 本地统计验证（`scripts/local_stats.py`）：事件卡 6 个 groupby 字段完整率 100%（284/284）；实锤 2026 雷击 64 张卡超 40 召回上限（compare 回答曾错报 32 次）
21. 检索层：`vector_store.aggregate_summary_line_counts` 全量扫描按线路精确计数（无上限、无 API）；`retriever` 雷击查询统一并入绕击（召回与计数一致）；新增 `build_stats_text`/`retrieve_with_stats`/`retrieve_for_compare_with_stats`
22. 生成层：ranking/compare/multi_line 三技能注入【精确统计】表（总数 + 按线路分布），3 个 prompt 模板规定"次数/排名以统计表为准，禁止自行数卡片"；compare 用例计数 7 vs 32（错）→ 7 vs 69（含绕击 5 次），生成耗时 100.6s → 41.3s（LLM 不再全量枚举卡片）
23. ranking 榜单补拉：排名依据换成全量统计表后，榜单线路的卡可能不在 40 张召回内（回答"暂无具体事件细节"无来源）；修复为聚合后按 top-N 线路（含并列）补拉事件卡并入上下文（report_id 去重）。回归 38/39 → 修复后排序用例 top-3（林朗Ⅱ线/程木1号线/绒甘I线，各 2 次）全部带来源；顺带首次验证真实反击报告（程木1号线 2026-06-09 雷击（反击））
24. 线路名归一（同线异名合并）：`metadata.canonicalize_line_name`（XX直流/XX直流联络线/XX直流I线/XX线极Ⅱ线 → XX线，艳牌I线/江莲二线等独立线路名不误伤）；接入 metadata 两处 + query_parser（新增 XX直流 句式捕获与泛指黑名单）；存量迁移 `scripts/migrate_line_names.py` payload 直改 56 块（无需重嵌入），线路名 195 → 187，锦苏线 13 → 14；compare prompt 强制每侧代表性事件来源链接
25. `LLM_MAX_TOKENS` 4096 → 8192：14 条事件完整格式输出约 5000+ tokens 超 4096 截断（锦苏线历年 13 条+断句 → 14 条完整，含原锦苏直流 2025-08-30 报告）；`single_line_stats/examples.txt` 补 4 条"历年"句式修复锦苏线路由漏判（0.6445）

**2026-07-28 掩码语义路由轮**（根治"XX线历年雷击情况"格式不统一/内容不全）：

26. 掩码语义路由：`query_parser.mask_line_tower` 在向量化前把线路名→"某线"、杆塔号→"某号塔"（杆塔/塔杆整体匹配），router 对例句和问题统一掩码——相似度比较句式结构而非词面，决策仍 100% 由 Embedding 做出（不加硬编码规则）。原漏判 5 条线路"历年雷击"全部修复（统一 0.9134），"复奉直流2025故障"等新句式泛化成功，既有 10 用例路由回归零影响
27. 含数字线路名提取修复：`_extract_line_raw` 字符类放开数字/字母（廻津5263线/程木1号线/强明5423线/黄金2号线原均提取为 None）；X号线词干须含非数字避免误吞杆塔号场景
28. `single_tower_stats/examples.txt` 补 2 条结构模板（某类型/通用"故障情况"后缀）

**2026-07-28 需求差距修复轮**（对照用户重申需求清单的 4 项差距）：

29. 季度/日期过滤接入：`build_query_filter` 三分支（single_line/single_tower、multi_line 组、default）补 `quarters`，multi_line 组与 default 补 `dates`——原解析出的季度/日期从未进入 Qdrant must 过滤（"泰吴线2026年第一季度"曾退化为全年过滤）
30. 单线"最频繁月份"精确统计（方案A）：`aggregate_summary_line_counts` 泛化为 `aggregate_summary_counts(filter, field)`；`retrieve_with_stats` 在查询锁定单线路时统计表改按月份分组（升序"X月 N 次"），排名补拉逻辑仅在线路维度生效；本地验证"2026年泰吴线山火最频繁月份"输出 2月4/3月4/4月2/5月1/6月1
31. 路由例句补充（multi_line_stats）："2025年6月10日全国500kV线路情况"、"2025年第一季度湖北1000kV线路情况"——两个需求示例句式原路由漏判（0.6322/0.7032 < 0.75），补例后 0.9936/0.9929；需求句式路由回归 8/8
32. `requirements.md` 同步重申需求目录：单线历年+故障类型组合、季度/日期过滤示例、雷击并入绕击、800kV=±800kV、多设备=运维单位统计、线路名归一规则、掩码语义路由（§6.4）、程序化预聚合（§6.5）、ranking 统计维度自适应、compare 双侧独立统计表
33. 裸"情况"句式路由修复（方案A）：「XX线2025年5月情况」「XX线2025年5月8日情况」等不带"故障"二字的句式原漂移到 single_tower_stats 或掉 default（三 Skill 三模板导致同类问题输出格式不统一）；`single_line_stats/examples.txt` 补 2 条结构例句后 25 条全量路由回归 25/25（含回归脚本 7 用例 + 需求句式 + 历史漏判边界），全量路由回归仅 4.5s（178ms/条，纯 Embedding 不经 LLM）
34. 线路家族查询扩展（方案A，查询侧词干扩展零迁移）：`metadata.line_stem`（罗马/中文含"回"/阿拉伯含"号"/5P16 式数字字母混合编号剥离）；`vector_store.distinct_line_names` 进程内缓存（首次 scroll 73ms）；`retriever.expand_line_variants` 接入 `build_query_filter` 三分支——查裸名（荆潇线）命中同族全部变体（荆潇II线），查精确变体不扩展，输出按 payload 具体线路名区分。POC 全量 186 名分组无误合并（11 个多成员家族皆真同族）
35. 顺带修复潜伏 bug：multi_line/ranking/compare 分支原不过滤 `line`，"2026年XX线山火最频繁月份"统计的是全部线路（POC 曾虚高 12 次=全库 2026 山火）；修复后复奉线 3月2次、锦忻一二线 2月2次与按线路计数一致。另查明 ranking 例句"泰吴线山火"在库中无数据（合成例句，仅作路由结构用）。扩展后路由回归 28/28

**2026-07-28 线路级单设备终测轮**（13 用例 e2e + 数据侧完备性核对）：

36. 路由补例（仅 txt，零代码）：`single_line_stats/examples.txt` +5 例——季度句式（复奉线2026年第一季度情况）、月日句式（建苏线2024年7月13日情况）、灾种反例×3（山火/冰害/风偏故障情况）。实锤系统性风险：掩码后杆塔例句"某线某号塔YYYY年灾种故障情况"与线路级灾种句式仅差一个 token（复奉线山火曾被 tower 以 0.9293 抢走）；补反例后原 3 条失败句式全部 1.0000 归位，舞动/异物短路泛化探针通过，33 条回归零干扰
37. 终测结论 13/13 产品行为正确：8 条直接通过；渔兴线1月（1 报告含 5 次独立跳闸逐条列出=需求行为）、雅湖线2026Q1雷击（无数据正确秒回）、复奉线季度/山火（重复报告被 LLM 正确合并为 1 事件）初判失败均证实为测试断言问题而非产品问题
38. **已知问题（用户决策：不处理，仅记录）**：全库 284 张事件卡存在 11 组重复报告（23 份）——同报告"千伏/kV"文件名变体×5、不同批次号×3、docx+pdf 双格式×1、陕武线两省上报×1（待人工确认是否真两次跳闸）。影响：【精确统计】按报告卡计数会虚高（极端 1 事件算 3 次，瀛易Ⅱ线风偏）；单设备回答无异常（LLM 实践中稳定合并重复卡并标注来源）。候选方案备查：统计侧按（日期+线路+类型+杆塔）事件键去重；prompt 明示"同一事件多份报告合并并全部列为来源"
39. **待办（优化其他类功能时处理）**：无时间反问目前仅覆盖"带线路名"的查询（线路/杆塔级单设备及带线路名的排序对比句式）；无线路名的多设备/归纳/通用查询无年份时仍静默默认 2026。用户决策：本次不改，待开始优化对应功能类别时再评估是否同样改为反问。已验证反问+多轮拼接全链路正确（engine._check_missing_time + app.py clarify_origin 合并）

**2026-07-28 线路级单设备功能验证完成 + 文档同步轮**：

40. 前端界面优化（app.py）：服务状态精简为"文件服务器：在线"；示例问题全部更换为线路级单设备已验证有数据的问题（雅湖线历年/季度/月/日期/年+类型/历年+类型 6 条）；删除底部旧说明句（含"未指定年份默认 2026 年"过时表述）
41. **里程碑：线路级单设备功能验证全面完成**——8 类需求句式（历年/年/季度/月/日期/季度+类型/年+类型/历年+类型）终测 13/13 产品行为正确；无时间反问链路验证通过；家族扩展（裸名查编号变体）实测生效
42. requirements.md 同步本周全部变更：事件卡分块策略（§4.2）、正文时间优先、无时间反问取代默认 2026（§11.2，无线路名查询的旧逻辑标注为待办）、LLM_MAX_TOKENS=8192/LLM_TIMEOUT=300（§7.2）、重复报告已知问题（§12）、目录结构补 event_card/qa_logger/新脚本（§10）

**2026-07-29 转换字体美化轮**（Word/WPS 转 PDF 字体错乱修复，零源码改动）：

43. 根因：macOS 缺公文字体（方正仿宋_GBK/仿宋_GB2312 等），LibreOffice 转换时随机替换为娃娃体/隶变/圆体/手写体。方案：用户从 Windows 拷贝 4 个基础字体（simfang/simhei/simkai/simsun）存入 `fonts_new/`，安装至 `~/Library/Fonts/` 并用 fonttools 生成 15 个"别名"副本（方正仿宋_GBK/楷体_GB2312/微软雅黑/等线/隶书/魏碑/华文行楷/华文中宋等）使文档指定字体名精确命中。关键坑：别名的 PostScript 名（nameID 6）必须是 ASCII，中文 PS 名会导致 LibreOffice 加载时跳过该字体（macOS CoreText 却能识别，形成"系统可见但 LO 不可见"的假象）。重建产物：`pdf_cache/` 58 份 Word 转 PDF 全部重转；`故障报告/` 7 份 WPS 转 PDF 重转（旧版备份于 `故障报告_旧PDF备份_字体/`，验收后已于当日删除）。验证：65 份全页扫描，丑字体从 800+ 字符/文件降至仅 1 个文件 18 字符残留。后续补 5 个常见变体别名（方正小标宋简体/仿宋GB2312/楷体GB2312/方正楷体简体/方正黑体简体，其中方正小标宋简体正是那 18 字符的真身，补后重转已清零）；"新宋体"无需别名（simsun.ttc 自带 NSimSun 字面）。env_fault 新增依赖：fonttools（仅用于生成别名）。别名清单共 20 个，新文档入库转换自动生效，无需额外操作
44. **待办（设计新增文件入库功能时处理）：Linux 部署的转换环境问题**——项目后续迁移 Linux，文档转换环节需解决：① 安装 libreoffice-writer（--headless 无需图形环境，.doc/.wps 过滤器跨平台自带）；② 字体迁移：fonts_new 4 原始 + ~/Library/Fonts 20 别名共 24 个字体文件拷至 /usr/share/fonts/truetype/ 并 fc-cache -fv（服务器默认零中文字体，不装则转换结果全是替换字体；可用 fc-match 验证，Linux 排查比 macOS 方便）；③ soffice 单实例 profile 锁：并行转换需 -env:UserInstallation 隔离（当前串行无碍）；④ 服务账户对字体目录的读权限。另注意 fonttools 尚未写入 requirements.txt；⑤ **双线报告入库问题**（2026-08-03 用户决策暂缓根治）：一报告涉及两条线路时（如"青林一线、兰林一线"），metadata/事件卡管线按"一报告=一事件"假设把 line 拼成单值，导致两条线路各自查询不可见。既有报告由 reindex 末尾自动跑 `split_dual_line_report.py` 兜底（条目 49）；新增双线报告的根治需事件卡抽取层支持"一报告多事件"schema，待新增文件入库功能开发时详细讨论

**2026-07-29 杆塔级输出格式修复轮**：

45. 杆塔级多事件回答前端塌行修复（纯 txt 改动）：用户实测"雅湖线2911塔2024年情况"内容正确但格式不换行，多轮必现。根因：Streamlit 按 CommonMark 渲染，单 `\n` 软换行被折叠为空格；`single_tower_stats/prompt.txt` 只有一句"输出格式与 single_line_stats 相同"（LLM 看不到那个文件，等于无约束），导致输出格式随事件数漂移——单事件时侥幸输出 `- ` 平铺列表（正常），多事件时输出编号块+缩进纯文本字段行（塌行）。修复：把 single_line_stats 的输出格式示例（编号+加粗 ISO 时间+`- ` 字段列表）原样植入 tower 模板并显式禁止缩进纯文本。实测 3 条全过：2911塔2024（2事件）、2911号塔历年（2事件）、3522号杆塔2025（1事件，统一为编号结构无回归）。同类隐患备查：default、fault_type_stats 两个模板也无格式示例，待优化对应功能时评估

**2026-08-03 错误线路名修复轮**（方案A：修代码+迁移存量，依据 temp_线路名称错误记录.md，已验证其内容属实后执行）：

46. 根因：5 份文件名结构为"单位+日期+电压+线路"（日期在电压前），主提取路径失败落入 `_fallback_extract_line`，叠加两个 bug——① fallback 省份剥离正则 `国网[^\d]{1,10}?(?:电力|公司|司)?` 非贪婪+可选尾组只删"国网"+1字，残留"肃电力/疆电力/北电力"；② `VOLTAGE_PATTERNS` 的 `[千伏]?` 单字符类匹配"500千"留"伏"。修复：metadata.py:171 尾组改强制 `(?:电力|公司|司)`；config.py 电压模式改 `(?:千伏|kV)?`（search 类用法无回归，sub 类用法严格改进）。8 个复现文件名提取全部正确，test_metadata.py exit=0
47. 存量迁移 `scripts/migrate_wrong_line_names.py`（显式映射、--dry-run、幂等）：16 块 payload 直改免重嵌入。王安一线 0→3（原完全查不到）、祁韶线 20→23、吉泉线 2→10、雁淮线 11→13，distinct 线路名 186→183，二次运行幂等跳过。改前备份 `qdrant_db_backup_20260803/`（验收后可删）。temp_线路名称错误记录.md 已删除；`青林一线、兰林一线` 双线报告存疑项维持现状，待用户单独决策（拆两条记录 / line 改列表 / 维持）

**2026-08-03 双线报告拆分轮**（用户决策：一报告算两起故障事件，查"青林线"答青林一线、查"兰林线"答兰林一线）：

48. `scripts/split_dual_line_report.py`（--dry-run、幂等、report_id 断言防误伤）：原拼接名"青林一线、兰林一线"4 块拆分——summary 克隆为 2 张独立事件卡（文本按各自事件改写：青林一线 028号塔 14:21:47.286/15:40 试送/546MW，兰林一线 029号塔 14:21:53.157/17:16 试送/700MW，重新嵌入各调 1 次 API），3 个 detail 各克隆 ×2（文本/向量不动仅改 line），删除原 4 块。仅动该报告 4 块，零代码改动，全库其余 908 块不受影响。结果：总块数 908→912、distinct 183→184；家族扩展天然生效（青林线→青林一线）；两线历年 fetch_by_filter 各命中 1 卡；2026蒙东500kV风偏精确统计按线路计 2 次（青林一线 1 + 兰林一线 1）；二次运行幂等跳过。**已知限制**：metadata 提取代码未改，未来新增双线报告仍会拼接线路名，需事件卡抽取层支持"一报告多事件"schema 方可根治（另立任务评估）
49. 拆分纳入重建后流程（防全量重建冲掉拆分成果）：`reindex.py` 末尾自动调用 `split_dual_line_report.main(dry_run=False)`（幂等，拼接名不存在时跳过）；`--max=0` 集成测试通过（reindex 完成后 split check 正常执行并幂等跳过）。青林/兰林报告的拆分此后在任何全量/增量重建后自动恢复

**2026-08-04 雷击标签归一轮**（用户决策：fault_type 只保留"雷击"一类，绕击/反击降为同义词，细分由事件卡承担）：

50. 背景与根因：绕击/反击在电力专业上同级，但系统内待遇不对称——绕击因文件名偶然用词成为独立 fault_type 标签（全库仅 5 份），反击无标签（14 份全部标雷击，细分仅在事件卡文本）。文件名驱动的标注无法支撑完整三分类，用户决策收敛为单类"雷击"。顺带修复两个查询侧缺陷：`query_parser._extract_fault_type` 无"反击"同义词（问"反击故障"类型过滤失效）；`_build_compare_queries` 把"反击"当字面值过滤（库中无此值，对比查询该侧必返 0）
51. 代码归一（ULW 3 轮）：`config.py` FAULT_TYPES 删"绕击"；`metadata.py` extract_fault_type/extract_all_fault_types 同义词归一（绕击/反击/雷害→雷击，防全量重建复发）；`query_parser.py` 查询侧同规则 + 对比查询归一；`retriever.py` 删除 [雷击,绕击] 归并规则；2 个 prompt.txt 归一化类型名清单删"绕击"。单元用例 20/20 PASS。已知取舍："绕击vs反击"类对比两侧均归一为雷击，无法精确对比（细分不走标签体系）
52. 存量精准重索引（`scripts/reindex_raoji_reports.py`，--dry-run、幂等、report_id 断言、文件缺失拒删）：仅 5 份绕击报告的 14 块删旧后走新管线重建（5 次 LLM 事件卡抽取 + 重新嵌入），其余 280 份报告的块零触达。结果：总块数 912 不变，fault_type 值域只剩 14 个合法值（绕击/反击清零），5 张新卡文本均为标准格式"雷击（绕击）"，二次运行幂等跳过。改前备份 `qdrant_db_backup_20260804/` 及上轮遗留 `qdrant_db_backup_20260803/` 验收后已于当日删除

**2026-08-04 时间范围查询修复轮**（方案A：正则修复，用户前端实测发现问题后分类修复）：

53. 问题分类（4 类）：A 月份区间不解析（"4至7月/3-8月"提取为空，月份过滤失效退化为全年）；B 年份区间部分写法不识别（"2023年至2025年"等"至/到"类不识别，落入默认单年）；C `_extract_tower`/`mask_line_tower` 的数字区间正则误吞时间区间——"2025年3-8月"被当作杆塔区间"3-8号"，掩码后路由被 single_tower_stats 以 0.8448 抢走（线路级问题误入杆塔技能）；D 多年范围查询仍走向量召回（top_k 截断漏事件，"2023年至2025年"漏掉 2025-05-08）
54. 修复（`query_parser.py` 4 函数 + `retriever.py` 1 处）：`_extract_years` 支持连接符类与至/到类区间并展开为年份列表；`_extract_months` 支持区间展开（先扫区间、抹除已命中文本再扫单点，防端点重复捕获）；`_extract_tower`/`mask_line_tower` 预处理先抹除年份区间/ISO 日期/月份区间/年份单点再做杆塔匹配（并拒绝 1900-2100 起始值的年份残留）；`retriever.retrieve` 全量拉取条件从 `all_years` 扩展为 `all_years or 多年份范围`。解析层 24/24 PASS（年份 6 写法、月份 5 写法、单点时间零回归、杆塔解析 7 项、掩码 2 项）
55. 端到端验证 21/21 通过：新功能 R1-R8——多年范围 7 事件齐全（2022 正确排除）、月份范围命中 2025-05-08（修复前"未检索到"）、杆塔+年范围组合下确定性核对正常（2910-2911 区间包含命中、参考信息正确标注实际杆塔号）；回归 L1-L9/T1-T4 与上轮基线一致，既有线路级/杆塔级功能零影响。requirements.md §2.2/§2.3 示例与检索策略、§6.1 过滤字段表已同步

**2026-08-04 胜家ⅠⅡ线双线报告拆分轮**（用户决策：拆分机制通用化，方案2 规格注册表）：

56. 背景：多线路功能验证中发现蒙东"胜家ⅠⅡ线"报告（report_id b334b93c14515361）与青林/兰林同构——一报告两线路，line 拼接为单值。差异点：该报告两线共 6 起跳闸（胜家Ⅰ线 2 起 148/154号 B相 87MW；胜家Ⅱ线 4 起 151/154/148/203号 C相 68MW），青林案为两线各 1 起。拆分目标名经用户特别确认为完整名"胜家Ⅰ线"+"胜家Ⅱ线"（非字面切分的"胜家Ⅰ"+"Ⅱ线"；库中 34 个Ⅰ/Ⅱ线路名全部带"线"后缀，line_stem('Ⅱ线')='' 为退化非法名）
57. `split_dual_line_report.py` 重构为通用执行体 + SPECS 数据清单（方案2）：青林/兰林、胜家两组规格，未来新增双线报告只需追加 SPECS 纯数据；reindex.py 零改动（入口 main() 不变）。执行：新建 2 卡 + 10 detail 克隆，删原 6 块，总块数 912→918、distinct 184→185、2026蒙东1000kV冰闪统计按线路 {胜家Ⅰ线:1, 胜家Ⅱ线:1}。验证：青林组幂等跳过（重构零破坏）、二次运行幂等、e2e 4 条（Ⅰ线/Ⅱ线历年各自独立、胜家线历年家族扩展返回两线、Ⅱ线203号塔杆塔级正确匹配高亮）。备份 `qdrant_db_backup_20260804_shengjia/` 验收后已于当日删除。**机制备注**：双线报告根治仍待事件卡"一报告多事件"schema（条目 44⑤），此前每发现一份只需在 SPECS 加一条

**2026-08-04 多设备路由修复轮**（纯 txt 零代码，先例条目36）：

58. 根因：multi_line_stats 仅 7 条例句且全是"省份+电压+类型"单结构，用户 14 类句式中"XXkV线路情况"（无省份）/"江西历年情况"（无电压类型）/"季度+电压"（无省份）等掩码后骨架无例句覆盖——13/14 低于阈值落 default（无全量拉取/无【精确统计】/无格式约束），1 句误入 compare_stats，清单不完整+计数矛盾+格式漂移全是路由失败的连锁反应。修复：examples.txt 7→19 条（按掩码后骨架覆盖：电压+年/历年/全国/季度/季度+类型、省份+年/历年/电压+历年/电压+季度+类型/月区间）；prompt.txt 优化——补 ISO 时间强制、线路按次数降序、【精确统计】口径优先、防塌行 Markdown 格式示例（task#45 同款）
59. 路由实测 26/26：14 句目标全部归位 multi_line_stats（12 句 ≥0.99）；12 条回归探针（单线/杆塔/排序/对比/灾种归纳）无一被抢。**已知问题（用户决策：记录不修改）**：全量拉取上限 ALL_YEARS_MAX_CHUNKS=40 < "800kV线路历年情况"真值 89 张卡，该查询清单会截断，其余 13 句均在上限内；待后续讨论上限策略

**2026-08-11 对外 HTTP API 上线轮**（v4 服务化第一版，需求来自 PLD 项目后端聚合调用）：

60. 新增 `src/interface/api.py`（FastAPI）：`POST /query` 收 `{"question": "..."}` 返回 `{"answer": "..."}`，直接调用 `engine.query()` 与前端行为一致；`GET /health` 探活；端点为同步 `def` 进 uvicorn 线程池，调用方超时建议 ≥300s（与 LLM_TIMEOUT 对齐）。`config.py` 新增 `API_HOST=0.0.0.0` / `API_PORT=8503`。env_fault 新装 fastapi 0.141.1 + uvicorn 0.52.1。范围外（用户明确否掉）：反问多轮衔接、SSE 流式、CORS（纯后端服务间调用）。验证：`/health` 200；端到端"雅湖线历年情况"返回完整分点答案含来源链接（skill=single_line_stats，total 87.2s），QA 日志埋点完整

**在线服务**：Streamlit 前端 `http://localhost:8502`；文件服务器 `http://localhost:18080`；知识库 API `http://localhost:8503`（FastAPI，供外部项目后端调用，`POST /query`，详见 `src/interface/api.py`）

**后续扩展方向**（见 requirements.md §13）：v2 故障类型自动识别、v3 实时数据接入、v4 MCP 服务化。
