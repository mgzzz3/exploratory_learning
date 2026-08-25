from __future__ import annotations

from dataclasses import dataclass, field

from app.clients.ai import ContentGenerationError
from app.clients.wechat import WechatClientError, WechatSession
from app.schemas.game import GeneratedGame


def generated_game(topic: str) -> GeneratedGame:
    return GeneratedGame.model_validate(
        {
            "title": topic,
            "levels": [
                {
                    "tier": "novice",
                    "title": "新手关",
                    "intro": f"{topic} 的第一个概念，就像给东西贴姓名条。",
                    "question": "哪一个说法最符合刚才的知识点？",
                    "options": ["正确说法", "反着说", "完全无关"],
                    "correct_option": 0,
                    "wrong_explanation": "像拿错了贴纸：名字和东西没有对应上，所以这次不能算对。",
                    "praise": "漂亮，第一块知识已经装进脑袋了！",
                    "takeaway": "先把概念和它的名字对应起来",
                },
                {
                    "tier": "advanced",
                    "title": "进阶关",
                    "intro": "第二个概念像门卫，条件符合才会放行。",
                    "question": "门卫在什么情况下会放行？",
                    "options": ["条件符合", "永远放行", "永远拦住"],
                    "correct_option": 0,
                    "wrong_explanation": "门卫要看通行条件，不会不看规则就直接放人。",
                    "praise": "进阶关也拿下，思路很稳！",
                    "takeaway": "条件决定后面的动作是否发生",
                },
                {
                    "tier": "boss",
                    "title": "Boss 战",
                    "intro": "最后把前两个概念合在一起。",
                    "question": "哪一个组合能正确完成目标？",
                    "options": ["先命名再判断", "只猜答案", "跳过条件"],
                    "correct_option": 0,
                    "wrong_explanation": "像先找座位再检票，顺序和条件缺一不可。",
                    "praise": "Boss 倒下，三关全拿下！",
                    "takeaway": "组合使用概念解决完整问题",
                },
            ],
            "summary": [
                "概念要和名字对应",
                "条件决定动作",
                "组合概念解决完整问题",
            ],
        }
    )


@dataclass
class FakeWechatClient:
    blocked_topics: set[str] = field(default_factory=set)
    login_error: bool = False
    safety_error: bool = False
    login_calls: list[str] = field(default_factory=list)
    safety_calls: list[tuple[str, str]] = field(default_factory=list)

    async def code_to_session(self, code: str) -> WechatSession:
        self.login_calls.append(code)
        if self.login_error:
            raise WechatClientError("微信登录暂时不可用")
        return WechatSession(openid=f"openid-{code}")

    async def check_message(self, openid: str, content: str) -> bool:
        self.safety_calls.append((openid, content))
        if self.safety_error:
            raise WechatClientError("内容安全服务暂时不可用")
        return content not in self.blocked_topics


@dataclass
class FakeContentGenerator:
    error: bool = False
    calls: list[str] = field(default_factory=list)

    async def generate(self, topic: str) -> GeneratedGame:
        self.calls.append(topic)
        if self.error:
            raise ContentGenerationError("模型没有返回完整关卡")
        return generated_game(topic)
