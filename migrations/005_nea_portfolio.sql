-- NEA Portfolio Companies
-- Separate from watched_companies (news tracking).
-- Used by meeting briefing to detect NEA ecosystem connections in founder backgrounds.

CREATE TABLE nea_portfolio (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,       -- from NEA URL slug, e.g. "cloudflare"
  company_name TEXT NOT NULL,      -- human-readable name
  domain TEXT,                     -- website domain if known
  sector TEXT,                     -- e.g. Enterprise, Consumer, Fintech, Life Sciences, Digital Health
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_nea_portfolio_name ON nea_portfolio(company_name);
CREATE INDEX idx_nea_portfolio_domain ON nea_portfolio(domain);

ALTER TABLE nea_portfolio ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON nea_portfolio FOR SELECT USING (true);
CREATE POLICY "Service role write" ON nea_portfolio FOR ALL USING (auth.role() = 'service_role');
