# 联网生成 TDD 实施记录

日期：2026-08-31。变更：`ground-ai-question-generation-with-tavily`。

自动化 TDD 使用隔离的模型/工具/微信夹具；真实开发凭证的受控验证在后文单独列出。本文不包含生产发布。完成状态以 OpenSpec 任务清单为准，未通过的环境门禁不计为完成。

## 兼容边界确认

用户已确认官方 Tavily 固定格式的数字 HTTP 状态码兼容例外。仅适配层允许解析，结构化状态优先，未知格式/状态失败关闭，自由描述不参与分类。规划更新范围是已有 design、delta spec、tasks；proposal 的目标不变。主规格未同步，变更未归档。

## 已完成的红灯与绿灯

| 任务 | 红灯证据 | 绿灯证据 |
| --- | --- | --- |
| 1.9–1.10 预算配置 | `pytest tests/test_config.py -k reserve --tb=line`：16 failed、7 passed；缺少三个预留字段及组合校验 | `pytest tests/test_config.py tests/test_generation_strategy.py tests/test_packaging.py`：52 passed |
| 3.6–3.7 Tavily 类型化错误、有限重试及窗口 | `pytest tests/test_tavily_failures_and_budget.py --tb=line`：46 failed；缺少调用上下文、reason，旧文案匹配及重试不符合约束 | 加既有 Search/Extract 和官方工具 HTTP 契约测试：69 passed |
| 2.7–2.8 服务端证据台账 | 新测试首次运行：19 项因模型/状态未实现而失败，另 1 项为测试辅助参数重名，修正辅助函数后验证 | 台账、证据模型、生成 Schema、旧 Agent 和注入测试：53 passed |
| 4.8–4.15 真正 Agent 编排 | 首批真实 `create_agent` 测试：18 failed、1 passed；后补隔离、资料不足、未知工具：4 failed。模型/工具 fake 之外使用实际 LangChain 图 | 真实编排、旧编排/动态策略/注入及正文分块：59 passed |
| 5.7–5.8 绝对截止时间 | 新增跨阶段测试暴露缺少预算模块；完成预算骨架后，检索窗口关闭/在途取消/SDK 隔离仍有 3 failed、10 passed | 预算、真实/旧 Agent、生成校验、注入：62 passed；阶段性全量 324 passed、1 deselected |
| 5.9–5.10 HTTP 错误与断连 | `test_generation_errors.py`：15 failed；reason/request_id 缺失、原错误混淆、HTTP 断连不停止生成；补正文原因分类 2 failed | 错误、预算、流水线、持久化：44 passed；正文原因和 MySQL 定向回归 8 passed |
| 5.11–5.14 准入与短期许可 | `test_basic_permits.py`：60 failed，策略/许可模块未实现；补非 ASCII 绑定格式 1 failed | 策略/许可加 HTTP/预算：88 passed；非 ASCII 绑定已通过最终全量验证 |
| 5.15–5.18 模式迁移与原子保存 | `test_basic_persistence.py`：7 failed，字段/迁移/共享保存缺失 | 新旧持久化、迁移和流水线：24 passed；真实 MySQL 双连接竞争仅保存一局 |
| 5.19–5.21 独立 basic 接口与三路径 | `test_basic_endpoint.py`：19 failed，端点 405、服务缺失 | basic HTTP/许可/持久化：86 passed；另在 MySQL 同时请求 grounded、legacy、basic 重放，确认模式互不影响 |

所有命令从 `backend/` 执行，Python/pytest 使用项目 `.venv/bin/python -m pytest`。普通测试中出现的凭证、主题、页面内容均为虚构夹具；HTTP fake 不收集请求头。

研究编排验收包括：一次搜索后停止、两次搜索加一次提取后的第三次搜索意图被拦截但保留证据、四次工具后整理、预留最后两次模型调用、并发工具不超额、格式与后置验收共享一次纠正、零工具补齐首个必需调用、歧义/不足/冲突不触发格式重搜，以及成功/异常/取消的请求状态清理。

