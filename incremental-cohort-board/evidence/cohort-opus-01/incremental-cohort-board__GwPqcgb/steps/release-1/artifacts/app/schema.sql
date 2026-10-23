CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    day TEXT,
    cents INTEGER
);
CREATE INDEX IF NOT EXISTS orders_account ON orders(account);
CREATE INDEX IF NOT EXISTS orders_day ON orders(day);
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    segment TEXT
);
CREATE INDEX IF NOT EXISTS tags_account ON tags(account);
CREATE INDEX IF NOT EXISTS tags_segment ON tags(segment);
CREATE TABLE IF NOT EXISTS rates (
    id TEXT PRIMARY KEY,
    segment TEXT,
    band TEXT
);
CREATE INDEX IF NOT EXISTS rates_segment ON rates(segment);
CREATE TABLE IF NOT EXISTS rollup (
    mode TEXT NOT NULL,
    day TEXT,
    segment TEXT,
    band TEXT,
    row_count INTEGER NOT NULL CHECK(row_count > 0),
    amount_count INTEGER NOT NULL CHECK(amount_count >= 0),
    total_cents INTEGER,
    account_count INTEGER NOT NULL CHECK(account_count > 0),
    min_cents INTEGER,
    max_cents INTEGER
);
CREATE INDEX IF NOT EXISTS rollup_key ON rollup(mode, day, segment, band);
CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

