# SETTINGS.md: kengash settings for this project. YAML. Kengash never overwrites this file.
version: 1

# project
project.test_cmd: ""          # e.g. "uv run pytest -q"; used by run_tests steps and reviewers
project.lint_cmd: ""
project.generate_cmd: ""          # rebuilds generated files, e.g. "python3 tools/gen.py"; runs before checks
project.commands: []              # more commands workers may run, exact prefixes

# loops
loop_max.simple: 3
loop_max.standard: 4
loop_max.critical: 6
loop_grant: 2                 # loops added per approval
loop_ask_at_cap: true         # false: park the ticket instead of asking
loop_count_rejected_review: true   # false: plan-review rejections count only toward plan.review_max
stall_repeat: 2               # the same finding fails this many loops in a row → stalled
loop_start: ask               # auto: start the loop as soon as tickets are added (Auto mode)
loop_relay: true              # a finishing worker starts what is runnable while a loop is on
checks.turns: 2               # fix turns an editing step gets when kengash's checks fail after it; 0 = off (SP15)
checks.parallel: 0            # kengash's own test runs at once on this machine; 0 = half the CPU cores

# planning
grill.round_size: 3
plan.review_max: 2            # 0 = no plan review
plan.reviewer: different-provider   # or provider[/model]
plan.max_files: 12            # a plan over this many files splits the ticket into parts; 0 = off

# sessions and limits
sessions.reuse: true          # resume each ticket×role session across loops
sessions.max: 8
sessions.per_provider: {claude: 3, codex: 3, antigravity: 2}
tokens.per_ticket_max: 3000000
step_timeout_min: 30          # a step running longer is killed and retried once
fallback_on_error: true

# token discipline
skill.max_lines: 80
skill.max_words: 400
memory.compact_at_lines: 200
memory.compactor: claude/haiku   # provider/model that compacts MEMORY.md and harvests decisions
memory.harvest: all              # all | plans (not chat) | off: record what the user settles
logs.keep_days: 30               # worker logs untouched this long are removed; 0 keeps all
watch.tabs: auto                 # a terminal tab per worker and a dashboard per loop; off: print the command
watch.terminal: ""               # a command with {title} and {command}; empty: Orca, tmux or gnome-terminal
watch.notify: true               # a desktop notification when a ticket needs you
review.diff_only: true
review.block_on: [high, medium]  # a review fails only on these severities

# steering: a stuck turn is stopped and resumed with a correction instead of killed
steering: {soft_min: 20, wrap_min: 10, turns: 2, poll_max: 8, full_runs_max: 2}

# paths: generated files are never claimed; two editing tickets may share this many exact files
paths: {shared: ["*.g.dart", "*.freezed.dart", "*.generated.*"], max_overlap: 2}

# context: how much of the plan's files an implementer's first prompt carries, read at that moment
context.max_kib: 64

# providers: allow_api_key keeps API-key variables in worker environments;
# user_config lets workers load your own hooks, plugins and MCP servers
providers:
  claude:      {allow_api_key: false, user_config: false}
  codex:       {allow_api_key: false, user_config: false}
  antigravity: {allow_api_key: false, user_config: false}

# agents: role → CLI; an omitted model means the CLI's default model; by_importance tries
# another CLI first for tickets of that importance (edit all of this on the Agents page);
# bypass_permissions: true adds the CLI's permission-bypass flag (off by default)
agents:
  planner:           {on: true,  cli: claude/opus,   skill: plan}
  plan-reviewer:     {on: true,  cli: codex,         skill: review-plan}
  implementer:       {on: true,  cli: codex,         skill: implement, fallback: [claude/sonnet]}
  code-reviewer:     {on: true,  cli: claude/sonnet, skill: review-code, by_importance: {critical: claude/opus}}
  security-reviewer: {on: true,  cli: claude/sonnet, skill: review-security, blocking: true}
  test-runner:       {on: false, cli: shell,         skill: run-tests}
  doc-writer:        {on: false, cli: antigravity,   skill: sync-docs, fallback: [claude/sonnet]}

# workflows: steps run in order; on_fail routes a failing verdict back and adds a loop
workflows:
  simple:   {steps: [plan, implement, review_code], on_fail: {review_code: implement}}
  standard: {steps: [plan, review_plan, implement, review_code],
             on_fail: {review_plan: plan, review_code: implement}}
  critical: {steps: [plan, review_plan, implement, review_code, security],
             on_fail: {review_plan: plan, review_code: implement, security: implement}}

# routing: the workflow a new ticket of each importance runs; an importance left out runs
# the workflow of its own name. Any other workflow is picked per ticket.
# routing: {simple: simple, standard: standard, critical: hotfix}

# sub-status shown while a step runs
status.names: {plan: under_planning, review_plan: under_plan_review, implement: under_implementation,
               review_code: under_review, security: under_security_review, run_tests: under_test,
               docs: under_docs, approve: needs_approval}

# merge: ask | auto | branch
merge.conflict_turns: 2       # conflict resolutions that cost no loop
merge.mode: auto
