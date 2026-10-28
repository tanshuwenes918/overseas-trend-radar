# 海外舆情飞书雷达

一个低成本、零三方 Python 依赖的海外舆情自动监控脚本，面向音乐运营场景，支持：

- 三大厂牌官方动态与头部发行观察
- 音乐媒体资讯聚合
- 音乐 / AI / 流媒体产业动态
- 官方订阅价格快照比对
- 海外节庆提醒
- 社媒热点、文化跨界、国际政坛轻量观察
- 每条输出中文摘要 + 信源链接
- 飞书群机器人交互卡片推送

## 目录

- `main.py`: 主程序
- `run_report.sh`: 本地运行包装脚本
- `.github/workflows/daily-report.yml`: GitHub Actions 定时工作流
- `data/state.json`: 价格快照状态文件，首次运行后自动生成

## 使用方式

默认口径：

- 报告发送时间按北京时间 `09:20`
- 每天晨报默认抓取“前一自然日”的内容
- 如果当天 `09:20` 前出现重要官方更新，可作为“今晨补充”加入
- 手动执行 `python3 main.py --dry-run` 时，也会按当天 `09:20` 作为统计截止，而不是按你执行命令的当前分钟漂移

先给脚本可执行权限：

```bash
chmod +x /Users/mac/Downloads/overseas-trend-radar/main.py
chmod +x /Users/mac/Downloads/overseas-trend-radar/run_report.sh
```

### 1. 先预览，不推送

```bash
cd /Users/mac/Downloads/overseas-trend-radar
python3 main.py --dry-run --debug
```

### 2. 推送到飞书

```bash
cd /Users/mac/Downloads/overseas-trend-radar
FEISHU_WEBHOOK_URL='你的 webhook' python3 main.py --send
```

### 3. 指定日期试跑

```bash
cd /Users/mac/Downloads/overseas-trend-radar
python3 main.py --dry-run --date 2026-04-07 --debug
```

## GitHub Actions 执行方案

当前支持两种方式：

- 直接使用 GitHub Actions 内置 `schedule`
- 用外部 cron 调用 `workflow_dispatch`

### 1. 把项目放到 GitHub 仓库

- 直接上传 [overseas-trend-radar](/Users/mac/Downloads/overseas-trend-radar) 整个目录

### 2. 配置 GitHub Actions Secrets

默认推荐直接用 **仓库级 Secret**，不需要先创建 GitHub Environment。

路径：

- 打开 GitHub 仓库
- 进入 `Settings`
- 进入 `Secrets and variables`
- 点击 `Actions`
- 在 `Repository secrets` 里新增下面这些键

> 当前 workflow 直接读取的是仓库级 `Actions secrets`。  
> 也就是说，对方仓库只要在 `Repository secrets` 里配置即可，不需要额外配置 `Environment secrets`。  
> 只有当他们后续想做更细粒度的权限隔离，才需要再把 workflow 改成绑定某个 environment。

必需：

- `FEISHU_WEBHOOK_URL`
  - 值：飞书群机器人的 webhook 地址
  - 用途：正式发送晨报卡片

建议：

- `OPENAI_API_KEY`
  - 值：模型网关的 API Key
  - 用途：启用大模型结构化翻译、完整摘要、运营意义提炼、动作建议增强

- `OPENAI_BASE_URL`
  - 值：OpenAI 兼容网关地址
  - 示例：`https://your-gateway.example.com`
  - 说明：脚本会自动兼容补全到 `/v1/chat/completions`，不要求你手动写完整接口路径

- `OPENAI_MODEL`
  - 值：模型名
  - 示例：`gpt-4.1`、`gpt-4o-mini` 或你们网关实际暴露的模型名

可选：

- `DEEPL_API_KEY`
  - 值：DeepL API Key
  - 用途：当未启用 LLM 或某些条目未走 LLM 增强时，作为翻译补充

