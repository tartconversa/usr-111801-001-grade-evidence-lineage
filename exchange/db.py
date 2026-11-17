import sqlite3


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, jurisdiction TEXT NOT NULL,
    classification TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS fields (
    source_id TEXT NOT NULL REFERENCES sources(id), name TEXT NOT NULL,
    meaning TEXT NOT NULL, kind TEXT NOT NULL, sensitive INTEGER NOT NULL,
    PRIMARY KEY(source_id,name)
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    schema_version INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
    received_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active',
    valid_to TEXT
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    recipient TEXT NOT NULL, purpose TEXT NOT NULL, valid_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS policies (
    jurisdiction TEXT NOT NULL, classification TEXT NOT NULL, purpose TEXT NOT NULL,
    decision TEXT NOT NULL, revision INTEGER NOT NULL,
    PRIMARY KEY(jurisdiction,classification,purpose)
);
CREATE TABLE IF NOT EXISTS products (
    id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
    PRIMARY KEY(id,revision)
);
CREATE TABLE IF NOT EXISTS product_inputs (
    product_id TEXT NOT NULL, product_revision INTEGER NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    PRIMARY KEY(product_id,product_revision,asset_id),
    FOREIGN KEY(product_id,product_revision) REFERENCES products(id,revision)
);
CREATE TABLE IF NOT EXISTS sites (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_items (
    id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites(id),
    code TEXT NOT NULL, name TEXT NOT NULL,
    UNIQUE(site_id,code)
);
CREATE TABLE IF NOT EXISTS asset_item_links (
    asset_id TEXT NOT NULL REFERENCES assets(id),
    item_id TEXT NOT NULL REFERENCES evaluation_items(id),
    PRIMARY KEY(asset_id,item_id)
);
CREATE TABLE IF NOT EXISTS asset_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_asset_id TEXT NOT NULL REFERENCES assets(id),
    target_asset_id TEXT NOT NULL REFERENCES assets(id),
    kind TEXT NOT NULL CHECK(kind IN ('corrects','supplements')),
    item_id TEXT REFERENCES evaluation_items(id),
    reason TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL,
    CHECK(source_asset_id<>target_asset_id)
);
CREATE TABLE IF NOT EXISTS conclusions (
    id TEXT NOT NULL, revision INTEGER NOT NULL,
    site_id TEXT NOT NULL REFERENCES sites(id),
    title TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'published',
    published_at TEXT NOT NULL, superseded_at TEXT,
    evidence_digest TEXT NOT NULL,
    PRIMARY KEY(id,revision)
);
CREATE TABLE IF NOT EXISTS conclusion_evidence (
    conclusion_id TEXT NOT NULL, conclusion_revision INTEGER NOT NULL,
    item_id TEXT NOT NULL REFERENCES evaluation_items(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    asset_digest TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
    PRIMARY KEY(conclusion_id,conclusion_revision,item_id,asset_id),
    FOREIGN KEY(conclusion_id,conclusion_revision) REFERENCES conclusions(id,revision)
);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, product_id TEXT, product_revision INTEGER,
    conclusion_id TEXT, conclusion_revision INTEGER,
    recipient TEXT NOT NULL, purpose TEXT NOT NULL, created_at TEXT NOT NULL,
    input_digest TEXT NOT NULL, policy_revisions TEXT NOT NULL,
    evidence_snapshot TEXT,
    CHECK((product_id IS NOT NULL AND conclusion_id IS NULL)
       OR (product_id IS NULL AND conclusion_id IS NOT NULL)),
    FOREIGN KEY(product_id,product_revision) REFERENCES products(id,revision),
    FOREIGN KEY(conclusion_id,conclusion_revision) REFERENCES conclusions(id,revision)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL
);
"""


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection
