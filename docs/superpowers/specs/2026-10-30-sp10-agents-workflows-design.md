# SP10: Namespaced skills, full control of agents and workflows, UI quality (design)

Date: 2026-10-30. Status: brainstormed with the user on 2026-10-30 (skill naming, built-in lock, workflow scope and both screen layouts chosen by the user); calls marked *call* are the builder's and open to veto.

## 1. Why

The user, on 2026-10-30, after using 0.2.0:

1. **Skills mix with other packages.** `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop` and `open-ui` install as bare names beside every other package's skills. The user wants one prefix, like `superpowers:brainstorming`, so typing `kengash` lists every command, in every agent CLI.
2. **Agents and workflows cannot be fully controlled from the UI.** A built-in agent's skill is a free-text box, so it can be repointed or broken, and the copies seeded into `~/.kengash/defaults/roles/` shadow the package's, so they go stale on upgrade. A custom agent's instruction is one line; the rest is a starter SKILL.md edited by hand on disk, and after creation its kind, instruction and permissions cannot change in the UI. Workflows cannot be created, copied, renamed or deleted; a step goes only "after the selected one, or before done"; a node's agent cannot be swapped.
3. **UI quality.** Closed choices are text inputs (CLI·MODEL is an `<input list>`, fallbacks are comma text, the skill is free text). Headless Chrome on 2026-10-30: the Agents roster's name and CLI columns overlap below about 1000 px; the Workflow graph is cut off at 390 px; the top navigation runs off a phone screen. The Agents row editor is too thin for real editing.

Research on 2026-10-30: the `name:skill` form exists only for plugins. Claude Code namespaces a plugin's skills as `/<plugin>:<skill>` and loads a plugin folder placed in `~/.claude/skills/<name>/` or the project's `.claude/skills/<name>/` with no marketplace (`<name>@skills-dir`; a project copy loads only after the workspace trust dialog, never in `-p` alone). Antigravity namespaces plugin skills the same way (`agy plugin install <target>`; plugins are per user). Codex has no namespace: skills come from `.agents/skills` and `~/.agents/skills` and are called with `$name`. The Agent Skills `name` allows lowercase letters, digits and hyphens only.

## 2. Goals, non-goals, anti-goals

- Goal: every kengash skill appears under `kengash` in every supported CLI: `/kengash:<skill>` in Claude Code and Antigravity, `$kengash-<skill>` in Codex.
- Goal: built-in agents keep their role and instructions; the user picks their CLI, model, fallbacks and switches.
- Goal: the user creates, edits, copies and removes their own agents in the UI: name, description, kind, CLI, model, ordered fallbacks, instructions (a chosen skill or their own text), blocking, permission bypass, on or off.
- Goal: the user creates, copies, renames and deletes workflows, inserts any agent at any point, reorders and swaps nodes, sets send-back edges and loop caps, and picks which workflow each importance gets; tickets then run exactly that workflow.
- Goal: every screen works from 360 px to wide desktop with no horizontal page scroll and no overlapping text; every closed choice is a real control.
- Non-goals: parallel branches or conditional edges (the user chose linear workflows); the same agent twice in one workflow; renaming an agent (*call*: copy it, then remove the old one; a rename would orphan the sessions, journal entries and worktree notes keyed by role); free node positions (layout stays automatic); a Codex plugin (Codex has no namespace); changing the plan-review job behind `/kengash:plan`, which keeps `plan.reviewer`.
- Anti-goals: changing a built-in agent's instructions by any path (UI, CLI, a store file); a custom agent that escapes the loop cap, token cap, blocking rule or verdict contract (SP6); a save that leaves SETTINGS.md invalid or drops the user's comments; renaming or deleting a workflow that an open ticket or an importance uses; any browser `alert`/`confirm`.

## 3. Decisions: skills (milestone 1)

1. **Short canonical names.** `skills/` holds `plan` (was `to-plan`), `grill` (`to-plan-with-grill`), `ticket` (`to-ticket`), `loop` (`to-loop`), `ui` (`open-ui`) and `memory` (`kengash-memory`); each folder name equals its `name`, as the lint requires. The plugin manifests (`.claude-plugin/plugin.json`, `.antigravity-plugin/plugin.json`) name the plugin `kengash`; the marketplace keeps `kengash-ai`, so `/plugin marketplace add normatov07/kengash-ai` then `/plugin install kengash@kengash-ai` gives `/kengash:loop`.
2. **`kengash skills install` per agent.**
   - `claude`: writes a skills-dir plugin, `<.claude or ~/.claude>/skills/kengash/` with `.claude-plugin/plugin.json` and `skills/<name>/SKILL.md`; it loads as `kengash@skills-dir`. A project install prints that the plugin loads after Claude Code's trust dialog for the folder.
   - `antigravity`: builds the same plugin folder under the store (`~/.kengash/plugin/kengash/`, *call*) and runs `agy plugin install <folder>`; if agy is missing or the install fails, it falls back to prefixed copies in `.agents/skills/` (or `~/.gemini/config/skills/` with `--global`) and says so.
   - `codex`: prefixed copies, `.agents/skills/kengash-<name>/SKILL.md` (or `~/.agents/skills/` with `--global`), with `name: kengash-<name>` rewritten in the copy.
   - Every route first removes the old kengash skills it finds in its targets: folders named `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop`, `open-ui` or `kengash-memory` whose SKILL.md carries `metadata: {source: kengash-ai}`. Nothing without that marker is touched.
