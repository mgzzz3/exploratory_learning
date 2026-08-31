# grounded-game-generation Specification
## Purpose

以可剥离的生成策略提供两种服务形态：默认的 grounded 策略让关键词或公开网页先通过 Tavily 取得当前、可追溯且与输入一致的资料后再出题，并在资料不足时停止猜测；显式 legacy 策略保留原线上关键词直出题能力，供部署级降级使用且不会伪装成联网结果。

## Requirements

### Requirement: 通过部署配置选择可剥离生成策略
系统 SHALL 通过仅由后端运行环境控制的 `QUESTION_GENERATION_MODE=grounded|legacy` 选择生成策略，默认值为 `grounded`。grounded 策略 SHALL 装配研究 Agent、Tavily 工具、证据验收和事实校验；legacy 策略 SHALL 只装配原 `ContentGenerator.generate(topic)`，并且不得初始化或调用 Tavily、LangChain 研究 Agent或联网事实校验。客户端 MUST NOT 在单个请求中指定或覆盖该模式。

#### Scenario: grounded 模式启动
- **WHEN** 服务以 `QUESTION_GENERATION_MODE=grounded` 启动
- **THEN** 系统要求有效的 Tavily/DeepSeek 配置和支持 Tool Calls 的研究模型，并对创建请求执行本规格定义的联网研究流水线

#### Scenario: legacy 模式启动
- **WHEN** 服务以 `QUESTION_GENERATION_MODE=legacy` 启动
- **THEN** 系统即使没有 Tavily key 或研究模型 Tool Calls 能力也能启动，且创建关键词游戏只调用原有内容安全检查和 `ContentGenerator.generate(topic)`

#### Scenario: 请求不能覆盖服务器策略
- **WHEN** 客户端在创建游戏请求中尝试提交生成模式或绕过联网的参数
- **THEN** 系统按严格请求 Schema 拒绝额外字段，并继续以服务器部署配置为唯一策略来源

#### Scenario: 运维显式降级
- **WHEN** 运维把环境配置从 `grounded` 改为 `legacy` 并重启或重新部署服务
- **THEN** 新创建的关键词游戏走原线上生成逻辑，历史游戏读取和答题继续可用，且不要求回滚兼容性数据库迁移

#### Scenario: 恢复 grounded 模式
- **WHEN** 运维把环境配置恢复为 `grounded` 并重新部署且启动检查通过
- **THEN** 新创建请求重新启用 URL、联网来源和事实校验能力，不受 legacy 期间创建的无来源游戏影响

### Requirement: 兼容关键词和网页输入
在 grounded 模式下，系统 SHALL 通过现有创建游戏入口同时接受知识关键词和单个公开网页 URL。系统 MUST 将完整输入可解析为单个公开 HTTP(S) URL 的请求识别为 URL 模式，其余输入识别为关键词模式；关键词最长 80 个字符，URL 最长 2048 个字符。legacy 模式 SHALL 只接受原有 80 字以内关键词。

#### Scenario: 用户输入知识关键词
- **WHEN** 用户提交“Harness Engineering”等非 URL 文本且内容安全检查通过
- **THEN** 系统将请求识别为关键词模式，并保留原始术语用于联网研究和主题消歧

#### Scenario: 用户输入公开网页
- **WHEN** grounded 模式下用户提交一个有效、无需登录且可公开访问的 HTTP(S) URL
- **THEN** 系统将请求识别为 URL 模式，并把该页面作为本局主要学习材料

#### Scenario: URL 超过长度限制
- **WHEN** 用户提交超过 2048 个字符的 URL
- **THEN** 系统返回 HTTP 422 和可操作的输入过长提示，且不调用 Tavily 或 DeepSeek

#### Scenario: legacy 模式拒绝 URL
- **WHEN** 服务处于 legacy 模式且用户提交任意 HTTP(S) URL
- **THEN** 系统返回 HTTP 422、错误码 `URL_REQUIRES_RESEARCH`，保留原输入供修改，且不把 URL 字符串交给旧内容生成器猜测页面内容

