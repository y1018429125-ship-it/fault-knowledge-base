"""双线报告拆分迁移：一报告两线路（拼接名单卡 → 每线路独立事件卡）。

背景：一报告涉及两条线路时，索引管线按"一报告=一事件"把 line 拼成单值
（如"青林一线、兰林一线"、"胜家ⅠⅡ线"），导致单线路查询不可见、统计口径错误。

通用执行体 + SPECS 数据清单：每份双线报告一条规格，新增报告只需追加 SPECS。
操作（只动规格指定 report_id 的块，其余块零影响）：
- summary 按线路改写文本克隆为独立事件卡（每线路 1 次 Embedding API）
- detail 块按线路克隆（文本不动、复用原向量，仅 payload line 改为各自线路名）
- 删除原拼接名块

幂等：拼接名不存在时该规格跳过。由 reindex.py 末尾自动调用（防全量重建冲掉拆分）。
用法: env_fault/bin/python3 scripts/split_dual_line_report.py [--dry-run]
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import PointStruct  # noqa: E402

from config import QDRANT_PATH  # noqa: E402
from core.embedding import embed_texts  # noqa: E402

_QL_WEATHER = "雷雨强对流大风天气，气温16.9℃～21.2℃，西北风，风力12级，极大风速36.7米/秒，降水量19.9mm。"

_SJ_CAUSE = (
    "本次故障由冰闪引起。主要是现场温差大叠加人工增雨增大湿气，在极端复合气象条件下，"
    "绝缘子迎风侧表面覆着大量冰雪混合物并桥接伞裙，引发湿雪冻融桥接闪络故障。"
)
_SJ_WEATHER = "雨夹雪天气，东风 5 级，气温 0℃左右，湿度 94%。"

SPECS = [
    {
        # 2026-07-04 蒙东 500kV 风偏：青林一线 028号塔 / 兰林一线 029号塔 各 1 起
        "concat_name": "青林一线、兰林一线",
        "report_id": "d0fc4b459a860f88",
        "expected_chunks": 4,  # 1 summary + 3 detail
        "cards": {
            "青林一线": {
                "text": (
                    "线路：青林一线 | 电压：500kV | 故障时间：2026-07-04 14:21:47 | 省份：蒙东\n"
                    "故障类型：风偏\n"
                    "故障杆塔：#028\n"
                    "故障原因：500千伏青林一线028号塔在超设计瞬时强风作用下，导线向塔身侧大角度偏移，击穿空气间隙引发A相单相接地故障跳闸。\n"
                    f"故障时天气：{_QL_WEATHER}\n"
                    "重合闸情况：14时21分47秒跳闸，重合不成功，15时40分试送成功，负荷损失546MW。\n"
                    "概述：2026年07月04日14时21分47秒286毫秒，500千伏青林一线A相（右线）跳闸，重合闸动作，重合不成功，15时40分试送成功，现场雷雨强对流大风天气。"
                ),
                "towers": ["28号"],
            },
            "兰林一线": {
                "text": (
                    "线路：兰林一线 | 电压：500kV | 故障时间：2026-07-04 14:21:53 | 省份：蒙东\n"
                    "故障类型：风偏\n"
                    "故障杆塔：#029\n"
                    "故障原因：500千伏兰林一线029号塔在超设计瞬时强风作用下，导线向塔身侧大角度偏移，击穿空气间隙引发A相单相接地故障跳闸。\n"
                    f"故障时天气：{_QL_WEATHER}\n"
                    "重合闸情况：14时21分53秒跳闸，重合不成功，17时16分试送成功，负荷损失700MW。\n"
                    "概述：2026年07月04日14时21分53秒157毫秒，500千伏兰林一线A相（右线）跳闸，重合闸动作，重合不成功，17时16分试送成功，现场雷雨强对流大风天气。"
                ),
                "towers": ["29号"],
            },
        },
    },
    {
        # 2026-04-09 蒙东 1000kV 冰闪：胜家Ⅰ线 2 次跳闸 / 胜家Ⅱ线 4 次跳闸
        "concat_name": "胜家ⅠⅡ线",
        "report_id": "b334b93c14515361",
        "expected_chunks": 6,  # 1 summary + 5 detail
        "cards": {
            "胜家Ⅰ线": {
                "text": (
                    "线路：胜家Ⅰ线 | 电压：1000kV | 故障时间：2026-04-09 11:40:38 | 省份：蒙东\n"
                    "故障类型：冰闪\n"
                    "故障杆塔：148号、154号\n"
                    f"故障原因：{_SJ_CAUSE}\n"
                    f"故障时天气：{_SJ_WEATHER}\n"
                    "重合闸情况：11时40分38秒第一次跳闸（148号），11时43分30秒第二次跳闸（154号），故障相别均为B相，重合闸动作，重合均成功，故障时负荷87MW。\n"
                    "概述：2026年4月9日11时40分-43分，1000千伏胜家Ⅰ线连续发生2次故障跳闸（148号、154号），故障相别均为B相，重合闸动作，重合均成功。"
                ),
                "towers": ["148号", "154号"],
            },
            "胜家Ⅱ线": {
                "text": (
                    "线路：胜家Ⅱ线 | 电压：1000kV | 故障时间：2026-04-09 11:42:27 | 省份：蒙东\n"
                    "故障类型：冰闪\n"
                    "故障杆塔：151号、154号、148号、203号\n"
                    f"故障原因：{_SJ_CAUSE}\n"
                    f"故障时天气：{_SJ_WEATHER}\n"
                    "重合闸情况：11时42分27秒至11时54分35秒连续发生4次跳闸（151号、154号、148号、203号），故障相别均为C相，重合均成功，故障时负荷68MW；12时11分退出T021、T022开关单相重合闸，16时17分投入。\n"
                    "概述：2026年4月9日11时42分-54分，1000千伏胜家Ⅱ线连续发生4次故障跳闸（151号、154号、148号、203号），故障相别均为C相，重合闸动作，重合均成功。"
                ),
                "towers": ["148号", "151号", "154号", "203号"],
            },
        },
    },
]


def _find_targets(client, concat_name: str) -> list:
    """全量翻页扫描，取 line == 拼接名的块（含向量）。"""
    targets = []
    offset = None
    while True:
        pts, offset = client.scroll(
            collection_name="fault_reports",
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for p in pts:
            if (p.payload or {}).get("line") == concat_name:
                targets.append(p)
        if offset is None:
            break
    return targets


def _split_one(client, spec: dict, dry_run: bool) -> None:
    targets = _find_targets(client, spec["concat_name"])
    if not targets:
        print(f"幂等跳过 [{spec['concat_name']}]：未发现拼接名块（已拆分或不存在）")
        return

    summary_pts = [p for p in targets if p.payload.get("chunk_type") == "summary"]
    detail_pts = [p for p in targets if p.payload.get("chunk_type") != "summary"]
    assert len(targets) == spec["expected_chunks"] and len(summary_pts) == 1, (
        f"[{spec['concat_name']}] 目标块数量异常: {[p.payload.get('chunk_type') for p in targets]}"
    )
    for p in targets:
        assert p.payload.get("report_id") == spec["report_id"], "report_id 不匹配，停手"

    n_new = len(spec["cards"]) + len(detail_pts) * len(spec["cards"])
    print(f"[{spec['concat_name']}] 目标块: {[p.payload.get('chunk_type') for p in targets]}")
    print(f"计划: 新建 {len(spec['cards'])} 张事件卡（重新嵌入）+ {len(detail_pts) * len(spec['cards'])} 个 detail 克隆（复用向量），删除原 {len(targets)} 块")
    if dry_run:
        for line, card in spec["cards"].items():
            print(f"\n--- 新事件卡 [{line}] ---\n{card['text']}")
        print("\n[dry-run] 未执行写入")
        return

    lines = list(spec["cards"].keys())
    vectors = embed_texts([spec["cards"][l]["text"] for l in lines])
    new_points = []
    for line, vec in zip(lines, vectors):
        payload = dict(summary_pts[0].payload)
        payload["line"] = line
        payload["text"] = spec["cards"][line]["text"]
        payload["towers"] = spec["cards"][line]["towers"]
        new_points.append(PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload))
    for dp in detail_pts:
        for line in lines:
            payload = dict(dp.payload)
            payload["line"] = line
            new_points.append(PointStruct(id=str(uuid.uuid4()), vector=dp.vector, payload=payload))

    client.upsert(collection_name="fault_reports", points=new_points)
    client.delete(
        collection_name="fault_reports",
        points_selector=[p.id for p in targets],
    )
    print(f"[{spec['concat_name']}] 拆分完成：新建 {n_new} 块，删除原 {len(targets)} 块")


def main(dry_run: bool | None = None) -> None:
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv
    client = QdrantClient(path=QDRANT_PATH)
    try:
        for spec in SPECS:
            _split_one(client, spec, dry_run)
    finally:
        client.close()


if __name__ == "__main__":
    main()
