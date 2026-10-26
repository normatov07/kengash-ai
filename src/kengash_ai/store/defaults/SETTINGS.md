# SETTINGS.md: kengash settings for this project. YAML. Kengash never overwrites this file.
version: 1

# project
project.test_cmd: ""          # e.g. "uv run pytest -q"; used by run_tests steps and reviewers
project.lint_cmd: ""

# loops
loop_max.simple: 3
loop_max.standard: 4
loop_max.critical: 6
loop_grant: 2                 # loops added per approval
loop_ask_at_cap: true         # false: park the ticket instead of asking
loop_count_rejected_review: true   # false: plan-review rejections count only toward plan.review_max
stall_repeat: 2               # the same finding fails this many loops in a row → stalled

# planning
grill.round_size: 3
plan.review_max: 2            # 0 = no plan review
plan.reviewer: different-provider   # or provider[/model]

# sessions and limits
sessions.reuse: true          # resume each ticket×role session across loops
sessions.max: 8
sessions.per_provider: {claude: 3, codex: 3, antigravity: 2}
tokens.per_ticket_max: 250000
step_timeout_min: 30          # a step running longer is killed and retried once
fallback_on_rate_limit: true

# token discipline
skill.max_lines: 80
skill.max_words: 400
memory.compact_at_lines: 200
memory.compactor: claude/haiku   # provider/model that compacts MEMORY.md
logs.keep_days: 30               # worker logs untouched this long are removed; 0 keeps all
review.diff_only: true

# providers: allow_api_key keeps API-key variables in worker environments;
# user_config lets workers load your own hooks, plugins and MCP servers
providers:
  claude:      {allow_api_key: false, user_config: false}
  codex:       {allow_api_key: false, user_config: false}
  antigravity: {allow_api_key: false, user_config: false}

# agents: role → CLI; an omitted model means the CLI's default model;
# bypass_permissions: true adds the CLI's permission-bypass flag (off by default)
agents:
  planner:           {on: true,  cli: claude/opus,   skill: plan}
  plan-reviewer:     {on: true,  cli: codex,         skill: review-plan}
  implementer:       {on: true,  cli: codex,         skill: implement, fallback: [claude/sonnet]}
  code-reviewer:     {on: true,  cli: claude/opus,   skill: review-code}
  security-reviewer: {on: true,  cli: claude/sonnet, skill: review-security, blocking: true}
  test-runner:       {on: false, cli: shell,         skill: run-tests}
  doc-writer:        {on: false, cli: antigravity,   skill: sync-docs}

# workflows: steps run in order; on_fail routes a failing verdict back and adds a loop
workflows:
  simple:   {steps: [plan, implement, review_code], on_fail: {review_code: implement}}
  standard: {steps: [plan, review_plan, implement, review_code],
             on_fail: {review_plan: plan, review_code: implement}}
  critical: {steps: [plan, review_plan, implement, review_code, security],
             on_fail: {review_plan: plan, review_code: implement, security: implement}}

# sub-status shown while a step runs
status.names: {plan: under_planning, review_plan: under_plan_review, implement: under_implementation,
               review_code: under_review, security: under_security_review, run_tests: under_test,
               docs: under_docs, approve: needs_approval}

# merge: ask | auto | branch
merge.mode: ask