### Requirement: 拒绝不安全或不受支持的 URL
grounded 策略 SHALL 在调用任何外部工具前校验 URL。系统 MUST 拒绝非 HTTP(S) 协议、包含用户凭证、指向本机/私网/链路本地地址、无法确定公开目标或需要登录凭证的 URL，并且 MUST NOT 尝试提取被拒绝的地址。

#### Scenario: 用户提交私网地址
- **WHEN** 用户提交 `http://127.0.0.1`、`http://localhost` 或其他私网/链路本地目标
- **THEN** 系统返回 HTTP 422、错误码 `INVALID_SOURCE_URL`，且 Tavily Extract 未被调用

#### Scenario: 用户提交非网页协议
- **WHEN** 用户提交 `file:`、`ftp:`、`javascript:` 或其他非 HTTP(S) 地址
- **THEN** 系统返回 HTTP 422、错误码 `INVALID_SOURCE_URL`，且不把该地址发送给任何外部服务

### Requirement: 出题前强制联网研究
当 `QUESTION_GENERATION_MODE=grounded` 时，系统 SHALL 在任何学习输入进入 AI 出题前，让研究 Agent 至少成功调用一次 Tavily Search 或 Tavily Extract；系统 MUST NOT 因模型自认为熟悉主题而绕过联网工具。关键词模式 MUST 至少调用一次搜索工具，URL 模式 MUST 至少提取一次用户提供的原始页面。

#### Scenario: 常见主题仍执行搜索
- **WHEN** 用户提交“Python 基础”等常见关键词且内容安全检查通过
- **THEN** 研究 Agent 至少调用一次 Tavily Search，并且只在取得合格资料后进入 AI 出题

#### Scenario: 新概念执行搜索
- **WHEN** 用户提交“Harness Engineering”等训练数据可能未覆盖的新概念
- **THEN** 研究 Agent 使用包含用户原始术语的查询检索当前资料，而不是根据旧有相近语义直接出题

#### Scenario: URL 模式执行页面提取
- **WHEN** 用户提交一个通过安全校验的公开网页 URL
- **THEN** 研究 Agent 至少调用一次 Tavily Extract 提取该确切 URL，且不得用相似页面的搜索摘要替代用户指定页面

#### Scenario: 违规输入不发送给研究工具
- **WHEN** 用户输入未通过微信内容安全检查
- **THEN** 系统维持现有内容拦截响应，并且 MUST NOT 将输入发送给 Tavily 或 DeepSeek

#### Scenario: Agent 未使用工具
- **WHEN** 研究 Agent 在限定步骤内尝试直接输出结论而没有成功调用任何联网工具
- **THEN** 系统拒绝该结果并进行一次受控纠正；仍未使用工具时返回 HTTP 502、错误码 `RESEARCH_AGENT_FAILED`，且不创建游戏

### Requirement: AI 自主编排 Search 和 Extract
grounded 策略 SHALL 同时向研究 Agent 提供关键词搜索和网页提取能力，由 Agent 根据原始输入、工具返回结果和证据缺口自主选择下一次调用。系统 MUST 允许 Agent 先搜索后提取关键页面、先提取用户页面后补充搜索，或在资料已经充分时停止继续调用；系统必须通过确定性限制约束允许的工具、参数和总调用预算。

#### Scenario: 搜索摘要已经足够
- **WHEN** 简单关键词的搜索摘要已经足以支持三个准确且递进的知识点
- **THEN** Agent 可以停止调用 Extract，并进入证据评估

#### Scenario: 搜索摘要不足
- **WHEN** 搜索结果与主题相关但摘要不足以支持正确答案或解释
- **THEN** Agent 调用 Tavily Extract 获取一个或多个关键结果页面的正文后再评估证据

#### Scenario: 指定页面需要外部补充
- **WHEN** 用户页面依赖未解释的外部概念、内容明显过时或存在影响正确答案的事实缺口
- **THEN** Agent 在完成页面提取后可以调用 Tavily Search 补充或核验资料

