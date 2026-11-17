import hashlib
import json

from .audit import write


class Conclusions:
    """评级结论及其证据集合。

    发布时把每份证据的摘要与有效区间冻结到 conclusion_evidence：
    此后材料的状态变化不会改写历史证据，新增材料也不会进入旧结论；
    重新发布只能产生新修订，并把上一修订标记为 superseded。
    """

    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _evidence_digest(entries):
        canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def publish(self, conclusion_id, site_id, title, evidence, at, actor):
        if not evidence or not any(evidence.values()):
            raise ValueError("结论缺少证据集合")
        site = self.connection.execute("SELECT id FROM sites WHERE id=?", (site_id,)).fetchone()
        if site is None:
            raise KeyError(site_id)
        frozen = []
        for item_id, asset_ids in evidence.items():
            item = self.connection.execute(
                "SELECT id FROM evaluation_items WHERE id=? AND site_id=?", (item_id, site_id)
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            for asset_id in dict.fromkeys(asset_ids):
                asset = self.connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
                if asset is None:
                    raise KeyError(asset_id)
                if asset["state"] != "active":
                    raise ValueError(f"材料 {asset_id} 不在有效状态，不能进入结论")
                link = self.connection.execute(
                    "SELECT 1 FROM asset_item_links WHERE asset_id=? AND item_id=?",
                    (asset_id, item_id),
                ).fetchone()
                if link is None:
                    raise ValueError(f"材料 {asset_id} 未挂接评价项目 {item_id}")
                frozen.append([item_id, asset_id, asset["digest"], asset["received_at"], asset["valid_to"]])
        frozen.sort(key=lambda entry: (entry[0], entry[1]))
        digest = self._evidence_digest(frozen)
        revision = self.connection.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM conclusions WHERE id=?", (conclusion_id,)
        ).fetchone()[0]
        with self.connection:
            self.connection.execute(
                "INSERT INTO conclusions(id,revision,site_id,title,published_at,evidence_digest) "
                "VALUES(?,?,?,?,?,?)",
                (conclusion_id, revision, site_id, title, at, digest),
            )
            self.connection.execute(
                "UPDATE conclusions SET state='superseded', superseded_at=? "
                "WHERE id=? AND revision<>?",
                (at, conclusion_id, revision),
            )
            self.connection.executemany(
                "INSERT INTO conclusion_evidence"
                "(conclusion_id,conclusion_revision,item_id,asset_id,asset_digest,valid_from,valid_to) "
                "VALUES(?,?,?,?,?,?,?)",
                [(conclusion_id, revision, item_id, asset_id, asset_digest, valid_from, valid_to)
                 for item_id, asset_id, asset_digest, valid_from, valid_to in frozen],
            )
            write(self.connection, at, actor, "conclusion.publish", conclusion_id,
                  {"revision": revision, "site": site_id, "evidence_count": len(frozen)})
        return revision

    def _load(self, conclusion_id, revision):
        conclusion = self.connection.execute(
            "SELECT * FROM conclusions WHERE id=? AND revision=?", (conclusion_id, revision)
        ).fetchone()
        if conclusion is None:
            raise KeyError((conclusion_id, revision))
        rows = self.connection.execute(
            "SELECT * FROM conclusion_evidence WHERE conclusion_id=? AND conclusion_revision=? "
            "ORDER BY item_id,asset_id",
            (conclusion_id, revision),
        ).fetchall()
        return dict(conclusion), [dict(row) for row in rows]

    def list_revisions(self, conclusion_id):
        rows = self.connection.execute(
            "SELECT revision,state,title,published_at,superseded_at,evidence_digest "
            "FROM conclusions WHERE id=? ORDER BY revision",
            (conclusion_id,),
        ).fetchall()
        if not rows:
            raise KeyError(conclusion_id)
        return [dict(row) for row in rows]

    def replay(self, conclusion_id, revision):
        """按冻结清单重新计算摘要，证明历史结论依据的内容仍可原样复现。"""
        conclusion, evidence = self._load(conclusion_id, revision)
        replayed, checks = [], []
        for row in evidence:
            asset = self.connection.execute(
                "SELECT digest,payload,state FROM assets WHERE id=?", (row["asset_id"],)
            ).fetchone()
            if asset is None:
                current_digest, payload, state = None, None, "missing"
            else:
                current_digest, payload, state = asset["digest"], json.loads(asset["payload"]), asset["state"]
            match = current_digest == row["asset_digest"]
            checks.append(match)
            replayed.append({
                "item_id": row["item_id"], "asset_id": row["asset_id"],
                "frozen_digest": row["asset_digest"], "current_digest": current_digest,
                "payload_matches_frozen": match,
                "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                "current_state": state, "payload": payload,
            })
        recomputed = self._evidence_digest([
            [row["item_id"], row["asset_id"], row["asset_digest"], row["valid_from"], row["valid_to"]]
            for row in evidence
        ])
        return {
            "conclusion_id": conclusion_id, "revision": revision,
            "title": conclusion["title"], "state": conclusion["state"],
            "published_at": conclusion["published_at"], "superseded_at": conclusion["superseded_at"],
            "frozen_evidence_digest": conclusion["evidence_digest"],
            "recomputed_evidence_digest": recomputed,
            "evidence_set_intact": recomputed == conclusion["evidence_digest"] and all(checks),
            "evidence": replayed,
        }

    def status(self, conclusion_id, revision):
        """计算结论当前可用性：失效只挂到对应评价项目，其他项目证据不受牵连。"""
        conclusion, evidence = self._load(conclusion_id, revision)
        details, need_review = [], []
        for row in evidence:
            asset = self.connection.execute(
                "SELECT state FROM assets WHERE id=?", (row["asset_id"],)
            ).fetchone()
            state = asset["state"] if asset else "missing"
            entry = {
                "item_id": row["item_id"], "asset_id": row["asset_id"],
                "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                "current_state": state, "usable": state == "active",
            }
            if state != "active":
                if state == "superseded":
                    relation = self.connection.execute(
                        "SELECT source_asset_id,reason FROM asset_relations "
                        "WHERE target_asset_id=? AND kind='corrects' ORDER BY id LIMIT 1",
                        (row["asset_id"],),
                    ).fetchone()
                    entry["reason"] = "材料已被补正"
                    entry["replaced_by"] = relation["source_asset_id"] if relation else None
                elif state == "invalid":
                    entry["reason"] = "材料已失效"
                else:
                    entry["reason"] = "材料缺失"
                need_review.append(entry)
            details.append(entry)
        return {
            "conclusion_id": conclusion_id, "revision": revision,
            "title": conclusion["title"], "state": conclusion["state"],
            "published_at": conclusion["published_at"], "superseded_at": conclusion["superseded_at"],
            "usable_now": not need_review,
            "need_review_items": sorted({entry["item_id"] for entry in need_review}),
            "need_review": need_review, "evidence": details,
        }
