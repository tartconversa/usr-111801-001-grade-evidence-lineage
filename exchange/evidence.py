from .audit import write


class Evidence:
    """景区、评价项目与材料的挂接。材料对结论的影响范围沿挂接传播。"""

    def __init__(self, connection):
        self.connection = connection

    def register_site(self, site_id, name, at, actor):
        with self.connection:
            self.connection.execute(
                "INSERT INTO sites(id,name,created_at) VALUES(?,?,?)",
                (site_id, name, at),
            )
            write(self.connection, at, actor, "site.register", site_id, {"name": name})

    def add_item(self, item_id, site_id, code, name, at, actor):
        site = self.connection.execute("SELECT id FROM sites WHERE id=?", (site_id,)).fetchone()
        if site is None:
            raise KeyError(site_id)
        with self.connection:
            self.connection.execute(
                "INSERT INTO evaluation_items(id,site_id,code,name) VALUES(?,?,?,?)",
                (item_id, site_id, code, name),
            )
            write(self.connection, at, actor, "item.add", item_id, {"site": site_id, "code": code})

    def link(self, asset_id, item_id, at, actor):
        asset = self.connection.execute("SELECT id FROM assets WHERE id=?", (asset_id,)).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        item = self.connection.execute("SELECT id FROM evaluation_items WHERE id=?", (item_id,)).fetchone()
        if item is None:
            raise KeyError(item_id)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO asset_item_links(asset_id,item_id) VALUES(?,?)",
                (asset_id, item_id),
            )
            write(self.connection, at, actor, "asset.link", asset_id, {"item": item_id})

    def items_of_asset(self, asset_id):
        rows = self.connection.execute(
            "SELECT i.* FROM asset_item_links l JOIN evaluation_items i ON i.id=l.item_id "
            "WHERE l.asset_id=? ORDER BY i.code",
            (asset_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def assets_of_item(self, item_id):
        rows = self.connection.execute(
            "SELECT a.* FROM asset_item_links l JOIN assets a ON a.id=l.asset_id "
            "WHERE l.item_id=? ORDER BY a.received_at,a.id",
            (item_id,),
        ).fetchall()
        return [dict(row) for row in rows]
