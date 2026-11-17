from .audit import write


class Lineage:
    """材料间的补正与补充关系。

    corrects（补正）：旧材料转为 superseded，仅对挂接的评价项目失效；
    supplements（补充）：不替代旧材料，只建立血缘，二者都可继续作为证据。
    """

    def __init__(self, connection):
        self.connection = connection

    def _asset(self, asset_id):
        row = self.connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return dict(row)

    def _relation(self, new_asset_id, old_asset_id, kind, item_id, reason, at, actor):
        new_asset = self._asset(new_asset_id)
        old_asset = self._asset(old_asset_id)
        if old_asset["state"] != "active":
            raise ValueError("被补正材料已不在有效状态")
        if new_asset["state"] != "active":
            raise ValueError("新材料必须有效")
        if item_id is None:
            items = self.connection.execute(
                "SELECT item_id FROM asset_item_links WHERE asset_id=?", (old_asset_id,)
            ).fetchall()
            if not items:
                raise ValueError("被补正材料未挂接评价项目，无法限定影响范围")
            scoped = [row["item_id"] for row in items]
        else:
            link = self.connection.execute(
                "SELECT 1 FROM asset_item_links WHERE asset_id=? AND item_id=?",
                (old_asset_id, item_id),
            ).fetchone()
            if link is None:
                raise ValueError("补正评价项目与材料挂接不一致")
            scoped = [item_id]
        with self.connection:
            cur = self.connection.execute(
                "INSERT INTO asset_relations(source_asset_id,target_asset_id,kind,item_id,reason,at,actor) "
                "VALUES(?,?,?,?,?,?,?)",
                (new_asset_id, old_asset_id, kind, item_id, reason, at, actor),
            )
            relation_id = cur.lastrowid
            if kind == "corrects":
                # 旧材料仅在受影响项目上被替代；原件保留，状态标注为被补正
                self.connection.execute(
                    "UPDATE assets SET state='superseded' WHERE id=? AND state='active'",
                    (old_asset_id,),
                )
            write(self.connection, at, actor, f"asset.{kind}", old_asset_id,
                  {"relation_id": relation_id, "new_asset": new_asset_id, "items": scoped, "reason": reason})
        return relation_id

    def correct(self, new_asset_id, old_asset_id, item_id, reason, at, actor):
        return self._relation(new_asset_id, old_asset_id, "corrects", item_id, reason, at, actor)

    def supplement(self, new_asset_id, old_asset_id, reason, at, actor):
        return self._relation(new_asset_id, old_asset_id, "supplements", None, reason, at, actor)

    def relations_of(self, asset_id):
        rows = self.connection.execute(
            "SELECT * FROM asset_relations WHERE source_asset_id=? OR target_asset_id=? ORDER BY id",
            (asset_id, asset_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def impact_scope(self, asset_id):
        """材料失效或被补正时受影响的评价项目；未挂接项目则不波及任何结论。"""
        rows = self.connection.execute(
            "SELECT i.* FROM asset_item_links l JOIN evaluation_items i ON i.id=l.item_id "
            "WHERE l.asset_id=? ORDER BY i.code",
            (asset_id,),
        ).fetchall()
        return [dict(row) for row in rows]
