# Daily News Assistant

每日 AI 新闻助手 Agent —— 用 LLM 驱动的智能体，每天自动为用户整理一份 AI 新闻简报并推送。用户可以按自己的偏好订阅（关注的话题、关键词），Agent 据此筛选内容。

## 功能

- **Agent 自主决策**：基于 DeepSeek function calling 循环，工具调用顺序、搜索哪些关键词、调用几次、何时停止，全部由 LLM 自主决定，不是硬编码流程
- **个性化订阅**：每个用户自定义关注话题与关键词，Agent 据此搜索、过滤、撰写专属简报
- **联网搜索**：通过 Tavily / Brave Search API 实时搜索最新新闻
- **定时推送**：APScheduler 每天定时生成，推送到钉钉 / 飞书 / 企业微信机器人 webhook
- **Web 界面**：填写身份、设置订阅偏好、手动触发生成、查看历史简报

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLite
- **LLM**：DeepSeek（OpenAI 兼容接口 + function calling）
- **搜索**：Tavily（默认）或 Brave Search API
- **推送**：钉钉 / 飞书 / 企业微信自定义机器人
- **调度**：APScheduler

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

# 4. 启动（首次启动自动按 schema.sql 建表）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. 打开浏览器
# http://localhost:8000 —— 填写身份和订阅偏好，点「立即生成」
```

### 可选：配置 IM 推送

在 `.env` 中设置（不配置则只在 Web 页面查看简报）：

```bash
PUSH_CHANNEL=dingtalk        # dingtalk | feishu | wecom
PUSH_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=SECxxx       # 仅钉钉机器人开启"加签"时需要
```

也可以在 Web 页面给单个用户填专属 webhook，实现"每人推送到各自群"。

## Agent 工具集

| 工具 | 说明 |
| --- | --- |
| `list_dir(path)` | 列出目录内容 |
| `read_file(path)` | 读取文件 |
| `search_content(keyword, dir)` | 在目录下按关键词搜索文件内容 |
| `write_file(path, content)` | 写入文件（Agent 用它落盘最终简报 markdown） |
| `bash(command)` | 执行 shell 命令 |
| `web_search(query)` | 联网搜索最新新闻（Tavily / Brave） |

Agent 循环实现在 `app/agent/loop.py`：每轮把工具清单交给 DeepSeek，模型返回 `tool_calls` 则执行并回填结果，直到模型给出最终回答（或达到最大迭代次数）。文件类工具出于安全限制在项目目录内操作。

## 项目结构

```
app/
├── main.py        # FastAPI 入口：API + 静态页面 + 启动初始化
├── config.py      # 环境变量配置
├── db.py          # SQLite 数据访问
├── news.py        # Tavily / Brave 搜索
├── push.py        # 钉钉 / 飞书 / 企业微信推送
├── scheduler.py   # APScheduler 每日定时任务
└── agent/
    ├── loop.py    # function calling Agent 循环
    └── tools.py   # 工具集定义与实现
static/index.html  # Web 前端
schema.sql         # 建表 SQL
```

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/users` | 用户列表 / 创建订阅 |
| PUT/DELETE | `/api/users/{id}` | 更新 / 删除订阅 |
| GET | `/api/briefings?user_id=` | 历史简报 |
| POST | `/api/generate` | 手动触发一次 Agent 生成 |

## License

[MIT](LICENSE)