3. **One spelling in text.** Skills, docs, the README, the UI and CLI hints write `/kengash:<skill>`; the skills README and `docs/` give the Codex form once (`$kengash-<skill>`). The `npx skills add` route is dropped from the docs (*call*: skills are useless without the `kengash` CLI, and it would install unprefixed names).
4. **Doctor.** `kengash doctor` warns when old skill names are installed (`old kengash skill names installed in <dir>; run: kengash skills install --agent <agent>`).
5. **Evals** move to `evals/<new name>/`; the runner loads the plugin with `--plugin-dir` for claude (a `-p` run never loads a project plugin) and installs per decision 2 for agy and codex. The skill bodies change only in names; their evals pass again on claude and agy.

## 4. Decisions: agents and workflows (milestone 2)

1. **Built-in agents are fixed in what they do.** For the seven built-in roles (`planner`, `plan-reviewer`, `implementer`, `code-reviewer`, `security-reviewer`, `test-runner`, `doc-writer`), `agents.<role>.skill` must equal the shipped skill (`planner: plan`, …); any other value fails validation with `agents.<role>.skill is fixed at <skill>; set it back, or copy the agent (kengash agent copy <role> <new>) to change what it does` (*call*: an error, not a silent fix, so an edit made through 0.2.0's free-text box is seen; `kengash settings check` and the UI's invalid banner show it). Built-in role skills always load from the package: `ops.skills.role_file` skips the store for a built-in skill name, `kengash init` stops seeding `defaults/roles/`, and `kengash doctor` lists leftover store copies as ignored (it never deletes them). Editable on a built-in: `on`, `cli`, `fallback`, `blocking`, `bypass_permissions`.
2. **A custom agent** keeps the SP6 shape: `agents.<role>` plus one `steps.<step>` (`role`, `kind`, `does`). `does` is shown as the agent's **description** (one line, at most 200 characters, still prepended to its prompt). Its **instructions** are its role skill:
   - *Use a skill*: `agents.<role>.skill` names any role skill on the lookup path (the seven built-ins, or another of the user's).
   - *Write my own*: `agents.<role>.skill` equals the role, and `roles/<role>/SKILL.md` in the scope holds the text, written only by kengash (`ops.agent_config.set_instructions`): frontmatter generated (`name`, `description: Use when you are the <role> on a kengash_ai ticket.`, `metadata: {source: user}`), the body the user's text, checked against `skill.max_lines` and `skill.max_words` before writing. A new agent's editor starts with its kind's SP6 starter steps; switching from *Use a skill* to *Write my own* starts it with the chosen skill's text. The prompt keeps adding the kind's rule and the JSON reply schema, so the user's text never has to. The file goes to the scope being edited, like its SETTINGS keys (*call*): editing a defaults agent from a project writes `projects/<slug>/roles/<role>/`, which overrides the defaults' copy for that project only; custom skills keep the project → defaults lookup.
3. **Kind can change** on a custom agent. Changing away from `review` drops that step's `on_fail` edges in every workflow, in the same validated save, and the UI says which.
4. **Copy an agent.** `ops.agent_config.copy_agent(source, new)` makes a custom agent with the source's kind (built-in `check` and `approve` cannot be copied), CLI, fallbacks and description, and its own instructions starting from the source's skill text. This is how a built-in's behaviour is changed.
5. **Workflow management.** Names match `[a-z][a-z0-9_-]{0,30}`. `ops.workflows`: `new(name, from_=None)` (a copy, or `steps: [implement]` when blank, *call*), `rename(old, new)`, `remove(name)`. Rename and remove refuse while an importance routes to the workflow or an in-queue or in-process ticket names it, listing those tickets; rename rewrites `routing` entries. Each write is one validated, comment-preserving save that journals `settings.changed`.
6. **Importance routing.** New settings key `routing: {simple: simple, standard: standard, critical: critical}`; a missing entry means the workflow of the same name, so every existing SETTINGS.md stays valid. Validation: each target exists. `kengash ticket add` sets a new ticket's `workflow` to `routing[importance]`; `kengash ticket set --workflow` still picks any workflow. The system spec §4.6 gains the key.
7. **Workflow editing rules** (UI and CLI alike): any agent that is on or off may be inserted at any position; a workflow holds each step once; `approve` is a node like any other; an `on_fail` edge starts at a review step and targets an earlier step, enforced by `Settings` validation (*call*: a forward send-back skips work and was never meant; no shipped default has one); swapping a node's agent keeps its edge when the new step is also a review step, else drops it.
8. **The engine needs no new behaviour.** Routing, kinds, caps and verdicts stay as SP3 and SP6 built them; tests prove that a custom agent inserted first, in the middle, last and before `approve` runs in that order, and that a ticket cut under a remapped importance runs the remapped workflow.
9. **CLI parity.** One ops entry point per change, called by CLI and UI alike:
   - `kengash agent new` (SP6) gains `--fallback`, `--skill NAME` and `--instructions-file PATH|-`.
   - `kengash agent edit ROLE [--cli] [--fallback] [--on|--off] [--blocking|--no-blocking] [--bypass-permissions|--no-bypass-permissions] [--kind] [--does] [--skill | --instructions-file]`; the last four refuse a built-in role.
   - `kengash agent copy SOURCE NEW`, `kengash agent show ROLE [--json]` (settings, instructions, where used).
   - `kengash workflow new NAME [--from W]`, `rename OLD NEW`, `remove NAME`, `route IMPORTANCE WORKFLOW`, and `set NAME --steps a,b,c [--on-fail A=B]…` (steps and edges, written whole like the UI's save; there is no general `settings set`).
   - All take `-p/--project` and `--json` like the rest of the CLI.

## 5. Decisions: UI (milestones 3 and 4)

The Agents and Workflow screens follow this spec, not the canvas boards, by the user's choice on 2026-10-30 (mock-ups in `.superpowers/brainstorm/`, option A of each); the other five screens keep canvas parity. AGENTS.md's "UI design source" says so. Both screens keep today's scope tabs (Defaults, then each project), the amber "set here" marks for keys the scope overrides, and one Save for the whole screen: edits to several agents or workflows stay as drafts until Save or Discard, and the footer counts them (*call*: no browser dialog on switching, and no edit is lost by clicking another agent).

1. **Controls kit** (`ui/static/controls.js`, *call*: one module, plain functions returning templates, like `html.js`): native `<select>` styled to the theme (keyboard, screen readers and phones for free); a model picker (CLI select → model select of that CLI's models, with "Other…" revealing a text field); an ordered chip list (add from a select, remove with ✕, reorder by drag or Alt+↑/↓); a segmented control (a radio group); a switch (a checkbox); a textarea with live line and word counts against the caps; an agent picker popover (search, grouped Yours and Built-in, "+ New agent…"); a dialog for new and rename. Free text only where the value is free: names, descriptions, instructions, commands.
2. **Models per CLI** come from `ops.providers`: claude's aliases (`default`, `fable`, `opus`, `sonnet`, `haiku`); antigravity from `agy models`, cached with the sign-in check; codex `default` only; every list ends with "Other…". CLIs that are not installed or signed in show disabled with their state.
3. **Agents screen** (option A): a list of agents grouped *Yours* then *Built-in* (icon by kind, name, CLI · model, on switch), search, and "+ New"; beside it the selected agent's editor, sections in order: header (name, description, BUILT-IN or YOURS badge, on switch, ⋯ menu: Copy, Remove), Role (Advisor, Worker, Reviewer; locked on built-ins), Model (CLI, model, ordered fallbacks), Instructions (*Use a skill* select with a read-only preview, or *Write my own* editor; built-ins show the shipped text read-only with "Copy as my agent"), Behaviour (blocking, skip permission prompts with its warning), Used in (workflow chips with position, each linking to the Workflow screen, plus "+ Add to a workflow"), then a sticky footer naming unsaved fields with Discard and Save. "+ New" opens the same editor empty. The selection is in the URL (`#/agents/<role>`). Parallelism and limits move below the list and editor, unchanged; Importance routing moves to the Workflow screen.
4. **Workflow screen** (option A): workflow tabs with "+ New workflow" (blank or copy of the current one) and a ⋯ menu (rename, copy, delete, with the refusal reason inline); the graph as today, plus a "+" on every link that opens the agent picker and inserts there, and dragging a node to a new position (keyboard: Alt+↑/↓ on a focused node); the inspector for the selected node: the agent at this step (a select; swapping follows §4.7), "A fail sends the ticket to" (earlier steps, or "stop and ask me"), remove; an Importance → workflow panel with, per importance, a workflow select and its max loops (loop caps stay `loop_max.<importance>`, as tickets copy them when cut). One Save writes every edited workflow, the routing and the loop caps.
5. **Responsive rules.** Breakpoints 1280, 900 and 600 px. Below 900 the top navigation folds into a menu button; the Agents list and editor stack (selecting opens the editor, a back control returns); the Workflow inspector moves under the graph and the graph fits the width, panning inside its stage; board columns scroll inside the board with snap. Below 600 forms are one column. No screen scrolls the page sideways at 360 px.
6. **Input audit.** Every input on the seven screens is checked against rule 1; known cases: Settings' `plan.reviewer` and `memory.compactor` become the model picker, `merge.mode` a segmented control, `grill.round_size` a select of 1 to 4.

## 6. Interfaces

- `GET /api/agents` → `{providers: [{name, installed, signed_in, version, models: []}], skills: [{name, source: package|defaults|project}], agents: [{role, builtin, kind, step, does, cli, provider, model, fallback, on, blocking, bypass_permissions, skill, instructions_own: bool, instructions, used_in: [{workflow, position}], tokens}], …limits as today}`.
- `POST /api/agents` (create), `POST /api/agents/{role}` (a patch of editable fields; instructions as text), `POST /api/agents/{role}/copy` `{new}`, `POST /api/agents/{role}/remove`. Each takes `project`, needs `X-Harness`, and returns the saved keys or a 400 naming the problem; nothing is written on a refusal.
- `GET /api/workflows` adds `routing` and `agents` (role, step, kind, builtin) for the picker. `POST /api/workflows` `{name, from}`, `POST /api/workflows/{name}/rename` `{new}`, `POST /api/workflows/{name}/remove`; steps, edges, caps and routing save through the existing settings save.

## 7. Risks

- `agy plugin install <local folder>`: proven by a spike on 2026-10-30 (agy 1.4.11). agy reads `.antigravity-plugin/plugin.json`, copies the folder to `~/.gemini/config/plugins/kengash/` (a second install replaces it), and `agy -p "/kengash:loop"` ran the plugin's `loop` skill. It has no per-session plugin flag, so evals use the copy fallback (`/kengash-<name>`) to leave the user's agy plugins alone (*call*); the copy fallback (§3.2) also covers a failed install.
- A project-scope Claude plugin needs the trust dialog; `kengash skills install` says so, and `--global` avoids it.
- Built-in skills stop reading store copies: a user who hand-edited one loses that edit's effect. `kengash doctor` names each ignored copy and the CHANGELOG says to copy the agent instead.

## 8. Milestones and acceptance

**M1 Skill namespace.**
- [ ] `kengash skills install --agent claude` (project and `--global`) writes the skills-dir plugin; a new interactive Claude Code session lists `/kengash:plan`, `:grill`, `:ticket`, `:loop`, `:ui`, `:memory` (by hand), and `claude plugin list` shows `kengash@skills-dir`.
- [ ] agy shows `/kengash:loop` after install, or the fallback copies when the plugin route fails; codex copies are `kengash-<name>` with matching `name`.
- [ ] Old kengash skills are removed on install; foreign skills are not (tests); doctor warns about old names.
- [ ] `kengash skills lint` clean; evals for the six skills pass on claude and agy.

**M2 Agents and workflows.**
- [ ] Built-in skill change refused by validation, CLI and API; store copies of built-in skills ignored and listed by doctor; `init` seeds no roles.
- [ ] `agent new|edit|copy|show|remove` and `workflow new|rename|remove|route` work with `--json`; refusals write nothing and name the problem (tests per refusal).
- [ ] Own instructions written within caps, refused over them; kind change drops review edges.
- [ ] Engine tests: a custom agent first, middle, last and before `approve` runs in order; a remapped importance runs its workflow.

**M3 Controls and Agents screen.**
- [ ] The Agents screen per §5.3 creates, edits (every field), copies and removes an agent on the demo store in headless Chrome; built-ins show locked Role and Instructions.
- [ ] Captures at 390, 820, 1280 and 1440 px: no overlap, `scrollWidth == clientWidth`; axe clean.

**M4 Workflow screen and polish.**
- [ ] New, copy, rename, delete (and the in-use refusal), insert on any link, drag and Alt+↑/↓ reorder, agent swap, send-back, loop caps and routing all save and reload, in headless Chrome.
- [ ] Input audit done; all seven screens pass the capture check and axe; the other five still match their canvas boards.
- [ ] `make check` green; module docs, architecture, the system spec (§4.6, §8), skills README, README and CHANGELOG updated.
