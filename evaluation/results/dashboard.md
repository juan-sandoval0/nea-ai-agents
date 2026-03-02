# NEA AI Agents — Judge Evaluation Results
*Generated: 2026-03-02T22:18:28.516272*

## Score Summary

| Test Case | Agent | Composite Score | Pass/Fail | Notes |
|-----------|-------|----------------|-----------|-------|
| news_aggregator_30d | ? | — | ERROR | The read operation timed out |
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
| tldr_matx.com | tldr | — (forced=0) | Fail |  |
| tldr_namespace.com | tldr | — (forced=0) | Fail |  |
| tldr_neuralmagic.com | tldr | — (forced=0) | Fail | HF: HF1: Briefing claims Neural Magic was funded by 'Andreessen Horowitz and New Enterprise Associates (NEA)' — no investor names appear anywhere in the four input tables., HF1: Briefing includes a 'Company Overview' section structured as the required sections but uses non-standard headings; more critically, the investor names are a clear hallucination. |
| tldr_octo.ai | tldr | — (forced=0) | Fail | HF: HF1: 'CEO Luis Ceze' — the title 'CEO' is not present in any input field. All founder title fields are blank. This is a hallucinated title assignment with no grounding in the input data. |

---

## Per-Agent Pass Rate

**news_aggregator**: 0/1 passed (0%) of 1 total

**outreach**: 7/13 passed (54%) of 13 total

**tldr**: 0/4 passed (0%) of 4 total

**unknown**: 0/0 passed (n/a) of 1 total
