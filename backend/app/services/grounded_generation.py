from __future__ import annotations

from app.clients.ai import ContentGenerationError, GroundedContentGenerator, GroundingValidator
from app.core.generation_budget import generation_stage
from app.core.observability import stage, record_counts, emit
from app.schemas.research import (
    GROUNDING_CHECK_FIELDS,
    GroundedGeneratedGame,
    GroundingIssue,
    ResearchContext,
)


class GroundingValidationError(RuntimeError):
    code = "GROUNDING_VALIDATION_FAILED"


def _source_issues(
    context: ResearchContext,
    game: GroundedGeneratedGame,
) -> list[GroundingIssue]:
    known_source_ids = {source.id for source in context.sources}
    issues: list[GroundingIssue] = []
    for position, level in enumerate(game.levels):
        unknown_ids = sorted(set(level.source_ids) - known_source_ids)
        if unknown_ids:
            issues.append(
                GroundingIssue(
                    level_position=position,
                    field=f"levels[{position}].source_ids",
                    message=(
                        "关卡引用了不存在的来源 ID："
                        f"{', '.join(unknown_ids)}；只能使用 evidence.sources 中的 ID"
                    ),
                )
            )
    return issues


def _normalize_report_issues(
    issues: list[GroundingIssue],
) -> list[GroundingIssue]:
    allowed_fields = set(GROUNDING_CHECK_FIELDS)
    normalized: list[GroundingIssue] = []
    for issue in issues:
        if issue.field in allowed_fields:
            normalized.append(issue)
            continue
        normalized.append(
            GroundingIssue(
                level_position=issue.level_position,
                field=issue.field,
                message=f"校验器报告了未登记字段；请复核相关内容：{issue.message}",
            )
        )
    return normalized


async def generate_grounded_game(
    context: ResearchContext,
    *,
    generator: GroundedContentGenerator,
    validator: GroundingValidator,
    max_regenerations: int = 1,
) -> GroundedGeneratedGame:
    if not 0 <= max_regenerations <= 1:
        raise ValueError("max_regenerations 必须介于 0 和 1")

    feedback: list[GroundingIssue] = []
    for attempt in range(max_regenerations + 1):
        try:
            async with generation_stage("generation"):
                with stage("generation"):
                    record_counts(model_calls=1)
                    game = await generator.generate_grounded(context, feedback)
        except ContentGenerationError as exc:
            if exc.reason != "INVALID_GENERATED_OUTPUT" or attempt == max_regenerations:
                raise
            # Schema correction shares the same single regeneration slot and
            # absolute deadline as factual corrections. Invalid JSON is not a game.
            feedback = [GroundingIssue(field="schema", message=(
                "上一次输出不是完整且符合 Schema 的 JSON。请仅输出一个完整 JSON 对象，"
                "不要 Markdown 代码围栏、说明文字或不合法的转义；保留恰好三关和全部必填字段。"
            ))]
            continue
        deterministic_issues = _source_issues(context, game)
        if deterministic_issues:
            record_counts(validation_issues=len(deterministic_issues))
            feedback = deterministic_issues
            continue

        async with generation_stage("validation"):
            with stage("validation"):
                record_counts(model_calls=1)
                report = await validator.validate_grounding(context, game)
        record_counts(validation_issues=len(report.issues))
        emit("validation_checked", stage="validation", outcome="success" if report.passed else "error", validation_issues=len(report.issues))
        if report.passed:
            return game
        feedback = _normalize_report_issues(report.issues)

    raise GroundingValidationError("生成内容经过一次修正后仍未通过事实一致性校验")
