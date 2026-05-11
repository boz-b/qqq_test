# Part 6 handoff: optional AI-generated daily brief summaries

Paste this note into a fresh OpenClaw session after the cheap AI API key has been added to this machine.

```text
We will now continue qqq_test part 6: AI-generated daily brief summaries.

Project context:
- Local repo: /home/robot/coding/qqq_test
- Remote: git@github.com:boz-b/qqq_test.git
- Canonical memory/worklog: /home/robot/coding/openclaw/external/boz-bot-memory/projects/qqq_test/
- Python rule: use only /home/robot/coding/qqq_test/venv; do not install global Python packages.
- Secrets rule: do not read, print, commit, or expose API keys. Real keys live only in ignored env/ files.
- Existing local key files:
  - env/finnhub.env for Finnhub
  - env/llm_summary.env for the optional cheap AI summary provider
- Safe templates:
  - env.example/finnhub.env.example
  - env.example/llm_summary.env.example
- The project currently works without AI summaries; keep fallback behavior intact.

Current qqq_test state:
- Parts 1-5 are complete and pushed.
- Latest part-5 commit: 9e8177a chore: update daily brief wording
- Local runtime exists: venv/, data/, logs/, env/.
- Cron is installed with local computer time:
  - Tuesday 02:00: scripts/tuesday_refresh.sh, which runs weekly calendar refresh first and then the Finnhub/news daily refresh/export
  - Wednesday-Saturday 02:00: scripts/nightly_refresh.sh
- Daily brief UI now says Daily Brief (news + macro calendar).
- Legacy JSON key remains ff_events for compatibility with public/index.html and dashboard.py.

Before coding:
1. cd /home/robot/coding/qqq_test
2. git pull --ff-only
3. confirm git status is clean
4. do not cat/print env/llm_summary.env; only check whether required variable names exist if needed without showing values
5. run baseline validation:
   - venv/bin/python -m py_compile *.py scripts/*.py
   - venv/bin/python dashboard.py --smoke-test
   - venv/bin/python export_json.py --no-git
   - git checkout -- public/data after no-git export validation if generated JSON changed

Implementation goal:
- Add an optional AI summarization layer for Finnhub news candidates.
- Keep macro/calendar rows deterministic and preserve existing weekly USD calendar behavior.
- If AI config is missing, disabled, over budget, invalid, or the provider request fails, fall back to the current heuristic news selection and do not break cron.

Suggested implementation:
1. Extend news_feeds.py env loading to include env/llm_summary.env.
2. Use the existing requests dependency and an OpenAI-compatible /chat/completions HTTP call when possible; avoid adding a provider SDK unless Boz approves the dependency.
3. Add helper functions such as:
   - _llm_summary_config()
   - _build_news_summary_prompt(candidate_items, trade_date)
   - _call_openai_compatible_summary(config, messages)
   - summarize_news_candidates_with_llm(candidate_items, trade_date)
4. Fetch broader same-day Finnhub candidates before the current hard cap, dedupe by headline/source, then send a capped number of candidates controlled by LLM_SUMMARY_MAX_CANDIDATE_ITEMS.
5. Ask the model for strict JSON only, for example:
   [
     {"time":"09:30","event":"Concise QQQ-relevant bullet [Source]","impact":"Medium Impact Expected","actual":"","forecast":"","previous":"","kind":"news_summary","priority":3}
   ]
6. Validate and sanitize model output defensively:
   - reject non-JSON or malformed rows
   - require short event text
   - preserve source attribution when available
   - cap bullets by LLM_SUMMARY_MAX_BULLETS
   - convert rows back to the same combined event CSV schema currently used by data/ff_events.csv
7. Preserve compatibility:
   - dashboard/export output should still use the ff_events JSON key
   - public/index.html should not need a schema-breaking frontend change
8. Add clear comments to every changed/implemented code line because Boz wants non-Python coders to understand the changes.

Validation after coding:
- bash -n scripts/*.sh
- venv/bin/python -m py_compile *.py scripts/*.py
- venv/bin/python -m pip check
- venv/bin/python dashboard.py --smoke-test
- LLM_SUMMARY_ENABLED=0 venv/bin/python export_json.py --no-git to prove fallback still works
- If Boz confirms the key is ready, run one limited enabled summary test without printing the key
- git checkout -- public/data after validation unless Boz wants generated static data committed/deployed
- commit and push qqq_test changes
- update and push the private memory repo worklog/memory
```
