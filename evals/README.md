# evals

Scenarios that prove each installed skill on real agents (SP4 spec decisions 11 to 13). Never installed; run with `kengash skills eval <skill>` or `make evals`, which spend subscription quota.

`evals/<skill>/<scenario>.yaml`:

```yaml
skill: to-plan                        # the skill under test
description: one line
notes: how it failed without the skill (RED)
files: {calc.py: "def sub(a, b): ..."}   # the scratch repo
settings: "plan.reviewer: {cli}\n"   # SETTINGS.md for the defaults and the project
setup:                                # kengash commands run before the conductor
  - {args: [plan, new, --mode, quick, --title, T], stdin: "prompt", save: plan}
turns:                                # what the user types; {plan} is a saved id
  - "/to-ticket {plan}"
  - "Yes, add them."
expect:
  journal: [ticket.created]           # event types that must appear
  absent: [plan.rejected]             # and that must not
  plans: {count: 1, fields: {status: ticketed}}
  tickets: {min: 2}
  memory: ["text MEMORY.md must hold"]
  reply: ["text the last reply must hold"]
  clean: true                         # the conductor changes no file in the repo
  ui: true                            # the store's UI server runs (the runner stops it after)
timeout_s: 900                        # per turn
```

`{agent}`, `{model}` and `{cli}` (`<agent>/<model>`) name the run's own conductor, so workers and reviewers can run on it too; `save:` adds more names.

Each run gets its own store and scratch repo, installs the skills for its agent (none with `--baseline`), runs every turn headless on the agent's cheapest model, resuming its session, then checks `expect`; the first miss is the failure.