旧测试里“每次纠错重新编译 Agent”和“从自然语言截 JSON”的预期已按批准的新契约替换；来源防伪、动态参数和安全约束仍保留。额外检查“结构化响应与未知工具同时出现”在既有新中间件下即被拒绝，作为回归测试保留，没有为该检查添加额外实现。

## 阶段性全量回归

```sh
.venv/bin/python -m pytest -m 'not mysql' --tb=short
```

研究编排改造后：**311 passed, 1 deselected**。被排除的 MySQL 集成不算通过。

## 第一阶段后端全量与真实 MySQL 验证（历史结果）

本轮创建了仅绑定 `127.0.0.1:13316` 的独立临时 MySQL 8.4 容器和 `grounded_regression_test` 数据库。现有开发容器、数据库和生产环境没有改动；真实数据库中的 AI、微信调用仍为 fake。

验证结束后，已核对临时容器的完整 ID、名称、镜像与端口，并仅删除本轮创建的 `codex-grounded-mysql-20260831` 及其临时数据卷。测试数据可由测试夹具重建，没有删除开发数据库。

```sh
TEST_MYSQL_DATABASE_URL='mysql+asyncmy://root@127.0.0.1:13316/grounded_regression_test?charset=utf8mb4' \
  .venv/bin/python -m pytest --cov=app --cov-report=term --tb=short
```

结果：**430 passed，无跳过**，包含 2 项真实 MySQL 集成。验证旧 JSON/URL/时区、0002→0003 增量迁移及往返、已有来源回填、唯一许可 ID、多连接并发重放、三种模式并发，以及 flush/关卡写入/commit/取消回滚。MySQL 竞争测试允许两次外部生成，但最终仅有一局完整游戏；不宣称模型调用或计费 exactly-once。

pytest 的行与分支合并覆盖率为 **91.68%**，达到现有工具配置的 85% 合并门槛；单独检查 coverage JSON 得到**纯分支覆盖率 540/654 = 82.57%**，尚未满足任务 7.3 的独立分支 85% 要求，故 7.3 不勾选。

原 API 测试“在错误中返回完整 topic”的断言已按批准的最小化诊断契约更新为安全 reason 和随机 request_id；不再把用户完整输入回写错误。歧义候选仍保留。

## 新增 UI 原型检查（任务 6.3）

已完整读取需求分析和现有 `design/` 页面、共享样式与脚本。在 `design/05-basic-recovery.html` 中新增 12 个评审状态，复用已有纸张底色、橙色主按钮、蓝色提示、字体和手机布局；附加样式仅作用于本原型，未改对应小程序 TSX/SCSS。

本地预览为 `http://127.0.0.1:8877/05-basic-recovery.html`，服务器仅暴露 `design/` 目录并绑定回环地址。内置浏览器逐状态检查了获准失败、选择前告知、basic 等待、未获准、无 HTTP 响应、许可过期、basic 失败、修改输入、联网等待、创建/答题、通关和重进。

- 1280×1050、375×812、812×375 三个视口均无页面或手机内容横向溢出；375 像素视口的主要操作和导航点击高度不少于 44 像素。
- 实际点击“选择基础知识题”到告知页，再点击明确同意到 basic 等待页；未获准、无响应、许可过期三页没有基础知识入口。
- 截图核对了题目、通关和重进三个状态始终存在“未经联网核验”，没有虚构来源、加载百分比或阶段进度；静态示例题不代表真实模型验收。
- 截图保存在本机 `/tmp/exploratory-basic-review-choice.png`、`/tmp/exploratory-basic-review-mobile.png` 和 `/tmp/exploratory-basic-review-persistent.png`，仅作为本轮评审证据。

这是 HTML 原型检查，不替代 H5 应用或微信小程序联调。用户在查看原型及明确确认问题后回复“继续”，确认新增交互、文案和“未经联网核验”标识；6.4 门禁通过。本轮开始对应小程序实现，不扩大到用户系统或生产部署。

## 第二阶段：前端、诊断与有界纠错 TDD

以下均为先观察预期失败、再实现修复；已有工作区改动未回退。

