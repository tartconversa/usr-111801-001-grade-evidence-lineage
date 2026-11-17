import json
import tempfile
import unittest
from pathlib import Path

from exchange import Exchange


class EvidenceLineageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "lineage.db")
        svc = self.service
        svc.catalog.register("src", "资料室", "甲地", "restricted",
                             [("finding", "服务观察", "text", False)], "2026-11-01")
        svc.evidence.register_site("site-1", "云湖景区", "2026-11-01", "资料室")
        svc.evidence.add_item("item-a", "site-1", "A", "现场服务", "2026-11-01", "资料室")
        svc.evidence.add_item("item-b", "site-1", "B", "设施维护", "2026-11-01", "资料室")
        svc.catalog.ingest("a1", "src", {"finding": "指引标识清晰"}, "2026-11-02")
        svc.catalog.ingest("a2", "src", {"finding": "巡检台账完整"}, "2026-11-02")
        svc.evidence.link("a1", "item-a", "2026-11-02", "资料室")
        svc.evidence.link("a2", "item-b", "2026-11-02", "资料室")
        svc.grants.issue("g-1", "src", "复核组", "质量复核", "2026-12-31", "2026-11-03")
        svc.policies.set("甲地", "restricted", "质量复核", "allow", "2026-11-03", "资料室")
        self.rev1 = svc.conclusions.publish(
            "c-1", "site-1", "4A 复核结论",
            {"item-a": ["a1"], "item-b": ["a2"]}, "2026-11-05", "复核组")
        self.assertEqual(self.rev1, 1)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_published_evidence_is_frozen_and_replayable(self):
        replay = self.service.conclusions.replay("c-1", 1)
        self.assertTrue(replay["evidence_set_intact"])
        self.assertEqual(replay["frozen_evidence_digest"], replay["recomputed_evidence_digest"])
        entries = {(e["item_id"], e["asset_id"]) for e in replay["evidence"]}
        self.assertEqual(entries, {("item-a", "a1"), ("item-b", "a2")})
        self.assertIsNone(replay["evidence"][0]["valid_to"])

    def test_correction_only_affects_linked_item(self):
        svc = self.service
        svc.catalog.ingest("a3", "src", {"finding": "指引标识夜间不可见，已补正"}, "2026-11-10")
        svc.evidence.link("a3", "item-a", "2026-11-10", "复核组")
        svc.lineage.correct("a3", "a1", "item-a", "现场照片显示夜间照明不足", "2026-11-10", "复核组")
        self.assertEqual(svc.catalog.get("a1")["state"], "superseded")
        # 影响范围只到挂接的评价项目，不波及同景区其他证据
        self.assertEqual([i["id"] for i in svc.lineage.impact_scope("a1")], ["item-a"])
        self.assertEqual(svc.catalog.get("a2")["state"], "active")

        status = svc.conclusions.status("c-1", 1)
        self.assertFalse(status["usable_now"])
        self.assertEqual(status["need_review_items"], ["item-a"])
        flagged = status["need_review"][0]
        self.assertEqual(flagged["asset_id"], "a1")
        self.assertEqual(flagged["replaced_by"], "a3")
        other = next(e for e in status["evidence"] if e["item_id"] == "item-b")
        self.assertTrue(other["usable"])

        # 历史依据原样可复现：原件未删除，冻结摘要仍一致
        replay = svc.conclusions.replay("c-1", 1)
        self.assertTrue(replay["evidence_set_intact"])
        payloads = {e["asset_id"]: e["payload"] for e in replay["evidence"]}
        self.assertEqual(payloads["a1"], {"finding": "指引标识清晰"})

    def test_new_material_cannot_enter_old_conclusion_republish_makes_new_revision(self):
        svc = self.service
        svc.catalog.ingest("a4", "src", {"finding": "新增暗访记录"}, "2026-11-12")
        svc.evidence.link("a4", "item-a", "2026-11-12", "复核组")
        rev2 = svc.conclusions.publish(
            "c-1", "site-1", "4A 复核结论（修订）",
            {"item-a": ["a4"], "item-b": ["a2"]}, "2026-11-13", "复核组")
        self.assertEqual(rev2, 2)
        revisions = svc.conclusions.list_revisions("c-1")
        self.assertEqual([r["revision"] for r in revisions], [1, 2])
        self.assertEqual(revisions[0]["state"], "superseded")
        self.assertEqual(revisions[1]["state"], "published")
        # 旧修订证据集合不变
        old = svc.conclusions.replay("c-1", 1)
        old_assets = {e["asset_id"] for e in old["evidence"]}
        self.assertEqual(old_assets, {"a1", "a2"})
        self.assertTrue(svc.conclusions.status("c-1", 2)["usable_now"])

    def test_invalidation_flags_review_but_keeps_history(self):
        svc = self.service
        svc.catalog.invalidate("a2", "2026-11-15", "资料室", "台账被发现漏记两次巡检")
        status = svc.conclusions.status("c-1", 1)
        self.assertFalse(status["usable_now"])
        self.assertEqual(status["need_review_items"], ["item-b"])
        self.assertEqual(status["need_review"][0]["reason"], "材料已失效")
        self.assertEqual(svc.catalog.get("a2")["valid_to"], "2026-11-15")
        replay = svc.conclusions.replay("c-1", 1)
        self.assertTrue(replay["evidence_set_intact"])

    def test_supplement_does_not_supersede(self):
        svc = self.service
        svc.catalog.ingest("a5", "src", {"finding": "补充满意度抽样"}, "2026-11-14")
        svc.evidence.link("a5", "item-a", "2026-11-14", "资料室")
        svc.lineage.supplement("a5", "a1", "丰富服务评价样本", "2026-11-14", "资料室")
        self.assertEqual(svc.catalog.get("a1")["state"], "active")
        self.assertTrue(svc.conclusions.status("c-1", 1)["usable_now"])
        relations = svc.lineage.relations_of("a1")
        self.assertEqual([r["kind"] for r in relations], ["supplements"])

    def test_publish_rejects_inactive_or_unlinked_evidence(self):
        svc = self.service
        svc.catalog.invalidate("a2", "2026-11-15", "资料室", "台账存疑")
        with self.assertRaises(ValueError):
            svc.conclusions.publish("c-2", "site-1", "无效证据结论",
                                    {"item-b": ["a2"]}, "2026-11-16", "复核组")
        svc.catalog.ingest("a6", "src", {"finding": "未挂接材料"}, "2026-11-16")
        with self.assertRaises(ValueError):
            svc.conclusions.publish("c-3", "site-1", "挂接不符结论",
                                    {"item-a": ["a6"]}, "2026-11-16", "复核组")

    def test_conclusion_delivery_carries_frozen_snapshot_and_gates(self):
        svc = self.service
        receipt = svc.delivery.send_conclusion("d-c1", "c-1", 1, "复核组", "质量复核", "2026-11-06")
        self.assertEqual(receipt["conclusion_id"], "c-1")
        snapshot = json.loads(receipt["evidence_snapshot"])
        self.assertEqual({s["asset_id"] for s in snapshot}, {"a1", "a2"})
        self.assertTrue(all(s["current_state"] == "active" for s in snapshot))
        self.assertIsNone(snapshot[0]["valid_to"])
        self.assertEqual(receipt["input_digest"], svc.conclusions.replay("c-1", 1)["frozen_evidence_digest"])
        # 幂等：同一编号重复交付返回同一凭据
        self.assertEqual(receipt, svc.delivery.send_conclusion("d-c1", "c-1", 1, "复核组", "质量复核", "2026-11-06"))
        with self.assertRaises(ValueError):
            svc.delivery.send_conclusion("d-c1", "c-1", 1, "其他机构", "质量复核", "2026-11-06")
        # 许可与策略闸门
        with self.assertRaises(PermissionError):
            svc.delivery.send_conclusion("d-c2", "c-1", 1, "陌生机构", "质量复核", "2026-11-06")
        # 材料失效后历史凭据仍可再次出具，快照如实反映当前状态
        svc.catalog.invalidate("a1", "2026-11-18", "资料室", "照片来源存疑")
        receipt2 = svc.delivery.send_conclusion("d-c3", "c-1", 1, "复核组", "质量复核", "2026-11-18")
        snap2 = {s["asset_id"]: s for s in json.loads(receipt2["evidence_snapshot"])}
        self.assertEqual(snap2["a1"]["current_state"], "invalid")
        self.assertEqual(snap2["a1"]["current_valid_to"], "2026-11-18")
        # 冻结的发布时有效区间不变
        self.assertIsNone(snap2["a1"]["valid_to"])
        self.assertTrue(svc.conclusions.replay("c-1", 1)["evidence_set_intact"])


if __name__ == "__main__":
    unittest.main()
