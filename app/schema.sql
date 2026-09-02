CREATE TABLE IF NOT EXISTS clinics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name_ko TEXT, name_en TEXT, name_zh TEXT,
  address_ko TEXT, address_zh TEXT,
  lat REAL, lng REAL,
  official_site TEXT, naver_place_url TEXT, instagram TEXT, facebook TEXT,
  verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('verified','suspected_fake','unverified')),
  verification_notes TEXT,
  revisit_badge INTEGER,
  editor_note TEXT,
  opened_year INTEGER,  -- 开业/개원年份(官网 병원소개 或 NAVER),用于"运营年限";未获取为 NULL
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS treatments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL CHECK (category IN ('光电类','注射类','线雕类','其他')),
  treatment_zh TEXT NOT NULL,
  treatment_ko TEXT,
  variant_zh TEXT NOT NULL,
  variant_ko TEXT,
  variant_en TEXT,
  notes TEXT,
  match_hint TEXT,  -- 变体级推断关键词('입술|립|唇'),available_no_price 优先按此匹配 offerings
  UNIQUE (treatment_zh, variant_zh)
);

CREATE TABLE IF NOT EXISTS prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  treatment_id INTEGER REFERENCES treatments(id),
  raw_name_ko TEXT,
  raw_name_zh TEXT,
  price_krw INTEGER NOT NULL,
  is_event_price INTEGER NOT NULL DEFAULT 0,
  spec_notes TEXT,
  source_url TEXT NOT NULL,
  collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  source TEXT NOT NULL,
  score REAL,
  review_count INTEGER,
  source_url TEXT NOT NULL,
  collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  source TEXT NOT NULL,
  text_original TEXT,
  text_zh TEXT,
  sentiment TEXT CHECK (sentiment IN ('positive','negative','neutral')),
  issue_type TEXT,          -- 差评问题领域(受控词表见 scripts/ingest.py ISSUE_VALUES);正/中性评留空
  post_url TEXT NOT NULL,
  posted_at TEXT,
  collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS xhs_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  url TEXT NOT NULL,
  title TEXT,
  sentiment TEXT CHECK (sentiment IN ('推荐','差评','中性')),
  nature TEXT NOT NULL DEFAULT '未判定',
  summary_zh TEXT,
  posted_at TEXT,
  collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  file_path TEXT NOT NULL,
  description TEXT,
  source_url TEXT,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clinic_offerings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  category TEXT NOT NULL,
  name_ko TEXT, name_zh TEXT, name_en TEXT,
  description_zh TEXT,
  source_url TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  UNIQUE (clinic_id, category, name_ko)
);

CREATE TABLE IF NOT EXISTS knowledge_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  name_zh TEXT NOT NULL,
  name_ko TEXT, name_en TEXT,
  origin TEXT,
  summary_zh TEXT NOT NULL,
  source_url TEXT,
  collected_at TEXT NOT NULL,
  parent_id INTEGER REFERENCES knowledge_items(id),  -- 产品家族的子型号(如 Rejuran 四型)挂父条目
  UNIQUE (category, name_zh)
);

CREATE TABLE IF NOT EXISTS doctors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  name_ko TEXT, name_zh TEXT,
  title TEXT,
  credentials_zh TEXT,
  is_specialist TEXT CHECK (is_specialist IN ('specialist','general','unknown')) DEFAULT 'unknown',
  source_url TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  UNIQUE (clinic_id, name_ko)
);

CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clinic_id INTEGER NOT NULL REFERENCES clinics(id),
  name_ko TEXT NOT NULL,
  name_zh TEXT,
  address_ko TEXT,
  naver_place_url TEXT,
  visitor_reviews INTEGER,
  blog_reviews INTEGER,
  is_primary INTEGER NOT NULL DEFAULT 0,
  source_url TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  UNIQUE (clinic_id, name_ko)
);

CREATE TABLE IF NOT EXISTS price_components (
  price_id INTEGER NOT NULL REFERENCES prices(id),
  treatment_id INTEGER NOT NULL REFERENCES treatments(id),
  PRIMARY KEY (price_id, treatment_id)
);

CREATE TABLE IF NOT EXISTS fx_rates (
  quote TEXT PRIMARY KEY,
  rate REAL NOT NULL,
  fetched_at TEXT NOT NULL
);