#### Scenario: Agent 超出工具预算
- **WHEN** Agent 达到配置的总工具调用次数或研究总时限后仍无法形成合格证据
- **THEN** 系统终止 Agent 循环并返回稳定的研究失败响应，不继续产生无界调用或退回模型记忆

### Requirement: 动态选择检索与提取参数
grounded 策略 SHALL 允许研究 Agent 在服务端安全边界内根据知识复杂度、时效性、地域、语言和证据缺口动态选择搜索深度、摘要或正文模式、结果数量、类别、日期范围、国家、语言、域名以及网页提取深度。参数选择 MUST 受允许值、结果上限、正文上限和成本预算校验。

#### Scenario: 简单知识使用摘要检索
- **WHEN** 输入是定义明确且不依赖大量上下文的简单知识
- **THEN** Agent 使用较低延迟的搜索深度、较少结果和不包含整页正文的结果摘要完成首轮检索

#### Scenario: 复杂或新知识使用深度检索
- **WHEN** 输入是新知识、专业知识、多义术语或需要多步理解的复杂概念
- **THEN** Agent 可以选择 advanced 搜索、增加受限结果数量并请求 Markdown 正文，且系统仍对返回正文执行上下文大小控制

#### Scenario: 新闻和强时效知识限制时间
- **WHEN** 主题明确要求最近新闻、当前事件或指定日期范围
- **THEN** Agent 动态选择合适的搜索类别和 `time_range` 或起止日期，避免以过期资料支持当前结论

#### Scenario: 中国地域内容提升本地结果
- **WHEN** 输入明确涉及中国的法规、生活服务、城市信息或本地语境
- **THEN** Agent 可以使用中文查询、`country=china` 和 `language=zh-cn` 提升相关来源，但不得把地域偏好当作绝对事实过滤

#### Scenario: 城市范围写入查询
- **WHEN** 输入明确涉及杭州、上海或其他具体城市
- **THEN** Agent 将城市名称保留在查询语句中，并只在可用时通过所属国家参数增强结果，不使用 Tavily 不存在的城市参数

#### Scenario: 国际技术知识覆盖多语言来源
- **WHEN** 输入是全球技术概念且高质量一手资料主要使用英文
- **THEN** Agent 不强制限制国家，可以使用英文查询或补充英文搜索，同时保留与用户语言一致的最终教学内容

### Requirement: URL 模式提取完整页面
grounded 策略 SHALL 使用 Tavily Extract 获取用户指定页面的完整可读正文。为取得整页内容，初次提取 MUST 不使用相关性 `query` 截断；系统可以在完整内容取得后于服务端分块、压缩或选择相关段落，但 MUST 保留足以覆盖页面核心结构和三个教学知识点的内容。

#### Scenario: 普通文章页面
- **WHEN** 用户提供结构简单的公开文章 URL
- **THEN** Agent 可以使用 basic 提取获得整页正文，并以页面标题和 URL 建立来源记录

#### Scenario: 包含表格或嵌入内容的复杂页面
- **WHEN** 页面包含影响理解的表格、嵌入内容或 basic 提取结果明显不完整
- **THEN** Agent 使用 advanced 提取重新获取更完整内容，并在限定正文预算内继续研究

#### Scenario: 页面无法读取
- **WHEN** 页面因登录墙、付费墙、站点拒绝、空正文、不受支持格式或持续提取失败而无法获得足够内容
- **THEN** 系统返回 HTTP 422、错误码 `PAGE_UNREADABLE`，保留原 URL 供用户修改或重试，且不根据 URL 标题或模型记忆猜测出题

#### Scenario: 页面超过正文处理预算
- **WHEN** Tavily 已返回页面正文，但完整正文超过服务端允许的单页处理预算
- **THEN** 系统返回 HTTP 422、错误码 `PAGE_UNREADABLE` 和不含正文的页面过大原因，且不得静默截取页面开头后继续出题

### Requirement: 主题语义消歧
grounded 策略 SHALL 基于 Agent 取得的搜索和提取结果确定本局采用的主题解释，并保留用户原始输入；当多个解释均有充分证据且无法可靠选定时，系统 MUST 要求用户补充说明而不是任意选择。

