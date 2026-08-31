## Context

原线上链路在微信内容安全检查后调用 `ContentGenerator.generate(topic)`，通过严格 JSON Schema 产出三关内容。本变更的本地实现已增加联网策略、两个 Tavily 适配工具、证据模型和来源字段，但“高情商聊天”的研究复现暴露了收敛缺陷：两次搜索和一次提取已取得资料，Agent 继续请求搜索时却直接以工具预算耗尽结束。当前纠错还会重新建立调用轨迹与 Agent 输入，未把已有证据带入下一次整理；通用异常包装会丢失供应商错误类别。

本次设计修订针对这些已确认的问题补齐请求级研究状态、收敛与预算分配，并新增用户主动选择的受控基础知识入口。设计描述的是待实施目标，不代表当前代码已经修复，也不代表本地变更已经部署到生产。

本变更横跨 FastAPI 服务、AI 客户端、MySQL 模型/API 契约和 Taro 通关页，并引入外部搜索供应商。需求边界见 `proposal.md`，可验收行为见 `specs/grounded-game-generation/spec.md`。

当前实现还受以下约束影响：

- 微信内容安全检查 MUST 继续发生在任何 Tavily 或 DeepSeek 调用之前。
- 新联网能力 MUST 能通过部署配置整体剥离，且 legacy 模式保留 `ContentGenerator.generate(topic)` 调用链。客户端不能覆盖全局部署模式；符合准入规则的独立基础知识请求不是部署模式切换。
- 前端当前创建游戏请求为同步 HTTP 请求；Agent 多轮模型调用、搜索正文和整页提取不能无限延长请求，也不能把供应商异常伪装成普通网络故障。
- 微信小程序 `WebView` 只能打开已配置业务域名的第三方网页，无法预先白名单所有搜索来源。因此微信端采用复制来源链接，H5 端才直接打开；不新增任意域名代理。
- 用户提供的 Tavily 凭证只属于后端运行环境。真实密钥不会进入本变更目录、版本控制、前端环境变量或日志。
- 官方 `TavilySearch` 只把查询、深度、日期、域名等参数放进 Agent 可见的调用 Schema；`max_results`、`include_raw_content` 和 `country` 必须在工具实例化时确定，而 Tavily API 新增的 `language/filter_by_language` 也没有出现在该官方工具的 Agent Schema 中。因此需要受控适配层，不能用一个固定原始实例同时满足摘要/全文、动态条数和跨语言策略。

## Goals / Non-Goals

**Goals:**

- 以统一策略接口隔离 grounded 与 legacy 生成链路，使 Tavily/LangChain 研究组件可以在不修改 API、数据库或旧生成器的情况下停用，legacy 安装甚至可以不包含研究依赖。
- 建立可测试、可替换的“输入安全 → AI 研究 Agent 自主调用 Search/Extract → 使用已有证据收敛 → 有据生成 → 事实校验 → 原子持久化”流水线，纠错不重建研究，也不重置预算。
- 兼容关键词和单个公开网页输入，对新概念、常见概念、多义词和指定页面采用匹配的失败关闭策略。
- 让 Agent 在确定性安全与成本边界内自主选择工具、顺序和参数，同时保证每局 grounded 游戏至少成功使用一个与输入类型匹配的联网工具。
- 保持已有游戏响应字段兼容，并让新生成游戏的依据可持久追溯。
- 将原失败请求与后续基础知识请求隔离，提供可验证的用户/主题绑定及持久结果标识，不用模型的“熟悉程度”作为兜底授权。
- 通过依赖倒置和确定性 fake 支持严格 TDD，不让单元/集成测试消耗 Tavily 或 DeepSeek 配额。
- 将检索次数、延迟、来源数量、拒绝原因和校验结果纳入不含密钥/身份信息的可观测数据。

**Non-Goals:**

- 不建设向量数据库、长期知识库、网页镜像、通用爬虫或多 Agent 系统；研究阶段只使用一个受控 Agent。
- 不允许用户编辑来源，不把任意网页全文永久保存到数据库。
- 不在首版缓存搜索结果；每次常规 grounded 创建请求都重新检索，历史游戏仅返回创建时保存的来源。本请求内复用证据不是跨请求缓存；legacy 与独立基础知识请求不检索。
- 不改变三关、三选一、生命值、复活和分享等既有玩法。
- 不在本变更中配置任意第三方来源为微信业务域名，也不通过 `bkgame.cc` 代理外部网页。
- 不承诺读取登录墙、付费墙、私网、文件下载或需要用户 Cookie 的页面。
- 不允许 grounded 请求在 Tavily/Agent 故障后自动静默调用 legacy；全局降级仍是修改环境配置并重启或重新部署的运维动作。显式基础知识兜底必须另发请求，不把失败草稿包装成兜底结果。
- 不建设通用主题分类服务、兜底管理后台、分布式研究任务队列或长连接进度服务；保守准入规则、短期许可和请求级状态足以完成本次修复。

## Decisions

### 1. 用策略接口和装配工厂实现部署级可剥离

在内容安全检查之后、数据库写入之前使用 `QuestionGenerationStrategy` 协议。协议接收权威校验后的输入并返回统一的可持久化生成结果，包含游戏草稿、输入类型、规范化来源输入、资料获取时间、来源、各关来源 ID、`generation_mode` 和核验提示。应用工厂仅根据后端 `QUESTION_GENERATION_MODE=grounded|legacy` 装配常规创建策略；`POST /api/v1/games` 的严格请求 Schema 拒绝策略或自行声明兜底等额外字段。

`GroundedGenerationStrategy` 组合 URL 安全、研究 Agent、证据验收、有据生成和事实校验。`LegacyGenerationStrategy` 复用原 `ContentGenerator.generate(topic)`，只接受 80 字以内关键词；遇到 URL 时在调用旧生成器前返回 `URL_REQUIRES_RESEARCH`。legacy 结果显式填充 `input_type=keyword`、`source_input=null`、`retrieved_at=null`、`sources=[]` 和空的关卡来源 ID，因此 API 与数据库仍使用同一写入路径。

研究模块从应用入口延迟导入：只有 grounded 工厂分支导入并构造 LangChain/Tavily 类。`langchain`、`langchain-deepseek` 和 `langchain-tavily` 放入 Python 的 `research` 可选依赖组；grounded 镜像安装 `.[research]`，legacy 镜像只需基础依赖。这既支持通过配置快速切换同一完整镜像，也支持构建不含研究依赖的最小 legacy 镜像。完整镜像切到 legacy 时同样不得读取 Tavily key 或初始化研究客户端。

单次 grounded 请求失败只返回稳定业务错误；符合条件时可附加基础知识许可，但不会继续生成。另设 `BasicKnowledgeService`，仅供经过许可验证的独立端点调用，复用原关键词生成器并输出 `generation_mode=basic`，不调用 grounded 策略、不创建第二个全局模式开关。它与 `LegacyGenerationStrategy` 共享旧生成能力，但拥有自己的准入、请求预算与结果标识。