| 范围 | 红灯证据 | 绿灯证据 |
| --- | --- | --- |
| 前端许可与显式选择 | 新状态模块/API 尚不存在；取消和登录刷新各 2 项失败；未获准文案 1 项失败 | 前端共 61 项通过，包含 24 项 basic 状态测试、3 项取消、2 项登录刷新；typecheck/lint 通过 |
| 日志与指标 | 诊断模块缺失；Alembic 禁用 logger、Uvicorn 五参数格式共 2 项失败 | 结构化日志、异常链脱敏、随机请求关联、准入与计数回归通过 |
| 工具/模型统计 | 缺少结果数、正文字符数及 token 统计导致 1 项失败 | 定向回归 39 项通过；物理 Tavily 请求/重试另有回归 |
| legacy 异常链 | 供应商异常作为 cause 泄露，1 项失败 | 移除敏感异常链，定向 21 项通过 |
| 研究格式纠正 | LangChain Schema 错误不能提供安全字段约束，1 项失败 | 只回传允许字段与类型、不含原输入，定向 41 项通过 |
| 容器研究依赖 | 默认构建未安装 research extra，1 项失败 | 默认包含 research、可显式剥离；packaging/日志定向 22 项通过（未构建实际镜像） |
| 生成 JSON 纠正 | 非法 JSON 直接失败、不使用既有一次纠正机会，2 项失败 | 格式/事实纠正共享一次额度及原截止时间，定向 35 项通过；不得跳过事实校验 |
| 恢复成功的请求原因 | 曾失败后恢复的请求仍记录失败 reason，1 项失败 | 最终成功记录 OK，单次失败阶段仍保留安全原因；全量回归通过 |

前端已按批准原型实现 TSX/SCSS：许可仅保存在页面实例内存，不进入持久化 store、URL 或日志；换输入/身份/离开清除，迟到结果不能恢复入口；无 HTTP 响应不推断授权。basic 成功后由数据库字段决定固定“未经联网核验”提示，旧无来源游戏不被误标 basic。取消会调用实际请求任务的 abort。同一用户刷新登录不再误清当前流程，其他账号的迟到刷新结果不能覆盖新身份。

后端安全诊断仅保留白名单阶段/模式/原因、耗时和数值计数；不记录完整主题、URL、网页正文、用户身份、许可或模型响应。LangSmith 在研究图调用处明确关闭载荷追踪。指标为进程内低基数直方图，P50/P95 是桶上界，不是精确采样；当前没有公开 metrics 端点。模型计数为 Agent 实际调用与生成器逻辑调用，不能据此声称已包含 legacy SDK 的隐藏物理重试。工具来源数为实际取得来源，非最终入选来源数。

### 第二阶段全量结果

再次使用仅绑定回环地址的临时 MySQL 8.4 容器 `exploratory-grounded-qa-20260831`，不访问开发库或生产库：

```sh
TEST_MYSQL_DATABASE_URL='mysql+asyncmy://root@127.0.0.1:13316/grounded_regression_test?charset=utf8mb4' \
  .venv/bin/python -m pytest --cov=app --cov-report=term \
  --cov-report=json:/tmp/exploratory-coverage.json --tb=short --show-capture=no
```

结果：**475 passed，无跳过**，含 2 项真实 MySQL 集成。合并覆盖率 **93.39%**；纯分支 **624/724 = 86.19%**，达到 85% 分支门槛。数据库约束/事务仍参与测试；外部 AI、Tavily、微信与 DNS 为受控夹具。

本轮临时 MySQL 容器完成后已核对完整 ID/镜像/端口，停止并仅删除该容器及其独立数据卷；再次确认原 `backend-mysql-dev-1` 仍运行、临时卷不再存在。测试数据可重建。

`pnpm test`：**61 passed**；`pnpm typecheck`、`pnpm lint`、`pnpm build:weapp`、`pnpm build:h5` 均通过。构建仍有 Sass legacy JS API 弃用提醒，无构建错误。构建成功不等同于双端 UI 验收通过。

### 实际 H5 联调（隔离夹具，不是真实 AI）

使用 `tests/ui_preview.py`，必须显式设置 `ALLOW_UI_FIXTURES=1`，仅绑定 `127.0.0.1:8878`；内存数据库和 fake 微信/AI，无生产入口引用。H5 开发服务在本机 10086 端口。此环境不代表真实微信内容安全验收。