#### Scenario: 新术语被解释为正确领域
- **WHEN** “Harness Engineering”的高相关检索结果指向 AI agent 环境、约束和反馈回路工程
- **THEN** 系统采用该解释生成课程，并且 MUST NOT 将其解释为同名公司的软件交付产品或其他无关领域

#### Scenario: 无法自动消除歧义
- **WHEN** 检索结果支持两个或更多明显不同的主题解释且没有可靠依据选择其中一个
- **THEN** 系统返回 HTTP 422、错误码 `TOPIC_AMBIGUOUS` 和不超过三个简短候选解释，且不创建游戏

### Requirement: 构建与输入模式匹配的合格证据集
grounded 策略 SHALL 按主题相关性、来源权威性、内容时效性和来源独立性筛选最终证据。关键词模式 SHALL 保存 2～5 条去重来源；URL 模式 SHALL 保存用户页面并可追加至多四条补充来源，即共 1～5 条。存在第一方发布、官方文档、原始论文或标准时，系统 MUST 优先采用这些来源；无合格证据集时 MUST NOT 出题。

#### Scenario: 关键词模式优先采用一手来源
- **WHEN** 检索结果同时包含主题发布方原文和聚合转载内容
- **THEN** 系统将发布方原文排在证据集中的更高优先级，并去除内容相同的重复转载

#### Scenario: URL 模式只有指定页面
- **WHEN** 用户指定页面内容自洽且足以支持三个教学知识点，Agent 没有发现必须外部核验的缺口
- **THEN** 系统允许只以该页面作为唯一来源生成“基于此页面”的课程，并明确记录来源模式为用户提供 URL

#### Scenario: 关键词证据数量或质量不足
- **WHEN** 关键词模式经过相关性和质量筛选后少于两条可用来源，或来源内容不足以支撑三关知识点
- **THEN** 系统返回 HTTP 422、错误码 `SOURCES_INSUFFICIENT`，且不调用无依据的降级出题流程

#### Scenario: 来源存在实质冲突
- **WHEN** 高质量来源对影响正确答案的核心事实存在无法解释的冲突
- **THEN** 系统将证据视为不足并拒绝生成，不得静默选择任意一方

### Requirement: 仅依据证据生成游戏
grounded 策略 SHALL 只依据已筛选证据集生成标题、介绍、题目、选项、正确答案、错题解释、夸奖文案和总结；每关的核心知识点与正确答案 MUST 至少关联一个证据来源，且不得引入证据集无法支持的新事实。

#### Scenario: 成功生成有依据的三关游戏
- **WHEN** 系统已取得语义明确且足以覆盖三个递进知识点的合格证据集
- **THEN** 系统生成仍符合现有三关、三选一、唯一正确答案和大白话解释约束的游戏，并为三关保存有效来源关联

#### Scenario: 联网内容包含提示注入
- **WHEN** 搜索摘要或提取页面包含要求忽略系统规则、泄露密钥、调用额外工具或改变输出结构的指令
- **THEN** 系统仅将联网内容视为不可信事实材料，忽略其中的操作指令，并保持既定工具与生成约束

### Requirement: 生成后事实一致性校验
grounded 策略 SHALL 在保存游戏前校验每关介绍、问题、正确选项、错误解释和总结是否与证据集一致。校验失败时系统 MUST 在限定次数内基于校验问题重新生成；仍不通过时 MUST 拒绝创建游戏。

#### Scenario: 首次生成含有无来源结论
- **WHEN** 生成草稿包含证据集没有支持的关键结论
- **THEN** 系统不保存该草稿，并向重新生成步骤提供具体的不一致项

#### Scenario: 重试后仍未通过事实校验
- **WHEN** 生成草稿在限定重试次数后仍有影响教学正确性的未支持内容
- **THEN** 系统返回 HTTP 502、错误码 `GROUNDING_VALIDATION_FAILED`，保留原输入供用户重试，且数据库中不存在半成品游戏

