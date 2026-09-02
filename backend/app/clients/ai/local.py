from __future__ import annotations

from app.schemas.game import GeneratedGame
from app.schemas.research import (
    GroundedGeneratedGame,
    GroundingIssue,
    GroundingReport,
    ResearchContext,
)


class LocalContentGenerator:
    async def generate(self, topic: str) -> GeneratedGame:
        return GeneratedGame.model_validate(
            {
                "title": topic,
                "levels": [
                    {
                        "tier": "novice",
                        "title": "新手关",
                        "intro": f"先抓住 {topic} 的核心：它像给一件东西贴上清楚的姓名条。",
                        "question": "刚才这一步最重要的是什么？",
                        "options": ["先认清核心概念", "只记复杂名词", "直接跳到最后"],
                        "correct_option": 0,
                        "wrong_explanation": "像行李箱没贴姓名条，看着都差不多，拿的时候当然容易认错。",
                        "praise": "脑子到账！第一块知识已经放稳了。",
                        "takeaway": "先认清一个核心概念",
                    },
                    {
                        "tier": "advanced",
                        "title": "进阶关",
                        "intro": "接着看它什么时候生效，就像门卫要核对通行条件。",
                        "question": "要正确应用这个概念，下一步该做什么？",
                        "options": ["确认使用条件", "任何时候都照搬", "忽略实际目标"],
                        "correct_option": 0,
                        "wrong_explanation": "门卫不会见人就放，条件没核对，后面的动作就没有可靠依据。",
                        "praise": "进阶关拿下，条件已经看得很清楚！",
                        "takeaway": "确认概念的使用条件",
                    },
                    {
                        "tier": "boss",
                        "title": "Boss 战",
                        "intro": "最后把概念和条件拼起来，像先认人再验票。",
                        "question": "面对一个新问题，哪种做法最稳？",
                        "options": ["先认概念再核对条件", "背一句话直接套", "跳过分析碰运气"],
                        "correct_option": 0,
                        "wrong_explanation": "像没看站名就上车，哪怕车跑得快，也可能离目的地越来越远。",
                        "praise": "Boss 倒下，三关全拿下！",
                        "takeaway": "组合概念和条件解决问题",
                    },
                ],
                "summary": [
                    "先认清核心概念",
                    "再确认使用条件",
                    "最后组合解决问题",
                ],
            }
        )

    async def generate_grounded(
        self,
        context: ResearchContext,
        issues: list[GroundingIssue],
    ) -> GroundedGeneratedGame:
        del issues
        game = await self.generate(context.interpretation)
        available_ids = [source.id for source in context.sources]
        fact_ids = [
            source_id
            for fact in context.facts
            for source_id in fact.source_ids
            if source_id in available_ids
        ]
        selected_ids = list(dict.fromkeys(fact_ids))[:5] or available_ids[:1]
        payload = game.model_dump(mode="python")
        for level in payload["levels"]:
            level["source_ids"] = selected_ids
        return GroundedGeneratedGame.model_validate(payload)

    async def validate_grounding(
        self,
        context: ResearchContext,
        game: GroundedGeneratedGame,
    ) -> GroundingReport:
        del context, game
        return GroundingReport(passed=True, issues=[])