运维降级仍必须修改 `QUESTION_GENERATION_MODE` 并重启或重新部署；legacy 部署不签发或受理基础知识许可，因为其常规关键词入口已经走旧逻辑。数据库兼容列予以保留，模式切换不要求回滚迁移。

**备选方案：** 同请求自动调用旧生成器会混淆失败与成功语义；让客户端任意传 `mode=legacy` 会绕过准入。仅保留运维开关又无法满足普通主题的用户主动兜底，因此采用“全局策略工厂 + 独立受控入口 + 统一持久化结果”。

### 2. 使用 LangChain `create_agent` 构建单一研究 Agent

研究阶段使用官方 `ChatDeepSeek` 承载后端配置的、经能力验证的 DeepSeek 模型，通过 `langchain.agents.create_agent` 创建单一 Agent。Agent 的联网工具仍只有 Search/Extract 两个适配器；使用 `response_format=ToolStrategy(ResearchConclusion, ...)` 获取 `structured_response`，不再从自然语言回答中截取第一个 JSON 对象。`ResearchConclusion` 只让模型输出研究状态、主题解释、选中的来源 ID、带来源关联的事实和必要的候选解释；完整 `ResearchBundle` 由服务端补齐可信元数据。

Agent 只负责联网研究、主题解释、来源选择和证据整理。现有 OpenAI SDK Responses 严格 JSON Schema 链路继续负责三关生成与事实校验。研究客户端显式使用非思考模式，按 DeepSeek Chat Completions 参数传入 `extra_body={"thinking":{"type":"disabled"}}`；不将这一参数原样混入 Responses 请求，也不擅自替换模型。除启动时的依赖/配置检查外，发布门禁必须用配置的真实模型验证“调用工具 → 接收工具结果 → 结构化结论”，仅成功 `bind_tools` 不算能力验证。legacy 不执行该研究检查。依据：[ChatDeepSeek 集成](https://docs.langchain.com/oss/python/integrations/chat/deepseek)、[DeepSeek 思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

每个请求创建一次 `ResearchRunState`，同时拥有证据台账、真实工具轨迹、消息历史、正文工作区、截止时间、调用计数、研究阶段和一次纠错额度；同一请求的整理与纠错共享它。工具成功返回后立即把规范化来源和证据块登记进台账，再把带稳定 ID 的结果交给模型。时间、URL、获取方式、调用 ID、耗时等由服务端生成，模型无需重新抄写，更不能提供其权威值。

研究中间件通过 `ModelRequest.override(tools=...)` 筛选预注册工具。异步路径使用对应异步 hook，模型计数在实际调用前执行；工具执行边界再次校验参数、权限和余额，防止旧消息或同轮多个调用绕过筛选。结构化结论使用的响应工具不是第三个联网工具，不消耗 Tavily 次数，但它所在的模型调用计入六次上限。筛除联网工具时保留结构化响应能力，不以 `tool_choice=none` 一并禁掉结论。依据：[LangChain 自定义中间件](https://docs.langchain.com/oss/python/langchain/middleware/custom)、[结构化输出](https://docs.langchain.com/oss/python/langchain/structured-output)。

停止条件与纠错规则如下：

- 资料已足以形成三关、模型主动提交结论时，立即验收，不要求用满工具预算。
- 某工具次数用尽时不再向模型提供它；总工具预算用尽、达到检索截止时间或只剩整理/纠错模型额度时，进入 `finalize`，停止新增联网调用，仅使用台账整理结论。
- 若 Agent 仍发出超限搜索意图，执行边界不发送外部请求，返回与该调用 ID 对应的“未执行，使用已有证据整理”工具反馈并进入整理。该反馈不能记成成功证据；安全违规、未知工具及真实供应商故障仍按错误处理。
- `ToolStrategy.handle_errors` 使用请求级、有限的错误处理器，不采用无限自动修复；只反馈安全的字段路径和错误类别。结构错误修复与后置来源/轨迹修复共用一次额度，第二次无效立即失败。后置修复继续同一个 Agent 的消息历史与台账，不能重新以原始关键词启动新研究。
- 已有成功联网资料的格式修复只开放结论输出，不再 Search/Extract。首轮零成功调用时，唯一一次纠正可在原剩余预算内补齐必需的首次工具调用，再整理；不能重置时限或计数。
- 来源 ID 必须实际存在于台账，关键词必须成功 Search，URL 必须成功 Extract 原页面。整理与纠错不降低来源数量、相关性或事实约束；正常的 `insufficient/ambiguous/conflict` 是业务结论，不启动格式纠错循环。

同一请求的工具额度预占必须原子化，避免同轮并发工具超支。结束、异常和取消统一释放正文及消息引用；不使用跨请求 checkpointer 保存研究内容。

**备选方案：** 单纯增加搜索次数不能解决不收敛；重新启动研究会丢失证据并重复消耗预算；要求模型复写完整调用轨迹增加格式错误且不能提供真实性。固定检索顺序又不满足自主编排，所以采用官方 Agent、请求级台账、有限纠错和服务端强制收敛。

### 3. 向 Agent 提供两个类型化适配工具，底层严格使用官方类

Agent 可见的工具保持为两个：

- `adaptive_tavily_search`：底层为官方 `langchain_tavily.TavilySearch`。
- `adaptive_tavily_extract`：底层为官方 `langchain_tavily.TavilyExtract`。

适配层不是新的搜索实现，只负责补齐安全输入 Schema、在每次调用时实例化正确配置的官方工具、规范化返回值和执行预算。适配器以 Agent 选择的 `max_results`、`include_raw_content` 和 `country` 构造官方 Search 实例，再在调用参数中传入查询、深度、日期、域名以及官方底层 API 可透传的 `language/filter_by_language`。新参数透传必须由所锁定版本的官方接口和契约测试验证，不能假设原工具 Schema 会保留未知字段，也不能静默丢弃语言参数。网络请求始终由官方 LangChain/Tavily 包执行。依据：[TavilySearch 集成](https://docs.langchain.com/oss/python/integrations/tools/tavily_search)、[Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)。

`AdaptiveSearchInput` 对 Agent 暴露：`query`、`content_mode`（`summary|full`）、`search_depth`、`max_results`、`topic`、`time_range`/起止日期、`include_domains`、`exclude_domains`、`country`、`language` 和语言过滤意图。适配器强制 `include_answer=False`，因为 Tavily 生成的答案不是可独立核验的一手证据；同时固定禁用图片和自动参数，让参数决策来自 Agent 且成本可预测。`summary` 映射为 `include_raw_content=False`，`full` 映射为 `include_raw_content="markdown"`。

`AdaptiveExtractInput` 对 Agent 暴露：1～3 个公开 URL、`extract_depth`、是否整页提取和可选相关性意图。用户直接提供 URL 时首次调用强制整页模式，即不传 `query` 或相关片段数量参数；Search 后补读页面时可以传 `query` 取得相关内容块。输出统一映射为来源、正文、失败 URL、响应时间和用量，不把供应商异常对象直接放入 Agent 上下文。依据：[TavilyExtract 集成](https://docs.langchain.com/oss/python/integrations/tools/tavily_extract)、[Tavily Extract API](https://docs.tavily.com/documentation/api-reference/endpoint/extract)。

保留异步 `ResearchTools`/供应商协议供依赖注入；测试使用记录参数与调用轨迹的 fake，`USE_MOCK_SERVICES=true` 时不访问 Tavily 或 DeepSeek。

**备选方案：** 一个固定 `TavilySearch` 实例不能动态改变全文、条数与国家；向 Agent 暴露多个摘要/全文预设实例会把两个概念工具膨胀成多个名称并增加选择歧义。因此使用两个类型化适配工具。

### 4. 使用“自主研究、确定性验收”的 Hybrid RAG 流水线

grounded 策略的具体顺序如下：

1. 清理输入并先执行微信内容安全检查。完整输入若可解析为单个公开 HTTP(S) URL 则进入 URL 模式，否则进入关键词模式；拒绝含用户凭证、非 HTTP(S)、本机、私网和链路本地目标。
2. 内容安全通过后创建唯一总截止时间及 `ResearchRunState`。向研究 Agent 提供原始输入、输入类型、当前日期、用户语言和两个适配工具。Agent 自主执行以下典型路径之一：关键词 `Search`；复杂关键词 `Search → Extract`；URL `Extract`；需要补充的 URL `Extract → Search`。
3. 工具边界规范化 URL、移除常见追踪参数、校验公开目标并把外部内容标为不可信。网页完整正文先从 Tavily 取回到请求级临时内存，再按标题/段落边界分块；较长页面向 Agent 返回章节索引和受预算约束的内容块，Agent 可用 Extract 的相关性意图补取重点，禁止无提示地只截取页面开头。
4. 及时停止检索，Agent 从台账已有证据形成 `ResearchConclusion`，输出 `ready`、`ambiguous`、`insufficient` 或 `conflict`。服务端组合 `ResearchBundle`，检查真实调用轨迹、被选来源 ID、输入模式数量和证据内容；关键词需要 2～5 条来源，URL 模式必须包含用户页面且允许 1～5 条来源。一次必要纠错使用同一台账与剩余预算。
5. `ready` 的 `ResearchContext` 进入结构化出题。`GroundedGeneratedGame` 延续现有 `GeneratedGame` 规则，并要求每关给出非空 `source_ids`。
6. 保存前先做确定性检查：来源 ID 存在、每关有证据、正确选项唯一、结构完整。随后用独立严格 Schema 输出 `GroundingReport`，逐关检查介绍、题干、正确答案、错误解释、要点和总结是否被证据支持。
7. 校验不通过时把具体问题反馈给生成步骤，最多重新生成一次并再次校验；这些调用共享总截止时间，不重新研究。剩余时间不足或仍失败则拒绝创建。仅最终通过的游戏与来源在一个数据库事务中写入；失败时只能附加符合第 11 节规则的许可，不能在此流水线内调用基础知识生成。

联网内容始终处于清晰的数据边界内。网页中的命令、密钥请求、工具调用建议或角色指令均不得影响系统提示、工具白名单和输出 Schema；模型不能使用研究上下文之外的事实填补缺口。

**备选方案：** 完全信任 Agent 最终回答会让它绕过工具或引用不存在的来源；完全固定工具顺序又无法适应 URL、简单摘要和复杂全文。因此采用 Agent 自主研究加确定性轨迹/证据验收。

### 5. 使用受控参数策略覆盖国内外与复杂度差异

Agent 的工具描述提供以下选择指导，适配器负责硬上限而不是替 Agent 做语义决策：

| 场景 | 推荐工具与参数 | 服务端边界 |
| --- | --- | --- |
| 简单、定义明确的关键词 | Search；`basic` 或 `fast`；摘要；3 条 | 不返回原始正文 |
| 一般关键词 | Search；`basic`；摘要；5 条 | 最多 5 条 |
| 新知识、复杂或多义概念 | Search；`advanced`；5～8 条；必要时 Markdown 正文 | 全文模式最多 3 条正文，其余保留摘要 |
| 搜索摘要不足 | Extract 关键结果；`basic` 或 `advanced`；可带相关性 `query` | 单次最多 3 个 URL |
| 用户直接提供普通网页 | Extract；`basic`；不传 `query` | 必须包含原始 URL |
| 用户提供复杂网页/表格 | Extract；`advanced`；不传 `query` | 正文分块并受总字符预算限制 |
| 新闻或强时效主题 | Search；`news` 与时间范围 | 日期参数必须合法 |
| 中国地域内容 | Search；中文查询、`country=china`、`language=zh-cn` | `country` 仅与 `general` 组合 |
| 具体城市内容 | 城市写入 query，国家参数仅作增强 | 不构造不存在的 city 参数 |
| 全球技术内容 | 不限制国家；必要时补充英文查询 | 默认不严格过滤语言 |

语言参数默认用于排序提升而非严格过滤，避免中文用户看不到英文一手资料。只有用户明确要求单一语言时才启用严格语言过滤。`auto_parameters` 保持关闭，因为本方案已经由 Agent 显式选择参数，且自动升级 advanced 会使成本难以预测。

**备选方案：** 按用户界面语言固定只搜中文或只搜英文会降低一手资料覆盖；始终指定中国会对全球技术概念产生偏差；始终 advanced/full 会放大延迟、上下文和费用。因此采用语义驱动的动态参数加确定性上限。

### 6. 证据模型与 API 契约采用可追溯 ID

新增 Pydantic 模型：

- `InputDescriptor`：包含 `input_type`（`keyword|url`）、规范化输入和用于界面展示的主题标题。
- `ResearchRunState`：请求级运行状态，拥有只属于本请求的证据台账、消息历史、正文工作区、预算与纠错计数，不可持久化或发送给客户端。
- `ToolCallRecord`：服务端记录工具名、安全参数类别、响应引用、耗时、物理请求次数及成功/失败/未执行状态，供强制联网与预算检查使用；未执行记录不能成为来源。
- `SearchResult` 与 `ExtractedPage`：分别承接官方 Search 与 Extract 返回值的受控映射；网页正文只存在于请求级内存。
- `SourceReference`：客户端可见且可持久化的稳定来源，包含 `id`、`title`、`url`、`domain` 和 `acquisition_method`（`search|extract`）。
- `ResearchConclusion`：模型输出的研究状态、主题解释、来源 ID、带证据引用的事实及候选解释，不包含模型自行填写的调用耗时、检索时间或来源 URL。
- `ResearchBundle` / `ResearchContext`：用结论与服务端台账组装的完整研究结果/生成上下文，包含研究状态、采用的主题解释、检索时间、来源、可支持事实和真实工具调用轨迹。
- `GroundedGeneratedLevel`：在现有关卡字段基础上增加 `source_ids`。
- `GroundingReport`：总体是否通过及逐项问题，不向客户端暴露内部提示或网页片段。

创建游戏请求继续使用 `topic` 字段以兼容现有客户端。grounded 策略按输入类型分支校验：关键词最长 80 字符，单个公开 URL 最长 2048 字符；legacy 策略在通用分类后拒绝 URL，只把 80 字以内关键词交给旧生成器。`learning_sessions.topic` 保持最长 80 字符并作为展示标题：关键词模式保存原关键词，URL 模式保存提取到的页面标题，缺失时回退为域名；原始的规范化输入另存到 `source_input`。

`GameOut` 增加向后兼容字段 `input_type: keyword | url`、`retrieved_at: datetime | null`、`sources: list[SourceReference]`、`generation_mode: grounded | legacy | basic` 和 `verification_notice: string | null`。grounded 关键词游戏 MUST 有 2～5 条来源；grounded URL 游戏 MUST 包含用户输入页面且允许 1～5 条来源。legacy 与迁移前历史游戏返回 `input_type=keyword`、`retrieved_at=null` 和空来源。基础知识结果固定 `generation_mode=basic`、`verification_notice="未经联网核验"`、`retrieved_at=null`、`sources=[]`，每关来源 ID 为空。模式和提示来自持久化字段，不通过来源为空或客户端本次点击状态推断。客户端仍只展示游戏级来源列表。

错误响应沿用现有 `AppError` 外壳：

- `INVALID_SOURCE_URL`：HTTP 422，URL 不合法、目标不公开或不允许访问。
- `PAGE_UNREADABLE`：HTTP 422，目标公开但 Tavily 无法抽取足够正文。
- `TOPIC_AMBIGUOUS`：HTTP 422，`details.interpretations` 最多三个候选解释。
- `SOURCES_INSUFFICIENT`：HTTP 422。
- `RESEARCH_AGENT_FAILED`：HTTP 502，Agent 未按要求调用工具、结构化结果无效或超过编排预算。
- `GROUNDING_VALIDATION_FAILED`：HTTP 502。
- `SEARCH_UNAVAILABLE`：HTTP 503，Tavily 认证、限流或可用性故障。
- `URL_REQUIRES_RESEARCH`：HTTP 422，当前部署处于 legacy 模式，不能读取用户指定网页。
- `BASIC_MODE_NOT_ALLOWED`：HTTP 403，独立基础知识请求未获有效许可、主题/用户不匹配、许可过期或当前策略不允许；不泄露原失败请求内容。结构字段不合法仍返回既有 `VALIDATION_ERROR`（422），登录失效仍走既有认证契约。

原 `AI_GENERATION_FAILED`（502）、内容安全与认证错误契约保持不变。新增 `error.details.request_id`、安全枚举 `reason` 及可选 `fallback`，不替换既有顶层 `code/message` 或歧义候选字段。具体错误分层见第 12 节，基础知识请求与许可字段见第 11 节。

**备选方案：** 在文案中嵌入脚注会破坏现有关卡 UI 和文本长度约束；只返回 URL 而不保存会导致历史游戏依据变化。因此采用稳定 ID 加游戏级来源元数据。

### 7. 来源元数据随游戏持久化，正文不落库

来源迁移为 `learning_sessions` 增加非空 `input_type`（默认 `keyword`）、可空 `source_input`、可空 `retrieved_at` 和非空 JSON `sources`（默认空数组），为 `levels` 增加非空 JSON `source_ids`（默认空数组）。URL 模式下 `source_input` 保存通过安全校验并移除常见追踪参数后的规范 URL；不得保存 URL 用户凭证、敏感查询参数或片段。

已有 `0002_grounded_sources` 之后新增独立 Alembic revision，不改写可能已经应用的迁移。新增 `learning_sessions.generation_mode`（非空，默认 `legacy`）、可空 `verification_notice` 和可空唯一 `basic_fallback_id`。对已有、具备真实检索时间和非空来源的记录回填 `grounded`；没有依据的旧记录保持 `legacy`，不补造来源，也不把旧游戏标为用户主动选择的 `basic`。新增游戏由统一结果显式写入模式；数据库/API 校验 basic 的提示及空来源不变量。

grounded、legacy 和受控 basic 三条入口都先返回统一的完整结果，再由同一个事务写入会话、三关、模式、提示及来源关联；任何研究、旧生成或校验异常都发生在写入前，写入异常则整体回滚。取消必须向上传播，不能吞掉取消后继续提交；提交前再次检查请求状态。数据库只保存最终来源元数据，不保存 Tavily 原始响应、完整网页正文或 Agent 中间消息；legacy/basic 保存空来源和空检索时间。

`basic_fallback_id` 保存许可的随机 ID 而非完整 token；唯一约束保证同一许可最多创建一局。许可有效期间重放已完成请求时，在验证当前用户、主题和许可后返回其已有游戏；并发提交触发唯一冲突时整体回滚竞争事务，再读取同属该用户的完整游戏。不得在外部生成期间持有数据库行锁，也不承诺不同进程的并发请求绝对只消耗一次模型费用。不创建用于兜底关联的失败游戏占位记录。

已有记录通过数据库默认值兼容，不回填虚构来源。旧客户端继续读取 `topic`；URL 输入生成的页面标题也能满足现有首页、分享和历史详情对短标题的预期。

**备选方案：** 独立来源表适合跨游戏复用，但首版没有该需求；将结果模式仅保存在客户端会使重进游戏丢失告知；修改旧迁移会破坏已部署数据库。采用兼容性增量列、原子写入和数据库唯一约束。

### 8. 前端区分输入模式、业务失败与网络失败

首页仍使用同一个输入框与请求字段，但数据层允许最多 2048 字符，并在提交前仅做轻量的关键词/URL 判定；后端始终执行权威校验。输入框占位、长 URL 展示、加载文案、来源区和错误状态必须先在 `design/` 中补齐原型并由用户确认，再按原型实现 TSX/SCSS，不能自行扩展 UI。

已确认的联网原型不自动覆盖新增基础知识交互。下一轮原型需补齐：获准失败状态中的“重试联网/基础知识模式”操作及选择前告知、未获准时无兜底入口、许可过期、基础知识生成失败，以及创建成功、答题中、通关和重新进入时的“基础知识模式 · 未经联网核验”标识。布局、配色、组件和文案位置延续已有设计，展示原型并取得新的明确确认后才能实现对应 UI；本设计文档不替代原型确认。

创建期间根据已知输入类型显示已确认的加载文案；同步接口没有真实阶段事件，不能用计时器伪造“资料已搜到一半”等进度。请求层继续把无 HTTP 响应识别为网络错误，并保留业务错误的 `code/details/request_id`：URL 不安全或不可读时提示更换公开页面；`URL_REQUIRES_RESEARCH` 说明当前服务暂不支持网页学习并保留输入；歧义时展示候选解释；资料不足时提示更具体的领域；Agent、校验或 Tavily 故障提供保留原输入的重试入口。

只有当前失败响应明确含 `fallback.available=true` 和有效许可时才展示基础知识操作，不能用错误码、本地关键词名单或字符串匹配自行推断许可。用户主动选择后携带原输入与许可发起独立请求；不预请求、不自动重试成 basic。输入变化、重试联网、切换账号或离开该失败流程时清除待用许可，异步旧响应不能为已改动输入恢复入口。许可只留在当前页面内存，不写本地持久存储、不进入 URL、埋点或错误日志；无 HTTP 响应时不得沿用上一次许可作为本次授权。

通关页只在 `sources` 非空时于现有总结下增加参考资料区，展示检索日期、标题、域名和获取方式；legacy 与旧游戏不展示联网标识或空资料容器。微信小程序端使用 `Taro.setClipboardData` 复制经过后端规范化的公开 HTTP(S) 来源链接；H5 端才使用浏览器直接打开。Taro 官方 `WebView` 对其他网页要求在小程序后台配置业务域名，搜索来源不可预知，因此不把任意来源交给 `WebView`。

常规和基础知识创建请求显式使用 `Taro.request` 的 `timeout: 90000`，单位为毫秒，不依赖默认值；业务错误不能被超时封装器改写为笼统“网络问题”。该值不能保证断网时也收到业务响应，也不能掩盖内容安全或代理耗时，需在开发/部署验收检查整条请求链。依据：[Taro.request 官方参数](https://docs.taro.zone/docs/apis/network/request/)。

**备选方案：** 将来源统一放入 `WebView` 会因业务域名校验在真机失败；由后端代理网页会扩大 SSRF、内容合规和版权风险。因此采用复制链接降级。

### 9. 密钥通过后端环境注入并按策略启动校验

根目录 `.env` 用于本机开发，`backend/.env.production` 用于服务器部署，两者均已在 `.gitignore` 中；`.env.example` 只加入空的 `TAVILY_API_KEY=` 占位。Docker Compose 通过 `env_file` 将生产值注入 API 进程，符合官方集成读取 `TAVILY_API_KEY` 环境变量的方式。

`Settings` 将生成模式、Tavily 与 DeepSeek 凭证建模为严格枚举和 `SecretStr`。真实 grounded 模式缺少任一凭证都会阻止启动，并验证研究模型 Tool Calls 与结构化输出能力；真实 legacy 模式只校验原 DeepSeek 生成所需配置，不读取 Tavily 凭证、不导入研究模块也不执行 Tool Calls 能力检查。mock 模式仍允许 fake 替换外部服务。grounded 每次工具调用由适配器构造官方 `TavilySearch` 或 `TavilyExtract` 实例；密钥不会传入前端、异常详情、Agent 输出或对象日志。

已通过普通协作文本出现的凭证必须完成轮换并使旧值失效；后续使用已确认的新值，只做不输出内容的配置与权限核查，不因修订设计重复改动密钥。仓库、OpenSpec 文档、测试夹具和部署产物只出现环境变量名。基础知识许可使用与登录 token 隔离用途的签名校验，不向模型或 Tavily 发送许可、登录 token 或用户标识。

**备选方案：** 把 key 写入前端或代码常量会直接泄露；运行时临时修改全局环境也不利于测试隔离。采用进程启动前环境注入。

### 10. 单一截止时间为整理、生成和校验保留预算

内容安全通过后记录单调时钟起点 `t0`，由外层 grounded 流水线创建 `deadline=t0+total_timeout`。研究、整理、生成、事实校验及全部重试共享这一截止时间；预算不再只包住 `ResearchAgent.research()`。使用 Python 3.11 的 `asyncio.timeout_at` 管理绝对截止时间，各子调用只能缩短本次等待，不能重新获得完整 85 秒。依据：[Python asyncio 截止时间](https://docs.python.org/3.11/library/asyncio-task.html#asyncio.timeout_at)。

默认分配如下，均为服务端配置且启动时校验相互关系。保留现有 `RESEARCH_TOTAL_TIMEOUT_SECONDS` 作为外层总预算，新增 `RESEARCH_GENERATION_RESERVE_SECONDS`、`RESEARCH_FINALIZATION_RESERVE_SECONDS` 和 `GROUNDING_VALIDATION_RESERVE_SECONDS` 表达三类预留；不是为每个阶段另开完整超时。缩短总预算时必须同时满足预留关系，否则拒绝启动。

| 边界 | 默认值与约束 | 到达边界的动作 |
| --- | --- | --- |
| 总生成流水线 | 85 秒，允许降低但不能提高上限 | 取消后续工作，拒绝未完成/未校验草稿 |
| 生成及校验预留 | 40 秒，必须为正且小于总预算 | 研究最晚在 `deadline-40s`（默认 `t0+45s`）结束 |
| 研究整理预留 | 15 秒，必须小于研究阶段预算 | 停止新增检索的截止点默认 `t0+30s`，剩余研究时间只做结论与一次必要纠错 |
| 必需事实校验预留 | 15 秒，必须小于生成及校验预留 | 每次生成/重生成都必须在总截止前为其后校验留下此窗口，否则不启动 |
| 研究调用 | 工具最多 4 次（Search 2 / Extract 2），模型最多 6 次 | 探索最多使用前 4 次模型调用，为结论和一次必要纠错保留最后 2 次 |

研究提前完成时，未用时间可供生成与校验使用；整理也可提前开始，不必等待计时点。未取得必需联网资料时仍只能在剩余允许检索窗口内纠正，不能占用后续阶段预留。最终校验及其网络重试只能在总截止内执行；一次反馈重生成与研究的一次格式纠错是两种不同额度，都计入同一个总时间预算。预留时间不是供应商成功 SLA：不能及时完成时明确失败，不跳过校验。

工具次数计算为已准入的逻辑调用，失败尝试也占该次数；工具内部唯一一次网络重试另外记录物理请求次数并计入时间。同轮工具必须先原子预占额度。被禁止或超限而未执行的意图只记录 `blocked`，不记作新证据。研究模型计数包括整理、格式纠错和实际网络重试；关闭研究 SDK 隐式重试，任何显式瞬时重试必须扣除同一六次额度，不得占用最后的必要整理额度。

单次 Search 最多返回 8 条摘要，全文模式最多保留 3 条 Markdown 正文；单次 Extract 最多处理 3 个 URL。直接 URL 输入的第一次 Extract 只处理该 URL，不能用搜索结果替换用户指定页面。

请求级正文处理预算为单页 120,000 字符，单次传给模型的工具上下文最多 40,000 字符。预算内的完整正文按标题/段落建立章节索引并选择完整相关块，不能静默截断为页面开头；如果 Tavily 返回的页面正文超过处理预算，系统失败关闭为 `PAGE_UNREADABLE` 并在安全 details 中标记页面过大，而不是以不完整页面出题。完整原文在请求结束后释放且不落库。

Search 单次超时上限 8 秒，Extract basic 12 秒、advanced 25 秒，实际超时取配置上限与当前检索窗口余额的较小值；进入整理阶段不再启动外部检索。单次工具的瞬时网络故障最多重试一次，短退避也计入同一窗口；认证、限流、参数和响应结构错误不循环重试。若是外层检索截止触发取消，保存先前成功证据并转入整理；若是工具本身的请求失败，则在有限重试后保持 `SEARCH_UNAVAILABLE` 等原错误，不假装该工具成功。

SDK 内置重试与应用重试不能叠加。grounded 生成/校验客户端应显式关闭隐藏网络重试，由流水线在剩余预算内管理；不修改 legacy 共享客户端的运行时配置。独立 basic 请求复用原生成方法，由它自己的最外层 85 秒上限约束所有原有生成重试，不执行事实联网校验，不改变全局 legacy 行为。

时间到期或收到取消时取消并等待本请求的工具/模型任务退出，不使用后台任务或 `shield` 继续生成；正文清理放在 `finally`。HTTP 入口须显式处理客户端断连，不能假设网络断开会自动取消所有业务协程。外部供应商可能已受理的请求无法保证不计费，但本服务收到取消后不得继续生成或提交新游戏。数据库事务仅在完整结果就绪后开始；内容安全检查和数据库/HTTP 开销并不包含在规格规定的 85 秒 AI 预算内，因此开发与生产还需分别核查这些开销及反向代理超时，不能把 85/90 秒差额宣传为绝对完成保证。

**备选方案：** 每个阶段分别设置 85 秒会让总时长叠加；只限制工具次数不能防止耗时耗尽；仅靠提示词“尽快结束”无法保证预留。因此采用绝对截止时间、阶段预留、真实调用计数和强制整理，默认时间分配通过受控 smoke test 验证后可在硬约束内调小或调整比例。

### 11. 保守主题准入与有绑定关系的独立基础知识请求

准入策略采用版本化的服务端稳定主题目录与明确别名，不采用模型输出的 `is_familiar` 或搜索失败状态作为许可依据。目录条目明确主题、别名及仅限基础知识的范围；首个回归条目为“高情商聊天”。规范化仅复用常规输入的既有规则（例如去首尾空格），整个输入必须命中已审核条目；不能截出已知子串、删除版本/日期词或通过模糊匹配扩大范围。未覆盖的普通主题也暂不授予许可，继续走联网或提示修改输入，后续经人工审核可增补目录，不由 Agent 自动扩表。

先排除网址/包含网址的输入、新技术、版本用法、强时效及不能确认类别的主题，再检查目录。即使命中基础词，只要完整输入携带最新/版本/日期等要求，或本次资料已显示未解歧义、实质冲突，也不能宣称其已被可靠确认。该目录只控制兜底，不影响常规 grounded 的任意合法关键词与 URL 输入。

只有内容安全通过、实际 grounded 流水线已终止为可识别失败且没有保存游戏时才考虑签发许可。可适用的失败包括研究服务不可用、研究编排/预算/结构失败、非冲突性的资料不足、生成服务或事实校验失败；输入校验、内容安全、认证、未解歧义、取消、持久化失败及未知内部错误不签发。错误类别不改变主题准入结论，Tavily 故障本身不能把任何主题“变成”基础知识。

许可采用短期签名 token，默认有效期 5 分钟，使用现有 PyJWT 的 HS256 验签、必填 claim 及专用 audience 校验。签名密钥与用户/主题绑定 MAC 从现有后端强 JWT secret 按不同用途标签派生，不能把登录 token 当许可，也不能把许可当登录 token；不新增需要手工分发的供应商凭证。绑定数据包含随机许可 ID、原失败 `request_id`、当前用户的不可读绑定值、原规范化主题的带密钥摘要、原失败类别、准入策略版本、签发/过期时间与专用 token 类型。token 不包含完整主题、OpenID、研究正文或 Agent 消息，完整 token 本身也属于日志必须剔除的凭据。依据：[PyJWT 官方使用说明](https://pyjwt.readthedocs.io/en/stable/usage.html)。

签名由已失败请求的服务端代码签发，即为失败关联证明，不依赖客户端自行传来的请求 ID，也无需新增失败研究内容表。策略版本变更、密钥轮换或切换 legacy 后旧许可可失效，用户需重新联网取得新的许可。

接口契约：

| 位置 | 字段/行为 |
| --- | --- |
| 原失败响应 | 保留原 HTTP 状态、`error.code/message` 与安全 details；增加 `details.request_id/reason` |
| 获准时 | `details.fallback={available:true, token, expires_at, mode:"basic", notice:"未经联网核验"}` |
| 未获准时 | `details.fallback={available:false}`，没有 token；旧服务未返回该字段也视为不可用 |
| 独立入口 | `POST /api/v1/games/basic`，使用现有登录认证，严格拒绝额外字段 |
| 请求体 | `topic`（原关键词）、`fallback_token`、`acknowledge_unverified`（必须为布尔值 `true`） |
| 成功响应 | 复用 `GameOut`；`generation_mode=basic`、固定未核验提示、空来源、空检索时间 |
| 准入拒绝 | `BASIC_MODE_NOT_ALLOWED`（403），安全 reason 区分许可无效/过期/准入不满足，不返回原主题或他人信息 |

服务端处理顺序为：认证 → 严格 Schema/关键词长度与 URL 拒绝 → 验签、时效、用途、原失败关联、当前用户与原主题绑定 → 按当前策略重新准入 → 再次微信内容安全 → 调用原关键词生成器 → 三关三选一完整性校验 → 单事务持久化并返回 basic 标识。再次内容安全失败或不可用时沿用原错误，零生成、零写入。许可和告知字段只用于服务端授权，不进入出题 prompt。

前端重放已成功的同一许可按第 7 节返回已有游戏，不重新调用生成器；未成功请求在有效期内可由用户主动重试，但不自动执行。原失败请求保持失败记录，后续 basic 有新的 `request_id`，日志以 `parent_request_id` 关联；basic 自身失败不再签发递归兜底许可。

**备选方案：** 全面依赖 LLM 分类会重现对新术语的自信误判；仅传 `allow_fallback=true` 或原请求 ID 无法证明授权；保存失败全文增加隐私和清理负担。采用保守目录、短期签名许可、用户/主题绑定及成功记录唯一约束，代价是未审核主题不能立刻兜底。

### 12. 分层保留错误并进行最小化诊断

工具适配层把外部异常转为类型化领域错误；Agent 中间件和整理器必须透传这些错误，不能捕获所有 `Exception` 后统一改成 `RESEARCH_AGENT_FAILED`，也不能把供应商异常当结构错误重启研究。未知异常仅在其所属边界映射为安全内部原因，使用类型/状态分类而非匹配异常中文字符串；取消单独传播。错误详情、日志和异常链输出均不得直接包含 `str(provider_exception)` 或原始响应。

2026-08-31 已获用户确认的唯一兼容例外：当前官方 `langchain-tavily` 0.2.18 把 HTTP 错误转成无状态属性的普通异常。仅在官方 Tavily 调用适配边界，允许严格识别其固定格式 `Error <三位 HTTP 状态码>: <reason>` 并提取数字状态码，立即转换为类型化领域错误；自由描述部分不参与分类、不外泄。结构化 HTTP 状态优先，未知格式或未知状态失败关闭，不以子串、自然语言或任意数字猜测认证/限流/重试原因。此例外不扩展到 Agent、生成服务、API 或前端。保留官方 Search/Extract 类和网络实现，以真实官方工具加受控 HTTP fake 覆盖状态与格式契约；升级依赖时复核，不修改供应商代码或静默换模型。

| 所属边界 | 兼容的 HTTP / code | 安全 reason 示例 |
| --- | --- | --- |
| Tavily 服务 | 503 / `SEARCH_UNAVAILABLE` | `PROVIDER_AUTH_FAILED`、`PROVIDER_RATE_LIMITED`、`PROVIDER_NETWORK_ERROR`、`PROVIDER_TIMEOUT`、`PROVIDER_UNAVAILABLE`、`PROVIDER_INVALID_RESPONSE` |
| 网页正文 | 422 / `PAGE_UNREADABLE` | `PAGE_EMPTY`、`PAGE_UNSUPPORTED`、`PAGE_TOO_LARGE`、`PAGE_EXTRACTION_FAILED` |
| Agent/研究整理 | 502 / `RESEARCH_AGENT_FAILED` | `TOOL_BUDGET_EXHAUSTED`、`MODEL_BUDGET_EXHAUSTED`、`RESEARCH_TIMEOUT`、`INVALID_RESEARCH_OUTPUT`、`REQUIRED_TOOL_MISSING`、`RESEARCH_MODEL_UNAVAILABLE` |
| 证据验收 | 422 / `SOURCES_INSUFFICIENT` 或 `TOPIC_AMBIGUOUS` | `INSUFFICIENT_EVIDENCE`、`CONFLICTING_EVIDENCE`、`AMBIGUOUS_TOPIC` |
| 出题/校验服务 | 502 / `AI_GENERATION_FAILED` | `GENERATION_TIMEOUT`、`VALIDATION_TIMEOUT`、`GENERATION_UNAVAILABLE`、`INVALID_GENERATED_OUTPUT` |
| 事实不受证据支持 | 502 / `GROUNDING_VALIDATION_FAILED` | `UNSUPPORTED_FACTS` |

模型提出一次被拦截的超限工具调用不等于立即报预算错误；只有整理后仍无法形成合格结果时才按真正终止原因分类。若最终结论明确为资料不足，保留 `SOURCES_INSUFFICIENT`；若没有合法研究结论，则区分超时、调用上限或结构错误。事实报告明确不通过和校验服务本身不可用也要区分，后者不能伪装为已经判定事实错误。

`request_id` 由服务端生成随机不含身份/内容的标识，错误响应与日志使用同一个值，不接受任意客户端字符串替代权威关联。记录模式、阶段、耗时、工具名称、参数类别、结果/正文字符/来源数量、模型及工具计数、物理重试次数、安全 reason、校验问题数量、准入结果和可取得的用量。日志不记录用户 ID、OpenID、JWT、完整关键词及其易枚举普通哈希、查询语句、完整 URL、许可、正文、消息历史或供应商响应；关联仅用随机 request ID。原失败与 basic 之间另记 `parent_request_id`。

默认禁用模型/工具原始载荷追踪，不直接使用官方示例中的消息打印或 LangSmith 全量追踪。服务端异常日志、访问日志、客户端埋点也要经过同一敏感字段检查，不能只让业务 logger 脱敏。指标使用低基数模式/阶段/原因维度，至少覆盖成功率、P50/P95 延迟、错误比例、工具/模型调用次数、受控兜底获准与完成比例；request ID、主题和用户值不作为指标标签。

**备选方案：** 统一“网络问题”无法定位预算和 Schema 故障；输出原始异常虽便于排查，却可能泄露密钥和正文。采用稳定业务码、细分安全 reason、随机请求关联和敏感数据否定测试。

## Risks / Trade-offs

- [legacy/basic 不能解决知识时效性与事实依据问题] → legacy 仅由部署显式启用；basic 仅接受获准用户的独立主动请求，禁止网址/新技术/版本/未知主题，并持久显示未经联网核验，不能冒充等价质量路径。
- [保守目录会拒绝部分实际属于常识的输入] → 这是防止模型误判新概念的可用性取舍；先覆盖“高情商聊天”回归主题，明确未知不开放，增加目录条目必须人工审核，不能用提高模型置信度代替。
- [短期许可可能过期、被篡改或跨账号重用] → 专用签名用途、过期时间、用户/原主题绑定及当前策略再验证；前端保留输入并提示重新联网，日志不记录 token。
- [重复点击或重试可能重复创建 basic 游戏] → 前端提交期间禁用重复操作，数据库以随机许可 ID 唯一约束保证最多一局；不宣称跨进程恰好一次模型调用。
- [可选研究依赖可能因入口文件的顶层 import 破坏 legacy 最小安装] → 依赖方向由策略协议指向实现，应用工厂只在 grounded 分支延迟导入研究包，并以“不安装 research extra 仍可启动和创建关键词游戏”的测试作为门禁。
- [同一数据库混合 grounded、legacy、basic 和历史记录] → 持久化模式与核验提示，结合检索时间和来源校验不变量；使用新迁移兼容旧数据，读取不重新推断模式或补造来源。
- [Tavily 返回相关内容不等于事实必然正确] → 一手来源优先、来源独立性检查、逐关来源关联和生成后校验共同降低风险；证据不足时失败关闭。
- [URL 模式可能只有用户指定的单一来源] → 产品明确标记“基于该页面生成”，事实校验只判断与页面一致性；如果 Agent 搜索补充来源，则同时展示，不能悄悄替换原页面。
- [Agent 的工具选择存在不确定性] → 强制输入模式最低工具要求，台账保存真实资料，动态筛选工具并预留结论/纠错额度；用真实 `create_agent` 接可脚本化模型 fake 验证中间件，不能只用返回预制字典的 Agent fake 验证收敛。
- [SDK 或 ToolStrategy 内置重试悄悄扩大调用次数] → 显式关闭/限制自动重试，纠错与后置验收共用一次额度，物理请求和模型计数都要测试，最终仍由绝对截止时间约束。
- [官方工具把部分参数固定在实例上，适配器可能随包升级失效] → 只封装实例创建和结果规范化，锁定依赖版本，并用契约测试覆盖 Search/Extract 的输入 Schema 与官方返回结构。
- [整页正文可能超过模型上下文或包含提示注入] → 请求内临时保存、结构化分块、字符预算、外部内容边界和注入回归测试；不把网页命令当作指令。
- [国家和语言只是检索排序增强，可能漏掉重要跨语言来源] → 默认不严格过滤语言；城市进入查询，国家只在明确地域主题上启用，并允许 Agent 补充英文或本地语言查询。
- [`advanced`、全文搜索和二次抽取会增加配额成本] → 禁用自动参数、限制全文条数与总工具调用，记录每局调用及用量；不以牺牲正确性为代价回退模型记忆。
- [85 秒同步预算仍可能失败，90 秒客户端超时还包含安全检查及网络开销] → 研究/整理/校验明确预留、有限重试、准确加载与错误文案，测量完整请求；预算不足时拒绝草稿，不通过延长前端等待掩盖后端问题，也不伪造阶段进度。
- [DeepSeek 同时参与研究、生成和事实校验，可能出现一致性偏差] → 每阶段独立严格 Schema、确定性前置/后置校验和已知误判回归测试；后续可替换验证模型而不改 API。
- [JSON 字段不利于未来跨游戏来源分析] → 首版优先兼容与交付速度；保留稳定来源 ID，后续可迁移到关系表。
- [微信端只能复制任意外部链接，体验弱于直接打开] → 明确复制成功反馈，H5 直接打开；只有来源域名稳定后才评估业务域名白名单。
- [旧游戏没有来源] → API 对旧记录返回空数组和空检索时间，仅对新建 grounded 游戏执行来源强约束，basic 不因缺来源被误判成异常联网结果。
- [密钥曾在非密钥管理通道出现] → 核实已轮换且旧 key 作废；仓库和产物始终只出现变量名，不在验收或日志中输出配置值。

## Migration Plan

本节是后续实施和发布顺序，不授权在规划修订中修改代码、环境、数据库或生产部署。现有任务勾选表示此前进展，不证明新增设计已实现；待任务清单单独确认后，用新增回归任务追踪本次增量。

1. 核对已确认提案/规格与本设计，下一步单独修订并确认 `tasks.md`。保留已有实现与测试证据，新增针对收敛、状态复用、总预算、错误保真、准入、许可和模式持久化的 TDD 任务；不能因为旧测试通过就把新行为标为完成。
2. 保留开发/生产环境隔离，用不输出值的方式核查轮换后的后端凭证。记录依赖解析版本并复核官方接口；分别验证无 research extra 的 legacy 安装及 grounded 完整安装。真实模型能力验证仅在受控开发 smoke test/发布检查中进行。
3. 先写能够复现“两次 Search + 一次 Extract 后再次要求 Search”的失败测试，再实现同请求证据台账、动态工具筛选和 `ResearchConclusion`。验证已有合格资料可直接收敛、格式纠错不重搜、零工具纠正不放宽首次联网要求、最多一次纠正且来源不能伪造。至少一组测试使用真实 `create_agent` 和 fake 模型/工具覆盖官方中间件与结构化输出路径。
4. 先写 fake 时钟/取消及故障注入失败测试，再实现绝对截止时间、生成/整理/校验预留和类型化错误透传。覆盖研究超时、隐藏重试、模型上限、网页不可读、Tavily 认证/限流/网络故障、无效结构、事实校验失败、客户端断连，断言错误分类稳定、未校验草稿不保存、grounded 内零旧生成器调用。
5. 先为稳定主题目录、失败许可签发/验证、用户/主题绑定、过期/伪造/跨账号/换主题、拒绝网址与新技术/版本/未知输入、再次内容安全、basic 独立预算及结构完整性写失败测试，再实现独立入口及统一结果。旧常规请求不能通过额外字段走 basic；basic 不调用 Tavily/Agent、不改变全局模式。
6. 新增结果模式与许可唯一 ID 的增量迁移，并通过 SQLite 单元测试和 MySQL 8 集成测试验证旧记录回填、grounded/basic/legacy 读取一致性、并发重放、事务失败和取消无半成品。迁移升降级往返测试只在可丢弃测试库进行，生产采用兼容扩展迁移，不做破坏性降级。
7. 在已有设计规范内补齐第 8 节新增失败与基础知识状态原型，展示给用户并取得明确确认，再实现前端类型、许可生命周期、独立请求及持久提示。验证新旧业务错误不会变成泛化网络错误；未获许可/无响应不展示入口，基础知识游戏重进仍保留未核验标识。完成 H5 与微信小程序构建及真机/开发者工具验收。
8. 日志与指标按 TDD 验证敏感数据缺失、错误可关联及请求正文释放；执行全量后端测试与项目既有 85% 分支覆盖率门槛，前端测试、类型检查、lint 和双端构建。自动化测试隔离 Tavily、DeepSeek、DNS 与时间，不消耗真实配额。
9. 使用开发凭证做独立的受控真实回归：“高情商聊天”首先完整走 grounded，核查来源与三关校验；注入研究故障后确认只有用户主动选择才生成 basic。另覆盖 `Harness Engineering`、简单摘要、复杂全文、公开页面、中国城市和国际技术主题；新知识与 URL 故障不得获准 basic。分别验证 legacy 无研究导入/调用与拒绝 URL，测试后恢复原开发配置。记录实际耗时与安全轨迹，不凭 fake 通过宣称真实故障已修复。
10. 检查 diff/构建产物无密钥、正文和身份数据，运行 OpenSpec 严格校验。完成实施验收后再同步主规格、归档；生产发布需要用户单独授权，并明确开发与生产各自版本、配置和验证结果。

授权发布后先做数据库备份与兼容迁移，再部署能读取三种结果模式的后端，检查健康、错误类别、调用次数和端到端延迟；最后发布已确认原型对应的小程序版本。旧客户端不理解 `fallback` 时忽略新增字段，因此不会主动创建 basic；正常关键词请求保持兼容。

首选运维降级仍是在保留兼容迁移和当前应用版本的前提下，把 `QUESTION_GENERATION_MODE` 改为 `legacy` 并重启或重新部署；这会恢复原关键词生成，URL 返回 `URL_REQUIRES_RESEARCH`，基础知识许可入口停用，历史 grounded/basic/legacy 游戏仍按原标识读取与答题。单个失败或用户主动兜底不触发全局切换。恢复时重新设为 `grounded` 并通过能力/健康检查。

如需回滚应用镜像，必须保留能识别 `generation_mode=basic` 与核验提示的读取能力，不能直接回滚到会隐藏既有 basic 告知的旧版本；优先回滚生成模块或使用同版本 legacy 配置。新增数据库列保留，避免破坏性数据库降级。没有通过端到端回归或 UI 原型门禁时不发布。
