## Context

现有系统是单人闯关：`LearningSession` 归属单个用户，答题走 `answer_game`，包含脑力扣减、原地重试、广告复活与好友助攻；题目由 `QuestionGenerationStrategy`（grounded / legacy / basic）生成，落到 `learning_sessions` + `levels`。现有 `LevelOut` 已不含 `correct_option`，判定全在服务端。本设计复用这套生成与存储，在其旁边新增对战域，不改动单人行为（见 proposal.md）。

## Goals / Non-Goals

**Goals:**

- 好友约战全流程可用：建房、分享、加入、就绪、作答、结算、复盘。
- 服务端权威计时与判定，客户端时钟不参与胜负计算。
- 对战与单人代码路径隔离，失败不影响现有闯关。

**Non-Goals:**

- 实时进度推送（WebSocket / 长轮询）与随机匹配（见 proposal Non-goals）。
- 对战胜负计入用户档案、段位或历史战绩列表。

## Decisions

### D1: 异步作答 + 仅结算点轮询

对战期双方各自作答，互不等待；先完成方在结果页每 3 秒轮询一次房间状态，直到对方完成或超时。

备选：WebSocket 实时推送对方进度。因用户已确认"各自答完看结果"，实时进度无产品需求；小程序 WebSocket 的后台断连、重连与连接数限制会显著增加复杂度。轮询只在等待窗口发生，成本可控。

### D2: 建房与出题并行（生成中状态）

房主提交关键词后立即创建房间并获得分享卡片，题目在后台生成；挑战者加入时若题目未就绪，看到"题目准备中"。grounded 生成可能耗时数十秒，等待好友点卡片的时间正好与生成并行，房主不必干等。

备选：先等生成完成再发卡片。实现更简单（房间无 generating 状态），但把生成延迟串行叠加到邀请链路上。若后台生成实现成本超预期，可降级为该方案，规格不变（规格只要求"创建后立即分享"为 SHOULD 级体验——见 spec 中 MUST 表述，实现顺序为 design 自由度）。若与 spec 冲突，以 spec 为准：房间创建后立即可分享。

### D3: 新表隔离对战域

新增三张表，均不动现有表：

- `battle_rooms`：id、host_user_id、topic、session_id（指向生成的 `learning_sessions`）、status（generating / waiting / playing / finished / void）、started_at（双方就绪信号）、expires_at、created_at。
- `battle_participants`：room_id、user_id、role（host / challenger）、status（joined / ready / playing / finished）、correct_count、total_seconds、result（win / lose / draw / null）。
- `battle_answers`：room_id、participant_id、level_position、selected_option、is_correct、answered_at；唯一约束 (participant_id, level_position) 保证幂等。

备选：复用 `AnswerAttempt`（已有 session_id + user_id）。但它携带 `hearts_after`、`response_payload` 等单人语义，且对战需要房间与参与者关联，复用会把两个域的演化耦合在一起。题目本体仍读 `levels`（只读），不重复存储。

### D4: 服务端统一起点与计时

双方均就绪时服务端写入 `battle_rooms.started_at`（唯一信号枪），`expires_at = started_at + 3min`。玩家总用时 = 本人第三题 `battle_answers.answered_at` - `started_at`，全部取服务端 UTC 时间。前端 3-2-1 倒计时是纯演出，用于覆盖加载时间差，不参与计时。

### D5: 惰性结算，无后台任务

不引入定时任务。结算发生在两个入口：任一玩家提交最后一题、以及任一方查询房间状态时。两条路径都先检查"双方均完成"或"已过 expires_at"，满足即原子结算（行锁防并发）。

备选：后台定时扫描过期房间。需要新增调度基础设施，收益仅是把结算时间从"下次访问"提前到"超时瞬间"；由于等待方每 3 秒轮询，惰性结算的实际可见延迟不超过一个轮询周期。

### D6: 独立对战答题接口

新增对战提交接口（按房间寻址），与 `answer_game` 完全分离：校验房间 playing 状态与参与者身份后判定对错，无论对错都推进参与者的当前题号，不触碰脑力、复活、助攻与用户统计。重复提交由 (participant_id, level_position) 唯一约束兜底，返回首次结果。

### D7: 前端页面与入口

新增对战页面组（创建/等待、受邀加入、作答、结果），微信分享卡片 path 携带房间 id。作答页复用现有题目展示组件，隐藏脑力与复活 UI。结果页分两态：等待对方（轮询中）与已结算（胜负 + 逐题复盘）。复盘数据由结算接口按"本人已完成"条件返回。

## Risks / Trade-offs

- [轮询可见延迟] → 等待方 3 秒轮询，最坏延迟一个周期；对战期本身无轮询。
- [生成失败发生在好友加入后] → 房间进入错误态，双方均可见并引导重新发起；不产生胜负。
- [3 分钟窗口对慢网络偏紧] → 服务端计时从双方就绪开始，页面加载在就绪之前完成；超时结算已有"完成者优先"兜底。
- [双方并发触发结算] → 结算走行锁 + 状态条件更新，只生效一次。
- [分享卡片被转发给多人] → 房间容量 2，后到者收到"房间已满"。

## Migration Plan

1. 新增 Alembic 迁移创建三张对战表，不修改既有表。
2. 后端先上线路由与服务（对单人无影响）。
3. 前端发布对战入口与页面。
4. 回滚：前端隐藏入口即可停用；后端路由保留无害；如需彻底回滚，删除三张表（对战数据可丢弃，不影响单人数据）。

## Open Questions

- 对战胜负是否在未来计入用户档案（战绩 / 胜率）——纯增量，不影响本期结构。
- 结果页与等待页视觉稿细节——沿用现有设计系统，原型阶段确认。
