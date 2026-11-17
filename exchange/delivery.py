import hashlib
import json

from .audit import write
from .grants import Grants
from .policy import Policies
from .products import Products


class Delivery:
    def __init__(self, connection):
        self.connection = connection
        self.grants = Grants(connection)
        self.policies = Policies(connection)
        self.products = Products(connection)

    def send(self, delivery_id, product_id, revision, recipient, purpose, at):
        existing = self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if existing:
            if (existing["product_id"], existing["product_revision"], existing["recipient"], existing["purpose"]) != (product_id, revision, recipient, purpose):
                raise ValueError("交付编号已用于其他请求")
            return dict(existing)
        product = self.connection.execute("SELECT state FROM products WHERE id=? AND revision=?", (product_id, revision)).fetchone()
        if product is None or product["state"] != "draft":
            raise ValueError("数据产品修订不可交付")
        inputs = self.products.inputs(product_id, revision)
        if not inputs:
            raise ValueError("数据产品缺少输入")
        reasons, revisions = [], {}
        for asset in inputs:
            source_id = asset["source_id"]
            if asset["state"] != "active" or not asset["source_active"]:
                reasons.append({"source": source_id, "reason": "inactive"})
            if not self.grants.permits(source_id, recipient, purpose, at):
                reasons.append({"source": source_id, "reason": "grant"})
            decision, policy_revision = self.policies.decision(asset["jurisdiction"], asset["classification"], purpose)
            revisions[source_id] = policy_revision
            if decision != "allow":
                reasons.append({"source": source_id, "reason": "policy"})
        if reasons:
            with self.connection:
                write(self.connection, at, recipient, "delivery.reject", product_id, {"revision": revision, "reasons": reasons})
            raise PermissionError(reasons)
        digest = hashlib.sha256("|".join(asset["digest"] for asset in inputs).encode()).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT INTO deliveries(id,product_id,product_revision,recipient,purpose,created_at,input_digest,policy_revisions) VALUES(?,?,?,?,?,?,?,?)",
                (delivery_id, product_id, revision, recipient, purpose, at, digest, json.dumps(revisions, sort_keys=True)),
            )
            write(self.connection, at, recipient, "delivery.accept", delivery_id, {"product": product_id, "revision": revision, "inputs": [a["id"] for a in inputs]})
        return dict(self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())

    def send_conclusion(self, delivery_id, conclusion_id, revision, recipient, purpose, at):
        """交付结论凭据：证据按发布时冻结清单出具，并记录每份材料的有效范围。"""
        existing = self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if existing:
            if (existing["conclusion_id"], existing["conclusion_revision"], existing["recipient"], existing["purpose"]) != (conclusion_id, revision, recipient, purpose):
                raise ValueError("交付编号已用于其他请求")
            return dict(existing)
        conclusion = self.connection.execute(
            "SELECT * FROM conclusions WHERE id=? AND revision=?", (conclusion_id, revision)
        ).fetchone()
        if conclusion is None:
            raise KeyError((conclusion_id, revision))
        rows = self.connection.execute(
            "SELECT e.*, a.source_id, a.digest, s.owner, s.jurisdiction, s.classification, s.active AS source_active "
            "FROM conclusion_evidence e JOIN assets a ON a.id=e.asset_id JOIN sources s ON s.id=a.source_id "
            "WHERE e.conclusion_id=? AND e.conclusion_revision=? ORDER BY e.item_id,e.asset_id",
            (conclusion_id, revision),
        ).fetchall()
        if not rows:
            raise ValueError("结论缺少证据集合")
        reasons, revisions, snapshot = [], {}, []
        for row in rows:
            source_id = row["source_id"]
            if not row["source_active"]:
                reasons.append({"source": source_id, "reason": "inactive"})
            if not self.grants.permits(source_id, recipient, purpose, at):
                reasons.append({"source": source_id, "reason": "grant"})
            decision, policy_revision = self.policies.decision(row["jurisdiction"], row["classification"], purpose)
            revisions[source_id] = policy_revision
            if decision != "allow":
                reasons.append({"source": source_id, "reason": "policy"})
            current = self.connection.execute("SELECT state,valid_to FROM assets WHERE id=?", (row["asset_id"],)).fetchone()
            snapshot.append({
                "item_id": row["item_id"], "asset_id": row["asset_id"],
                "asset_digest": row["asset_digest"],
                "valid_from": row["valid_from"], "valid_to": row["valid_to"],
                "current_state": current["state"] if current else "missing",
                "current_valid_to": current["valid_to"] if current else None,
            })
        if reasons:
            with self.connection:
                write(self.connection, at, recipient, "delivery.reject", conclusion_id,
                      {"revision": revision, "reasons": reasons})
            raise PermissionError(reasons)
        with self.connection:
            self.connection.execute(
                "INSERT INTO deliveries(id,product_id,product_revision,conclusion_id,conclusion_revision,"
                "recipient,purpose,created_at,input_digest,policy_revisions,evidence_snapshot) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (delivery_id, None, None, conclusion_id, revision, recipient, purpose, at,
                 conclusion["evidence_digest"], json.dumps(revisions, sort_keys=True),
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
            )
            write(self.connection, at, recipient, "delivery.accept", delivery_id,
                  {"conclusion": conclusion_id, "revision": revision,
                   "evidence": [{"item": r["item_id"], "asset": r["asset_id"]} for r in rows]})
        return dict(self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())