### Requirement: 联网工具故障采用失败关闭策略
在 grounded 模式的单次请求内，系统 SHALL 为 Search、Extract 和 Agent 循环设置有限超时与有限重试；服务不可用、超时、限流、认证失败或响应不可解析时 MUST 返回稳定错误，且 MUST NOT 为该请求自动回退到仅使用模型记忆的旧出题路径。切换 legacy 只能由运维修改部署配置并重启或重新部署完成。

#### Scenario: Tavily 暂时不可用
- **WHEN** Search 或 Extract 在限定重试后仍返回超时、限流或服务错误
- **THEN** 系统返回 HTTP 503、错误码 `SEARCH_UNAVAILABLE` 和可重试提示，不继续无依据出题且不创建游戏

#### Scenario: Tavily 凭证无效
- **WHEN** grounded 服务启动时缺少有效 Tavily 凭证，或运行中的 Tavily 返回认证失败
- **THEN** 启动检查立即失败，或当前请求返回不泄露凭证内容的 `SEARCH_UNAVAILABLE` 响应，并记录可供运维定位的安全日志

#### Scenario: Tavily 故障不触发请求内降级
- **WHEN** grounded 请求已发生 Tavily 超时、限流、认证或响应错误
- **THEN** 当前请求返回对应稳定错误且不调用 legacy 生成器；是否整体降级由运维在后续部署中显式决定

### Requirement: 来源可追溯且持久一致
grounded 策略成功创建的游戏 SHALL 保存输入类型、资料获取时间及最终来源元数据，每条至少包含稳定标识、标题、公开 URL、站点域名和获取方式 `search` 或 `extract`。legacy 策略创建的游戏 SHALL 保存 `input_type=keyword`、`retrieved_at=null` 和 `sources=[]`。创建游戏和后续读取同一游戏时 MUST 返回一致的策略结果，且不得重新研究后悄然改变历史题目的依据。

#### Scenario: 创建响应包含来源
- **WHEN** grounded 游戏成功创建
- **THEN** API 在保持现有字段兼容的同时返回 `input_type`、`retrieved_at` 和符合当前输入模式数量要求的去重来源元数据

#### Scenario: legacy 创建响应明确无联网来源
- **WHEN** legacy 关键词游戏成功创建
- **THEN** API 返回 `input_type=keyword`、`retrieved_at=null` 和 `sources=[]`，前端不得展示“已联网”或参考资料区域

#### Scenario: 重新读取历史游戏
- **WHEN** 用户随后读取已创建的游戏
- **THEN** API 返回创建时保存的相同输入类型、资料获取时间和来源集合，而不是以新的研究结果替换它们

#### Scenario: 通关后查看参考资料
- **WHEN** 用户完成三关并进入通关结果
- **THEN** 小程序展示本局参考资料的标题、站点、获取方式和链接操作，并明确资料获取日期；微信小程序端允许复制链接，H5 端允许直接打开链接

### Requirement: 密钥和用户数据隔离
grounded 策略 SHALL 仅在后端通过 `TAVILY_API_KEY` 使用 Tavily 凭证；legacy 策略 MUST NOT 读取凭证值或构造 Tavily 客户端。凭证 MUST NOT 被提交到版本控制、写入 OpenSpec 产物、包含在前端构建、返回给客户端或出现在应用日志中；发送给 Tavily 的内容 MUST 限于通过安全检查的关键词、公开 URL 及 Agent 为研究构造的参数，不包含 OpenID、JWT 或其他用户标识。

#### Scenario: 构建小程序前端
- **WHEN** 前端执行开发或生产构建
- **THEN** 构建产物不包含 Tavily API 密钥或可直接调用 Tavily 的客户端逻辑

#### Scenario: 记录联网研究诊断信息
- **WHEN** 系统记录工具名称、搜索耗时、结果数量、错误类型或请求标识
- **THEN** 日志排除或脱敏 Tavily 凭证、用户身份、URL 用户信息和可能包含令牌的查询参数

#### Scenario: Agent 尝试发送用户身份
- **WHEN** Agent 生成的工具参数包含 OpenID、JWT 或与学习内容无关的用户身份数据
- **THEN** 确定性工具边界拒绝该调用并记录不含原始敏感值的安全事件