- 实际点击“高情商聊天”→联网失败→基础知识告知，确认前 basic 请求计数不增加；确认后独立发 basic 请求，完成三关。
- 答题、通关、刷新重进均显示固定未核验提示，无联网来源区；375×812 截图无横向溢出。
- 实际取消延迟研究后，后端取消计数增加，游戏数未增加；不会后台保存取消结果。
- 注入 basic 生成失败，显示专用失败及重试操作；失败前后游戏数均为 3，未产生半局。
- 后续再次验证 basic 失败：请求计数 4→5、游戏数仍为 3；恢复夹具后主动点击“重试基础知识题”，计数 5→6、游戏数 3→4。确认失败不会自动重试。
- 已观察八类联网业务错误（搜索失败、网页不可读、歧义、资料不足、研究失败、事实校验失败、无效网址、legacy 不支持 URL）；修改操作保留输入。等待真实 5 分钟后，许可自动失效、入口消失，只提供重新联网/修改主题；截图 `/tmp/exploratory-basic-h5-expired.png`。
- H5 公开网址夹具完成三关，通关资料区显示 `2026.08.31`、1 条、整页读取、标题/域名；此处仅验证资料区渲染，不代表夹具中的题目使用了真实 Python 文档内容。
- 点击 H5 来源按钮后，内置浏览器未观察到新页面，不能宣称“打开链接”已通过；此项和微信复制链接仍待验证。
- 停止仅本轮创建的 8878 夹具后，实际请求无 HTTP 响应，页面显示“未收到生成结果”和结果未知提示，仅有重试联网/返回修改，没有 basic 入口；截图 `/tmp/exploratory-basic-h5-network.png`。随后重新启动全 fake 夹具，旧内存测试游戏随进程退出释放，不影响开发/生产库，可重新生成。

证据截图在本机 `/tmp/exploratory-basic-h5-consent.png`、`/tmp/exploratory-basic-h5-game.png`、`/tmp/exploratory-basic-h5-complete-mobile.png`。不包含真实凭据或研究正文。

### 微信开发者工具实际交互（隔离夹具）

官方自动化 SDK 可连接和截图，但元素查询有挂起；转用 macOS 可访问控件，并把模拟器置于前台后，可以实际操作。后台模拟器会暂停页面更新，不能仅凭后台静止画面判断应用死锁。

最新代码使用本机 8878 夹具构建到独立 `/tmp/exploratory-weapp-qa.UBZcXC` 项目，未覆盖用户原开发者工具项目。点击联网失败→基础知识告知时 basic 计数保持 6；主动确认后 basic=7、游戏数 4→5、安全检查累计 30。实际完成三关、刷新通关页，固定未核验标识始终存在，没有来源区或联网标识。

截图：`/tmp/exploratory-weapp-basic-game.png`、`/tmp/exploratory-weapp-basic-complete.png`。这是微信开发者工具中的实际页面与 HTTP 交互，但 AI/微信服务仍为 fake，不等同于真实接口或真机验收。

### 可剥离 legacy 验证

新建临时 venv `/tmp/exploratory-legacy-qa.BgipzP/venv`，只安装 `.[test]`，确认 LangChain/Core/DeepSeek/Tavily/LangSmith 均未安装。注入测试设置后关键词创建返回 201，URL 返回 422/URL_REQUIRES_RESEARCH、无兜底；已保存游戏可读取。另仅在内存测试数据中模拟已有 basic 记录，legacy 读取仍保留固定未核验提示。

完整依赖环境的 HTTP 测试验证 grounded→legacy→grounded、许可禁用与已有 basic 重读。使用注入的 Settings 切换，未修改任何真实 `.env`、未重启生产服务；这不是生产回滚演练。全局回退仍须保留当前兼容字段的代码与迁移，不能退回不显示 basic 标识的旧版本。

## 真实开发接口验证（与上述离线测试分开）

使用当前配置模型 `deepseek-v4-flash` 及开发 Tavily 凭证，不输出密钥、不切换模型。模型能力检查成功：4 次模型调用、2 次 Search + 1 次 Extract，服务端接受结构化 `ResearchConclusion`，耗时约 21.94 秒。

