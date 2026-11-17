import argparse
import json

from .service import Exchange


def show(label, value):
    print(f"\n== {label} ==")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def main():
    parser = argparse.ArgumentParser(description="景区资料本地协作演练")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    service = Exchange(args.database)
    try:
        # 1. 来源与字段登记
        service.catalog.register("src", "资料室", "甲地", "review",
                                 [("finding", "服务观察", "text", False)], "2026-11-01")
        # 2. 景区与评价项目
        service.evidence.register_site("site-1", "云湖景区", "2026-11-01", "资料室")
        service.evidence.add_item("item-a", "site-1", "A", "现场服务", "2026-11-01", "资料室")
        service.evidence.add_item("item-b", "site-1", "B", "设施维护", "2026-11-01", "资料室")
        # 3. 原件入库并挂接到评价项目
        service.catalog.ingest("a1", "src", {"finding": "指引标识清晰"}, "2026-11-02")
        service.catalog.ingest("a2", "src", {"finding": "巡检台账完整"}, "2026-11-02")
        service.evidence.link("a1", "item-a", "2026-11-02", "资料室")
        service.evidence.link("a2", "item-b", "2026-11-02", "资料室")
        # 4. 使用许可与策略
        service.grants.issue("g-1", "src", "复核组", "质量复核", "2026-12-31", "2026-11-03")
        service.policies.set("甲地", "review", "质量复核", "allow", "2026-11-03", "资料室")
        # 5. 发布第一版结论（证据集合在此冻结）
        rev1 = service.conclusions.publish(
            "c-1", "site-1", "4A 复核结论",
            {"item-a": ["a1"], "item-b": ["a2"]}, "2026-11-05", "复核组")
        show("发布结论修订 1", {"revision": rev1, "replay": service.conclusions.replay("c-1", rev1)})
        # 6. 交付第一版结论凭据
        receipt = service.delivery.send_conclusion("d-1", "c-1", rev1, "复核组", "质量复核", "2026-11-06")
        show("结论交付凭据", {k: receipt[k] for k in ("id", "conclusion_id", "conclusion_revision", "evidence_snapshot")})
        # 7. 发现现场服务证据有误，补正：只影响项目 A
        service.catalog.ingest("a3", "src", {"finding": "夜间照明不足，指引不可见"}, "2026-11-10")
        service.evidence.link("a3", "item-a", "2026-11-10", "复核组")
        service.lineage.correct("a3", "a1", "item-a", "现场照片与记录不符", "2026-11-10", "复核组")
        show("补正后第一版结论状态（仅项目 A 需复核）", service.conclusions.status("c-1", rev1))
        show("第一版结论历史依据仍可复现", service.conclusions.replay("c-1", rev1))
        # 8. 用补正后的证据发布修订 2；项目 B 证据沿用
        rev2 = service.conclusions.publish(
            "c-1", "site-1", "4A 复核结论（修订）",
            {"item-a": ["a3"], "item-b": ["a2"]}, "2026-11-12", "复核组")
        show("发布结论修订 2", {"revision": rev2, "status": service.conclusions.status("c-1", rev2),
                          "revisions": service.conclusions.list_revisions("c-1")})
        # 9. 设施材料后来失效：只挂到项目 B，项目 A 不受牵连
        service.catalog.invalidate("a2", "2026-11-15", "资料室", "台账漏记两次巡检")
        show("设施材料失效后修订 2 状态", service.conclusions.status("c-1", rev2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
