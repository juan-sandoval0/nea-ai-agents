# NEA AI Agents — Judge Evaluation Results
*Generated: 2026-03-04T01:53:48.052100*

## Score Summary

| Test Case | Agent | Composite Score | Pass/Fail | Notes |
|-----------|-------|----------------|-----------|-------|
| news_aggregator_7d | news_aggregator | 63.0 | — |  |
| outreach_matx.com_ashley_email | outreach | 3.6 | Pass |  |
| outreach_matx.com_danielle_email | outreach | 3.2 | Fail |  |
| outreach_matx.com_madison_email | outreach | 4.1 | Pass |  |
| outreach_namespace.com_ashley_email | outreach | 3.6 | Pass |  |
| outreach_namespace.com_danielle_email | outreach | 3.7 | Pass |  |
| outreach_namespace.com_madison_email | outreach | 3.7 | Pass |  |
| outreach_neuralmagic.com_ashley_email | outreach | 3.4 | Fail |  |
| outreach_neuralmagic.com_danielle_email | outreach | 3.1 | Fail |  |
| outreach_neuralmagic.com_madison_email | outreach | 3.1 | Fail |  |
| outreach_octo.ai_ashley_email | outreach | 3.8 | Pass |  |
| outreach_octo.ai_danielle_email | outreach | 3.3 | Fail |  |
| outreach_octo.ai_madison_email | outreach | 4.2 | Pass |  |
| outreach_perplexity.ai_ashley_email | outreach | 2.6 | Fail |  |
| tldr_airbnb.com | tldr | — (forced=0) | Fail | HF: HF1: Multiple factual claims not traceable to any input table — '$9.3B raised', '100.6M monthly visitors', '+13.7% over 30 days', '17,139 headcount', '+0.2% over 90 days', 'founded in 2007', 'Last Funding Round: $1B (April 2020)', 'VENTURE_UNKNOWN stage', 'B2C digital marketplace', 'Andreessen Horowitz, BlackRock, Axel Springer, FJ Labs, ESO Fund as investors', 'web and mobile platforms'., HF2: Agent used training-data knowledge about Airbnb (a publicly known company) to populate fields that the input tables explicitly returned empty — company_core returned 0 fields, key_signals returned 0 signals, news returned 0 articles. All numerical and financial data originates from outside the provided inputs. |
| tldr_cydelphi.com | tldr | — (forced=0) | Fail | HF: HF1: 'Doron Kolton, VP Engineering' is mentioned in Key Points as a named leader, but no such name or title appears in any of the four input tables. Founders table has 0 founders. This is a hallucinated fact., HF2: 'Doron Kolton, VP Engineering' may also represent use of outside knowledge, as this individual does not appear in any provided input data. |
| tldr_distyl.ai | tldr | 62.2 | Fail |  |
| tldr_genspark.ai | tldr | 63.2 | Fail |  |
| tldr_matx.com | tldr | — (forced=0) | Fail | HF: HF1: 'CEO Reiner Pope' — title 'CEO' is not present in any input field; founder title fields are blank., HF1: 'CTO Mike Gunter' — title 'CTO' is not present in any input field; founder title fields are blank. |
| tldr_namespace.com | tldr | — (forced=0) | Fail | HF: HF1: Briefing states 'Web Traffic: 3,110' — an absolute traffic number not present in any input table. The input data only contains '+18.6% (30d)' with no absolute figure., HF1: 'the company is actively tracking its data for future insights' — fabricated claim with no basis in any input field. |
| tldr_neuralmagic.com | tldr | — (forced=0) | Fail | HF: HF1: 'notable investors including Andreessen Horowitz and New Enterprise Associates (NEA)' — no investor names appear in any of the four input tables. This is a hallucinated claim. |
| tldr_noma.security | tldr | — (forced=0) | Fail | HF: HF1: Briefing assigns title 'CEO' to Niv Braun and 'CTO' to Alon Tron, but both founders have blank Title fields in the input data. These titles are not traceable to any input field and constitute hallucinated facts. |
| tldr_novee.security | tldr | — (forced=0) | Fail | HF: HF1: Agent assigned 'CEO' to Ido Geffen and 'CPO' to Gon Chalamish — both Title fields in the founders table are explicitly blank. These titles are hallucinated with no basis in the input data. |
| tldr_octo.ai | tldr | 38.4 | Fail |  |
| tldr_openai.com | tldr | — (forced=0) | Fail | HF: HF1: Multiple hallucinated facts not traceable to any input table (funding amounts, headcount, traffic metrics, founding date, investor names, product description, employee count, business model, stage classification, specific round date), HF2: Agent demonstrably used outside knowledge/training data about OpenAI rather than the provided input tables, which contained zero company_core fields, zero key_signals, and zero news articles |
| tldr_periodic.com | tldr | — | ERROR | no_json_block |
| tldr_saviynt.com | tldr | — (forced=0) | Fail | HF: HF1: Amit Saha's title 'VP of Business Development' is hallucinated — the founders table shows an empty title field for this individual., HF2: SailPoint and CyberArk named as competitors from outside/training knowledge — not present in any input table. Market assertion 'Zero Trust and multi-cloud IAM are high-priority enterprise spending categories' uses outside knowledge not grounded in any input field. |
| tldr_stripe.com | tldr | — (forced=0) | Fail | HF: HF1: Numerous factual claims not traceable to any input table — funding total ($8,815,918,068), employee count (14,145), web traffic (108.9M monthly visits), headcount growth (5.5% over 90 days), web traffic growth (8.3% over 30 days), funding event date (February 24, 2026), investor names (Andreessen Horowitz, Google), product description details, founding year (2010), stage (Late-stage private) — none of these appear in any of the four input tables., HF2: Agent demonstrably used training data knowledge about Stripe rather than the provided input tables, which contained only founder data and no company_core, key_signals, or news_articles records. |

---

## Per-Agent Pass Rate

**news_aggregator**: 0/1 passed (0%) of 1 total

**outreach**: 7/13 passed (54%) of 13 total

**tldr**: 0/13 passed (0%) of 14 total
