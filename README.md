# Daily News Assistant

每日 AI 新闻助手 Agent —— 用 LLM 驱动的智能体，每天自动为用户整理一份 AI 新闻简报并推送。用户可以按自己的偏好订阅（关注的话题、关键词），Agent 据此筛选内容。

## 功能

- **自动简报**：每天定时抓取、筛选、汇总 AI 领域新闻
- **个性化订阅**：用户自定义关注话题与关键词，Agent 据此过滤内容
- **Agent 自主决策**：工具调用顺序由 LLM 通过 function calling / ReAct 循环自主决定，而非硬编码流程

## 技术栈

- Python
- Web 前端（简单页面：填写身份、设置订阅偏好、查看历史简报）

## 快速开始

> 🚧 项目开发中，以下步骤将在代码完成后提供。

```bash
# 1. 克隆仓库
git clone https://github.com/xiayang544/Daily-News-Assistant.git
cd Daily-News-Assistant

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量（密钥不硬编码）
cp .env.example .env
# 编辑 .env 填入 API Key

# 4. 启动服务
python main.py
```

## 工具集

Agent 内置以下工具供 LLM 自主调用：

| 工具 | 说明 |
| --- | --- |
| `list_dir(path)` | 列出目录内容 |
| `read_file(path)` | 读取文件 |
| `search_content(keyword, dir)` | 按关键词搜索目录下文件内容 |
| `write_file(path, content)` | 写入文件 |
| `bash(command)` | 执行 shell 命令 |

## License

[MIT](LICENSE)
