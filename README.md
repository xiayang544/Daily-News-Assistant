# Daily News Assistant

每日 AI 新闻助手 Agent —— 用 LLM 驱动的智能体，每天自动为用户整理一份 AI 新闻简报并推送。用户可以按自己的偏好订阅（关注的话题、关键词），Agent 据此筛选内容。

## 功能

- **Agent 自主决策**：基于 DeepSeek function calling 循环，工具调用顺序、搜索哪些关键词、调用几次、何时停止，全部由 LLM 自主决定，不是硬编码流程
- **个性化订阅**：每个用户自定义关注话题与关键词（预设话题 + 自定义），Agent 据此搜索、过滤、撰写专属简报
- **RSS + 搜索混合采集**：feedparser 抓取已配置 RSS 源（稳定基线），Tavily / Brave 联网搜索补充覆盖，`get_article` 核实原文
- **防幻觉约束**：简报每条新闻必须来自工具真实返回，保留原始 URL、来源、发布时间；采集到的新闻落入 `news_items` 表（URL 唯一去重）
- **定时邮件推送**：APScheduler 按用户时区每天触发，SMTP 发送简报邮件（开发环境可用 Mailpit 模拟收信）
- **任务状态机与幂等**：`agent_runs`（running→success/failed）记录每次工具调用轨迹；`deliveries`（pending→sent/failed/skipped）记录推送结果，发送失败可单独重试而不重新生成；按用户+日期防重复生成
- **Web 界面**：填身份（姓名/邮箱/时区）、设置订阅偏好（可暂停）、手动触发生成、查看历史简报与 Agent 工具调用轨迹

## 技术栈

- **后端**：Python 3.9+ / FastAPI / SQLite（六张核心表）
- **LLM**：DeepSeek（OpenAI 兼容接口 + function calling）
- **采集**：feedparser（RSS）+ Tavily（默认）/ Brave Search API
- **推送**：SMTP 邮件（开发环境 Mailpit 模拟）
- **调度**：APScheduler（按用户时区触发）

## 快速开始（5 分钟）

```bash
# 1. 克隆仓库
git clone https://github.com/xiayang544/Daily-News-Assistant.git
cd Daily-News-Assistant

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量（密钥不硬编码）
cp .env.example .env
# 编辑 .env，填入：
#   DEEPSEEK_API_KEY  —— https://platform.deepseek.com/ 申请
#   TAVILY_API_KEY    —— https://tavily.com/ 申请（免费 1000 次/月）
#   SMTP_*            —— 邮件推送配置；本地开发可先起 Mailpit：
#                        docker run -p 1025:1025 -p 8025:8025 axllent/mailpit
#                        （浏览器打开 http://localhost:8025 查看收到的邮件）

# 4. 启动（首次启动自动按 schema.sql 建表）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. 打开浏览器
# http://localhost:8000 —— 填写身份和订阅偏好，点「立即生成」
```

### 定时任务

服务运行期间，APScheduler 每小时检查一次：对每位"订阅中"的用户，其**本地时间**到达
`SCHEDULE_HOUR`（默认 8 点）且当天尚未生成简报时自动执行。暂停订阅（enabled=0）的用户跳过。
服务需保持运行定时才会触发；关闭终端后可用 `nohup` 或部署到服务器长期运行。

## Agent 工具集（八个）

| 工具 | 说明 |
| --- | --- |
| `list_dir(path)` | 列出目录内容 |
| `read_file(path)` | 读取文件（如 config/news_sources.txt 新闻源清单） |
| `search_content(keyword, dir)` | 按关键词搜索文件内容（检索历史简报去重） |
| `write_file(path, content)` | 写入文件（Agent 用它落盘最终简报 markdown） |
| `bash(command)` | 执行受限 shell 命令（只读类白名单） |
| `search_news(query, days)` | 联网搜索最近 N 天新闻（Tavily / Brave） |
| `fetch_rss(source)` | 抓取 RSS 订阅源新闻 |
| `get_article(url)` | 抓取原文页面提取正文，核实新闻 |

Agent 循环实现在 `app/agent/loop.py`：每轮把工具清单交给 DeepSeek，模型返回 `tool_calls`
则执行并回填结果，直到模型给出最终回答。循环施加**最大 12 轮 + 300 秒时间预算**防止无限循环。
调用顺序完全由模型自主决定——`agent_runs` 表保存每次真实调用轨迹
（Web 页面每期简报可点「🔧 工具调用轨迹」查看），不同用户/不同日期的轨迹各不相同。

**安全约束**：文件类工具限制在项目目录内，禁止读写 `.env`、数据库文件；`bash` 仅允许
只读类命令白名单，禁止重定向与命令替换。密钥只经环境变量读取。

## 数据库（六张核心表）

| 表 | 用途 |
| --- | --- |
| `users` | 用户（姓名、邮箱唯一、时区） |
| `subscriptions` | 订阅偏好（话题、关键词、enabled 开关） |
| `news_items` | 原始新闻池（URL 唯一去重、来源、发布时间） |
| `briefings` | 简报（user_id+brief_date 唯一防重复生成） |
| `agent_runs` | Agent 执行记录（完整工具调用轨迹） |
| `deliveries` | 推送记录（状态机，可单独重试发送） |

## 项目结构

```
app/
├── main.py        # FastAPI 入口：API + 静态页面 + 启动初始化
├── config.py      # 环境变量配置
├── db.py          # SQLite 数据访问（六张表）
├── news.py        # 采集层：搜索 / RSS / 原文提取
├── push.py        # SMTP 邮件推送
├── scheduler.py   # APScheduler 定时（按用户时区）+ 推送重试
└── agent/
    ├── loop.py    # function calling Agent 循环（12 轮 + 时间预算）
    └── tools.py   # 八个工具定义与实现（含安全约束）
static/index.html  # Web 前端
config/news_sources.txt  # RSS 新闻源清单
schema.sql         # 建表 SQL
```

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/users` | 用户列表 / 创建用户 |
| GET/PUT/DELETE | `/api/users/{id}` | 用户详情 / 修改 / 删除 |
| GET/PUT | `/api/subscriptions/{user_id}` | 订阅设置 / 更新 |
| POST | `/api/briefings/generate` | 手动触发 Agent 生成简报 |
| GET | `/api/briefings?user_id=&date=` | 历史简报（可按日期过滤） |
| GET | `/api/briefings/{id}` | 简报详情（含推送记录） |
| GET | `/api/agent-runs/{id}` | Agent 工具调用轨迹 |
| POST | `/api/deliveries/{id}/retry` | 重试失败的邮件推送 |

## License

[MIT](LICENSE)