以下是真实研究→生成→事实校验的策略调用，**不包含实际微信安全接口和 HTTP 持久化**，所以不能代替任务 7.7/7.8 的完整端到端验收。每例有界执行，没有无限重试；来源仅记录数量，不保存正文。

| 用例 | 首轮结果 | 耗时 |
| --- | --- | --- |
| 高情商聊天 | Search 后 Extract 失败：PAGE_EXTRACTION_FAILED | 9.49 秒 |
| Harness Engineering | INVALID_RESEARCH_OUTPUT | 25.40 秒 |
| 什么是变量 | 三关通过，3 来源 | 16.02 秒 |
| Transformer 注意力机制 | INVALID_RESEARCH_OUTPUT | 27.83 秒 |
| Python 文档公开 URL | 研究通过，INVALID_GENERATED_OUTPUT | 19.13 秒 |
| Python calendar 含表格 URL | 三关通过，4 来源；advanced/full Extract，32032 字符 | 24.64 秒 |
| 杭州的西湖是什么 | 两次事实校验不通过，未交付草稿 | 32.81 秒 |
| Rust 所有权基本概念 | 一次反馈修正后通过，5 来源 | 38.38 秒 |

定向修复后的复核：

- Harness Engineering：增加安全 Schema 约束反馈后，研究收敛到 AI agent 领域，5 来源，三关经一次事实反馈修正后通过，约 41.02 秒。
- 高情商聊天：曾在研究成功后输出非法 JSON，类型为 `json_invalid`（未记录原响应）。因此补齐格式纠正的 TDD，仍共享一次重生成上限。
- 最新一次高情商聊天：研究和初次生成通过，但事实校验分别报告 7、6 项问题，一次重生成仍失败，约 44.01 秒。**没有绕过校验或当作成功保存**；还不能宣称真实联网生成已稳定修复。

另发现：已审核关键词也可能因后续 Extract 失败而返回 `PAGE_UNREADABLE`。现有批准准入规则不包含该错误；是否扩大“仅已审核关键词”的手动兜底范围已向用户提问，尚无针对该规则的明确确认，当前不擅自修改。

### 真实 basic / 微信安全联调的授权门禁

曾准备仅绑定 8879 的临时内存库，使用真实微信/DeepSeek 客户端，仅对研究阶段注入失败；未改配置文件。开发者工具当前身份的登录刷新可能触发真实微信认证，但后续内容安全及研究操作需要针对该身份的明确授权，已暂停并向用户说明。安全计数为 online=0/basic=0/games=0/safety_checks=0，不能计作真实 basic 成功。

该临时进程已停止，内存数据随进程释放；QA 构建恢复指向全 fake 的 8878 服务，正式 `dist` 重新构建为生产 API 地址。不通过其他接口绕过真实身份授权门禁。

## 产物与规格检查

前端 H5 构建连同待提交文件扫描 224 个文件、微信构建连同待提交文件扫描 242 个文件，对本地已配置的 3 项服务秘密只做内存比对，未发现泄露或私钥。微信正式 `dist` 恢复为生产 API 配置，不含本机 QA 地址或前端直连 Tavily。

后端构建 wheel 成功，检查包内 48 个文件，未包含环境文件、QA 入口、测试夹具或已配置的秘密。`git diff --check` 与 `openspec validate ground-ai-question-generation-with-tavily --strict` 通过。本轮只标记有证据的任务，未同步主规格、未归档、未推送。

## 尚未完成的交付门禁

- 微信开发者工具已实际完成 basic 选择/三关/刷新，仍未完成全部错误状态、grounded 来源复制与旧游戏状态的双端验收；不能据此宣称全部小程序功能可交付。
- H5 八类业务失败与无 HTTP 响应已验；真实微信安全/basic 主动选择端到端、所有真实主题稳定性及动态参数核验仍未完成。
- 6.7 的 H5 故障界面及 7.3 自动化全量/分支覆盖率门禁已通过；任务 6.8–6.10、7.4、7.7–7.9 保持未勾选，不能将局部 UI 验收作为完整交付。
- 本轮不包含生产部署、远端推送、主规格同步或归档。
