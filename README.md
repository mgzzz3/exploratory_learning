# AI 万物学堂 MVP

一个把学习主题转成三关小游戏的微信小程序。前端使用 Taro 4、React 18、TypeScript 和 Zustand；后端使用 FastAPI、Pydantic v2、SQLAlchemy 2、MySQL 8、LangChain Agent 与 OpenAI SDK，模型服务为 DeepSeek。

当前工作区包含 Tavily 联网生成与手动基础知识兜底的开发版本，尚未完成全部真实主题和微信端验收，也未发布到生产。验收边界见 [TDD 实施记录](dosc/联网生成TDD实施记录.md)。

## 已实现

- 微信 `wx.login` 静默登录与服务端 JWT
- 用户主题先经过微信内容安全检查，再交给 AI
- AI 严格生成新手、进阶、Boss 三关，每关一道三选一题
- 答对晋级；答错用大白话解释并扣一颗心；归零暂停
- 完整观看激励视频或另一位好友使用单次助力卡后恢复三颗心
- 通关小报、学习统计、音效、振动与联网搜索开关设置
- 内容拦截、AI 生成失败、网络中断和幂等重试状态
- 设计稿中的 18 个核心、反馈、恢复和异常状态

## 本地启动

### 1. MySQL 与后端

```bash
cp .env.example .env
cd backend
docker compose -f compose.development.yml up -d --wait
docker compose -f compose.test.yml up -d --wait
python3.11 -m venv .venv
.venv/bin/pip install -e '.[research,test]'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端始终从仓库根目录的 `.env` 读取配置，因此从仓库根目录或 `backend` 目录启动均可。本地开发库为 `127.0.0.1:3306/ai_school_dev`，测试库为 `127.0.0.1:3307/ai_school_test`，二者和线上库完全隔离。DeepSeek 密钥支持 `DEEPSEEK_API` 和 `DEEPSEEK_API_KEY` 两种变量名；密钥只由后端读取，不会打包进小程序。

首次才复制环境示例，不要覆盖已配置的 `.env`。`QUESTION_GENERATION_MODE=grounded` 为默认联网模式，需要后端配置 `TAVILY_API_KEY` 与 DeepSeek key；`legacy` 为独立的旧关键词生成策略，可只安装 `.[test]`，不导入研究依赖、不调用 Tavily、不接受网址或新的 basic 许可。配置与回退细节见 [联网生成调试与回滚](dosc/联网生成调试与回滚.md)。

开发环境会分别判断服务凭证：微信凭证兼容 `WX_APP_ID`/`WX_APP_SECRET` 和 `WECHAT_APP_ID`/`WECHAT_APP_SECRET` 两组变量名；没有微信凭证时使用本地微信登录，但只要配置了 DeepSeek 密钥，AI 内容生成就会调用真实 DeepSeek。`USE_MOCK_SERVICES=true` 会强制两者都使用确定性的本地服务。生产环境必须设置真实凭证并保持 `USE_MOCK_SERVICES=false`。

AI 提供商通过 `AI_PROVIDER` 选择，默认 `deepseek`。提供商在 `backend/app/clients/ai/` 以注册表方式接入：新增一个提供商模块并调用 `register_ai_provider` 即可，不需要改动既有提供商和服务层。用户也可以在小程序“我的-学习设置”里关闭联网搜索，关闭后出题直接使用 AI、不再联网检索（网页地址输入仍要求联网）。

### 2. 小程序前端

```bash
cd frontend
pnpm install
pnpm dev:weapp
```

`pnpm dev:weapp` 明确加载 `.env.development`，监听代码并请求本机 `http://127.0.0.1:8000/api/v1`。真机调试时，将 `.env.development.local.example` 复制为 `.env.development.local`，把地址改成电脑局域网 IP，然后重启命令。需要用开发构建联调线上后端时运行 `pnpm dev:weapp:online`。

`pnpm build:weapp` 明确加载 `.env.production`，生成请求 `https://api.bkgame.cc/api/v1` 的生产包。将 `frontend/dist` 导入微信开发者工具；切换环境后必须重新运行对应命令，因为 Taro 只在构建时读取环境文件。部署完成后还需要在微信公众平台把 `https://api.bkgame.cc` 加入 request 合法域名，并在 `.env.production` 配置 `TARO_APP_AD_UNIT_ID`。

H5 联调可运行 `pnpm dev:h5`，默认请求 `http://127.0.0.1:8000/api/v1`。

## 验证

```bash
cd backend
.venv/bin/pytest --cov=app --cov-report=term-missing

TEST_MYSQL_DATABASE_URL='mysql+asyncmy://root:test-password@127.0.0.1:3307/ai_school_test?charset=utf8mb4' \
  .venv/bin/pytest

cd ../frontend
pnpm test
pnpm typecheck
pnpm lint
pnpm build:weapp
pnpm build:h5
```

FastAPI 文档在后端启动后位于 `http://127.0.0.1:8000/docs`。MySQL 集成测试只允许连接数据库名以 `_test` 结尾的独立测试库。

## 生产部署

生产环境使用 `backend/compose.production.yml` 启动 MySQL 8.4、数据库迁移、FastAPI 和 Caddy。Caddy 为 `api.bkgame.cc` 自动申请并续期 HTTPS 证书，MySQL 不暴露公网端口。

```bash
cd backend
cp .env.production.example .env.production
# 填入随机数据库密码、JWT 密钥、微信凭证、DeepSeek 与 grounded 模式的 Tavily 密钥
docker compose --env-file .env.production -f compose.production.yml up -d --build
```

服务器防火墙只需向公网开放 TCP 22、80、443 和 UDP 443；不要开放 MySQL 3306。域名的 `api` A 记录必须指向服务器公网 IP，HTTPS 才能自动签发。

以上为部署说明，不代表本次已执行发布。默认 Docker 镜像安装 research extra；显式构建 `--build-arg INSTALL_RESEARCH=false` 时只能运行 legacy 模式。生产使用独立的 `backend/.env.production`，不要用本地 `.env` 覆盖生产配置，也不要因切换生成模式回退数据库迁移或移除 basic 的未核验标识。
