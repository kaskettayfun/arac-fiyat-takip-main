CREATE TABLE IF NOT EXISTS vehicle_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    version_trim TEXT,
    fuel_type TEXT,
    transmission TEXT,
    engine_power_hp INTEGER,
    list_price_try INTEGER NOT NULL CHECK (list_price_try > 0),
    campaign_price_try INTEGER,
    source_url TEXT NOT NULL,
    UNIQUE (collected_at, brand, model, version_trim, list_price_try)
);
CREATE INDEX IF NOT EXISTS idx_vehicle_prices_brand_model
    ON vehicle_prices (brand, model);
CREATE INDEX IF NOT EXISTS idx_vehicle_prices_collected_at
    ON vehicle_prices (collected_at);
