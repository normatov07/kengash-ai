"""Plan lifecycle: new, save, show, approve, reject (SP2 spec §2.8, §2.15, §3)."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from kengash_ai import memory, settings
from kengash_ai.model import (
    PLAN_SECTIONS,
    Doc,
    Event,
    NeedsUser,
    Plan,
    PlanMode,
    PlanStatus,
    Review,
    UserError,
    utc_now,
)
from kengash_ai.ops import harvest, records
from kengash_ai.ops.workspace import resolve_slug
from kengash_ai.store import documents
from kengash_ai.store.frontmatter import read_sections
from kengash_ai.store.ids import new_id
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact


@dataclass
class PlanResult:
    id: str
    project: str
    status: str
    sections: list[str] = field(default_factory=list)
    review_skipped: bool = False
    decisions: int = 0  # Lasting decisions recorded on approval (SP16 spec §3.2)
    warnings: list[str] = field(default_factory=list)


def new_plan(
    prompt: str, *, title: str, mode: PlanMode, project: str | None, cwd: Path, by: str
) -> PlanResult:
    """Keep the user's prompt verbatim in a new plan: `grilling` in grill mode, else `draft`."""
    paths = StorePaths.default()
    slug = resolve_slug(project, cwd, paths)
    if slug is None:
        raise UserError("no project here; pass --project SLUG, or run: kengash init")
    if not prompt.strip():
        raise UserError("the prompt is empty")
    review_max = settings.load(paths, slug).plan.review_max
    status = PlanStatus.grilling if mode is PlanMode.grill else PlanStatus.draft
    with locked(paths.locks / f"{slug}.lock"):
        plan_id, uuid = new_id(records.taken_ids(paths))
        now = utc_now()
        try:
            plan = Plan(
                id=plan_id,
                uuid=uuid,
                project=slug,
                title=title,
                mode=mode,
                status=status,
                review=Review(max=review_max),
                created=now,
                updated=now,
            )
        except ValidationError as exc:
            raise UserError(records.describe(exc)) from exc
        documents.save_plan(paths.project(slug), Doc(plan, {"Prompt": prompt}))
    created = Event(
        type="plan.created", project=slug, plan=plan_id, title=plan.title, mode=mode.value, by=by
    )
    records.record(paths, f"kengash: plan new {plan_id}", created)
    return PlanResult(plan_id, slug, status.value)


def save_plan(plan_id: str, markdown: str, *, project: str | None, by: str) -> PlanResult:
    """Replace the sections given as `## Name` Markdown; the plan becomes a draft again."""
    sections = read_sections(markdown, PLAN_SECTIONS)
    if not sections:
        raise UserError("no sections given; write each as a ## <Section> heading")
    if "Prompt" in sections:
        raise UserError("the Prompt section holds the user's words and never changes")
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.ticketed:
            raise UserError(f"plan {plan.id} already has tickets; start a new plan")
        doc.sections.update(sections)
        if (
            plan.mode is not PlanMode.quick
            and "Goal" in sections
            and not doc.sections.get("Lasting decisions", "").strip()
        ):
            raise UserError(
                "add a ## Lasting decisions section: one line per choice later work must "
                "follow, or the word none"
            )
        plan.status = PlanStatus.draft
        plan.review.verdict = None
        plan.review.skipped = False
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    saved = Event(type="plan.saved", project=slug, plan=plan.id, sections=list(sections), by=by)
    records.record(paths, f"kengash: plan save {plan.id}", saved)
    return PlanResult(plan.id, slug, plan.status.value, list(sections))


def show_plan(plan_id: str, *, project: str | None) -> records.Document:
    """The plan file, its frontmatter and its sections."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    return records.document(slug, path, records.load_plan(path))


def approve_plan(plan_id: str, *, skip_review: bool, project: str | None, by: str) -> PlanResult:
    """Record the user's approval once the review passed or used up its rounds, the plan is
    quick, review is off, or the user skips the review (SP3 spec decisions 14, 30)."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    review_max = settings.load(paths, slug).plan.review_max
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.approved:
            return PlanResult(plan.id, slug, plan.status.value, review_skipped=plan.review.skipped)
        if plan.status not in (PlanStatus.draft, PlanStatus.in_review):
            raise UserError(
                f"plan {plan.id} is {plan.status.value}; only a draft plan can be approved"
            )
        review = plan.review
        unreviewed = not (
            review_max == 0
            or plan.mode is PlanMode.quick
            or review.verdict == "pass"
            or review.round >= review_max
        )
        if unreviewed and not skip_review:
            if review.verdict == "fail":
                raise NeedsUser(
                    f"plan {plan.id} failed review round {review.round} of {review_max}; "
                    f"save a revision and run: kengash plan review {plan.id}, "
                    "or approve with --skip-review"
                )
            raise NeedsUser(
                f"plan {plan.id} has no review (plan.review_max: {review_max}); "
                "approve it with --skip-review"
            )
        plan.review.skipped = unreviewed
        plan.status = PlanStatus.approved
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    approved = Event(
        type="plan.approved", project=slug, plan=plan.id, review_skipped=unreviewed, by=by
    )
    records.record(paths, f"kengash: plan approve {plan.id}", approved)
    result = PlanResult(plan.id, slug, plan.status.value, review_skipped=unreviewed)
    _record_lasting(paths, slug, plan.id, doc.sections.get("Lasting decisions", ""), result, by)
    harvest.submit(paths, f"plan {plan.id}", slug, harvest.plan_words(doc.sections))
    return result


def _record_lasting(
    paths: StorePaths, slug: str, plan_id: str, section: str, result: PlanResult, by: str
) -> None:
    """Record each `Lasting decisions` line in DECISIONS.md; a line memory refuses becomes a
    warning, since the approval already stands."""
    for line in section.splitlines():
        if not line.strip().startswith(("- ", "* ", "+ ")):
            continue
        decision, why, rejected = memory.parse_decision(line)
        if not decision:
            continue
        try:
            added = memory.add(
                paths,
                decision,
                why or f"plan {plan_id}",
                decision=True,
                rejected=rejected or None,
                project=slug,
                by=by,
                user=True,  # the user approved this plan, so these are theirs
            )
        except UserError as exc:
            result.warnings.append(f"not recorded: {decision[:60]}: {exc}")
            continue
        result.decisions += added.added


def reject_plan(plan_id: str, why: str, *, project: str | None, by: str) -> PlanResult:
    """Record the user's rejection in the Review log; saving the plan again revives it."""
    reason = records.one_line(why, "why")
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.ticketed:
            raise UserError(f"plan {plan.id} already has tickets; move them instead")
        line = redact(f"- {date.today().isoformat()} rejected by the user: {reason}")
        log = doc.sections.get("Review log", "")
        doc.sections["Review log"] = f"{log}\n{line}" if log else line
        plan.status = PlanStatus.rejected
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    rejected = Event(type="plan.rejected", project=slug, plan=plan.id, why=reason, by=by)
    records.record(paths, f"kengash: plan reject {plan.id}", rejected)
    harvest.submit(
        paths, f"plan {plan.id} rejected", slug, f"USER rejected a plan: {reason}", reason
    )
    return PlanResult(plan.id, slug, plan.status.value)
