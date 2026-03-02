"""
Judge prompt builders for LLM-as-a-Judge evaluation of all three NEA agents.

Each module exposes a single function:
    build_judge_prompt(input_data, agent_output, context_tags) -> (system_prompt, user_prompt)

The returned tuple is ready to pass directly to the Anthropic Messages API
(or Batch API) as the system and user fields respectively.

Usage:
    from evaluation.judge_prompts.outreach_judge import build_judge_prompt
    system, user = build_judge_prompt(company_bundle, outreach_response, context_tags)
"""