如果未配置 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`：

- workflow 仍然可以跑
- 会尝试生成规则筛选 + 基础翻译的直接翻译版，并明确标注
- 只有基础翻译确认成功且内容通过质量检查，才发送直译版
- 基础翻译也失败时停止正式日报，尝试发送简短失败通知，并让 Actions 标记失败

### 3. 启用工作流

- 工作流文件是 [.github/workflows/daily-report.yml](/Users/mac/Downloads/overseas-trend-radar/.github/workflows/daily-report.yml)
- 当前 workflow 已内置 GitHub `schedule`
- 默认定时是北京时间每天 `09:20`
- 也支持手动点 `Run workflow` 立即试跑
- 如果你更信任外部 cron，也可以继续让外部服务调用 `workflow_dispatch`

### 4. 试运行

- 在 GitHub Actions 页面手动运行一次
- 可选输入 `report_date`
- 建议保留 `skip_if_already_sent = true`
- 勾选 `dry_run = true` 可使用真实信源和已配置的模型、翻译服务生成预览，全程不发送飞书消息（包括失败通知）
- 运行后产物保留 14 天；在 Actions Summary 和 `report-output/run_status.json` 中查看生成模式、失败环节及发送状态

### 5. 外部定时触发

- 推荐用 `cron-job.org` 免费版
- 具体配置见 [EXTERNAL_CRON_SETUP.md](/Users/mac/Downloads/overseas-trend-radar/EXTERNAL_CRON_SETUP.md)

## 发送确认与故障排查

- 正常：发送完整日报，模型参与摘要、精选和运营建议。
- LLM 未配置、请求失败或结果无效：仅在入选新闻的标题与独立摘要都已确认翻译成功时，发送标注“直接翻译版”的日报；不附模板运营建议。
- LLM 与基础翻译均不可用：不发送正式日报，尝试发送一条简短失败通知，包含模型/翻译失败原因与运行链接；即使通知成功，Actions 仍返回失败，且不记录正式日报已发送。
- 飞书：必须收到明确成功的 `code: 0` 或 `StatusCode: 0`。业务拒绝、缺失/冲突状态码、网络超时都不能记录为已发送。
- POST 不自动重试。发送结果为 `unconfirmed` 时，请先核对群里是否已收到，再决定补跑，避免重复发送。
- 新闻、节庆和价格共用 36 条总预算；先为节庆和价格预留位置，再按原有新闻评分保留其余条目，避免各栏目单独合规却在总量检查时整份失败。质量闸门继续保留。
- 已确认当天发送成功时，保留 `skip_if_already_sent = true` 会在抓取前直接跳过。
- 其他抓取、质量检查和程序异常在 Actions 中标记失败；本次不新增通用群告警、自动保活或定时变更。

在运行页面的 Summary，或下载 `report-output` 中的下列文件排查：

| 文件 | 内容 |
| --- | --- |
| `run_status.json` | 报告日期、生成模式、失败环节、模型/翻译失败原因、飞书发送状态 |
| `diagnostics.json` | 抓取、翻译、模型和质量检查的诊断信息 |
| `quality_errors.json` | 内容质量检查失败的具体条件（若有） |
| `last_report.md` / `last_card.json` | 通过生成检查的日报预览和卡片；失败时不会残留上次的日报 |

退出码：`0` 正常/直译版/重复跳过，`1` 程序异常，`2` 缺少飞书配置，`3` 飞书失败或结果未确认，`4` 内容质量检查失败，`5` LLM 与基础翻译均不可用。预览模式也执行生成质量检查，但不发送任何飞书消息、不更新正式发送日期，Actions 也不保存其状态缓存。

本地测试（无第三方 Python 依赖、不调用真实服务、不向群发消息）：

```bash
python3 -m unittest discover -s tests -v
```

## 当前信源

### 头部发行

- Sony Music 官方 feed
- Warner Music Group 官方 press release feed
- Universal Music Group 官方 feed
- Billboard / Rolling Stone / Pitchfork 的发行类内容作为补位信源

### 音乐资讯

- Billboard
- Rolling Stone Music News
- Pitchfork News

### 音乐 / AI 产业

- Music Business Worldwide
- TechCrunch AI
- The Verge AI
- Spotify / Apple Music / Amazon Music 官方价格页

### 节庆

- Nager.Date 公共假期 API

### 社媒热点

- Daily Dot Unclick
- Mashable RSS

### 文化 / 政治

- Variety Film
- ESPN Soccer
- The Hill
- NPR Politics

## 过滤逻辑

- 头部发行：优先三大官方；若主窗口内官方信号过少，则用高相关音乐媒体中的新歌、专辑、MV、预热类内容补位；过滤财报、任命、收购、事故与普通巡演新闻
- 日期窗口：默认抓取“前一自然日”；必要时补充当日 `09:20` 前的重要更新
- 去重：优先按标准化标题去重，后续建议继续扩展为“事件聚类去重”
- AI / 产业：只保留 AI、流媒体、价格、版权、分发、平台相关内容
- 订阅价格：只有官方页面快照发生变化时才提示
- 节庆：按国家抓全年公共假期，默认抓 `25-30 天预警` 和 `5 天内提醒`
- 政策：只做轻量观察，默认最多展示 1-2 条
- 中文摘要：先准备基础翻译，再用模型加工；模型任一环节失败时，恢复未经模型修改的基础翻译版本。翻译未确认成功时停止正式日报，不用中文模板假装翻译成功
- 本地默认仅预览，也会尝试基础翻译；GitHub Actions 正式运行发送日报。两者使用相同的翻译确认与质量检查逻辑
- 若配置 `DEEPL_API_KEY`，GitHub Actions 使用 DeepL；否则使用免费翻译接口。只缓存成功的中文翻译，旧缓存中的失败原文不会被当作成功译文
- 若同时配置 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`，会额外生成更完整的中文标题、运营意义、市场提示和动作建议

## 当前输出结构

晨报固定输出为以下 7 个区块：

1. `【今日三大信号】`
2. `【头部发行】`
3. `【平台 / AI / 产业】`
4. `【社媒趋势】`
5. `【节庆预警】`
6. `【跨界 / 政策观察】`
7. `【今日执行建议】`

## 建议部署方案

### 方案 A：外部 cron + GitHub Actions

- 免费且比 GitHub 原生 `schedule` 更稳
- GitHub 只执行，不负责定时
- 最适合当前版本

### 方案 B：本机 `launchd` 定时

- 成本最低
- 适合只在个人电脑上跑
- 稳定性取决于设备是否在线

### 方案 C：云函数 / 轻量服务器

- 最稳，适合长期团队化
- 成本略高于前两者
- 后续适合加数据库、网页后台、多群推送

## 说明

- 这是一个适合今天上线试运行的 V1 版本
- “民众本地集体事件”目前优先用公共假期覆盖，后续可继续扩展到重点国家新闻源
- 如果你要，我下一步可以继续加：
  - 国家 / 语区维度输出
  - 西语区专项监控
  - 白名单艺人库
  - 飞书多群分发
  - 节庆民众集体行为事件信源
