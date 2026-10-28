# 海外舆情飞书雷达

每天从固定的海外新闻订阅源抓取内容，筛选、翻译并生成中文日报，通过飞书群机器人发送。面向音乐与内容运营，使用 GitHub Actions 定时执行，无第三方 Python 包依赖。

日报按有内容的栏目展示：**头部发行、AI·产业动向、社媒热点、文化·艺术界、国际政坛、节庆预警、运营建议**。新闻条目展示标题、摘要和信源名；原文链接保存在运行产物中。

## 日常使用

默认使用 GitHub Actions，无需保持个人电脑开机。

打开 [Actions → Overseas Trend Radar](https://github.com/tanshuwenes918/overseas-trend-radar/actions/workflows/daily-report.yml)，点击 **Run workflow**，分支选择 `main`：

| 你要做什么 | `dry_run` | `skip_if_already_sent` |
| --- | --- | --- |
| 只预览，不发群消息 | `true` | 保持默认 |
| 正式发送，当天发过就跳过 | `false` | `true`（默认） |
| 确认需要重新发送，即使当天已发过 | `false` | `false` |

`report_date` 留空表示今天；指定日期时填写 `YYYY-MM-DD`。指定过去的日期只会从当前可取得的信源内容中筛选，不保证能恢复历史日报。

预览也会访问真实信源、翻译和已配置的模型接口，但不会发送任何飞书消息，包括失败通知。它不更新正式发送日期，工作流也不保存预览的状态缓存。

运行结束后，先看页面的 **Summary**；需要看完整预览时，在 **Artifacts → report-output** 下载 `last_report.md`。产物保留 **14 天**。

## 运行结果怎么看

| 情况 | 日报与群消息 | Actions 结果 |
| --- | --- | --- |
| 模型加工、内容检查、飞书回执均正常 | 发送完整日报 | 成功 |
| 模型未配置、调用失败或结果无效；入选新闻的基础翻译可用 | 发送标注“直接翻译版”的日报，不附运营建议 | 成功，Summary 说明降级原因 |
| 模型不可用，且有入选新闻的基础翻译未成功 | 停止正式日报，尝试发送简短失败通知 | 失败；通知成功也不算日报成功 |
| 飞书拒绝消息，或发送结果无法确认 | 不记录为已发送 | 失败 |
| 内容质量检查或程序运行失败 | 停止正式日报 | 失败 |
| 状态中已确认该报告日期发送成功，且开启了跳过重复发送 | 跳过本次抓取与发送 | 成功，状态为 `already_sent` |

飞书必须返回明确成功的业务状态码，程序才记录发送日期。**发送超时或回执不明时，先核对群内消息再补跑**：消息可能已送达，只是回执未收到。程序不会自动重试消息发送。

详细状态、错误码和补跑说明见 [运行与排错](docs/OPERATIONS.md)。

## 首次部署

1. 将本项目放入自己的 GitHub 仓库。
2. 在 **Settings → Secrets and variables → Actions → Repository secrets** 配置下表中的密钥。当前工作流直接读取仓库级 Secrets。
3. 在 Actions 中启用 **Overseas Trend Radar**，先预览，再正式发送一次。

| Secret | 是否需要 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | 正式发送必需 | 飞书群机器人的 webhook 地址 |
| `OPENAI_API_KEY` | 完整日报需要 | 模型接口密钥 |
| `OPENAI_BASE_URL` | 完整日报需要 | OpenAI 兼容的 Chat Completions 接口地址 |
| `OPENAI_MODEL` | 完整日报需要 | 服务商实际支持的模型名 |
| `DEEPL_API_KEY` | 可选 | 基础翻译使用 DeepL；未配置时使用 Google 非官方翻译接口 |

模型配置三项需要同时填写。`OPENAI_BASE_URL` 支持服务根地址、以 `/v1` 结尾的地址，或完整的 `/chat/completions` 地址；程序会补全相应路径。模型服务需支持当前请求使用的 JSON 输出格式。

模型未配置时仍可尝试生成直接翻译版，发送条件见上表。不要将密钥写入代码或提交到仓库。

## 日报如何生成

1. **抓取信源。** 从代码配置的新闻 RSS 获取标题、摘要、时间和链接，再尝试提取网页文字补充摘要。另行获取公共假期和订阅价格快照。
2. **规则筛选。** 按时间窗口、栏目关键词、排除词、相关性和新鲜度评分，清理重复标题，各新闻栏目最多保留 6 条候选。
3. **基础翻译。** 翻译标题与独立摘要，只缓存确认成功的中文译文。
4. **模型加工。** 根据已有材料改写中文标题与摘要、精选归类，并生成运营建议。模型不会自行联网扩展信源；任一模型环节失败时，改用独立保存的基础翻译结果。
5. **总量与质量检查。** 新闻、节庆、价格信息合计最多 36 条；先为节庆和价格预留位置，再按原有新闻评分保留其余条目。检查总量、信源及部分栏目的相关性等条件。
6. **发送与保存。** 生成飞书卡片，确认成功回执后记录报告日期；保存翻译、模型和价格缓存及审计文件。

### 时间口径

- 定时表达式为 `20 1 * * *`，计划在**北京时间每天 09:20**触发。GitHub 调度可能延迟，不保证准点送达。
- 报告默认包含**前一自然日全天，以及报告当天 09:20 及之前**发布的合格新闻。即使任务下午运行，截止时间也不随启动时间后移。
- 节庆展示当天、未来 7 天内，以及提前 25–35 天的提醒，并按代码中的节庆条件筛选。
- 价格观察覆盖 Spotify、Apple Music、Amazon Music 的美国官方页面。首次建立快照；之后识别到价格结构变化时加入日报。

### 信源范围

| 类别 | 代表信源 |
| --- | --- |
| 头部发行 | Sony Music、Warner Music Group、Universal Music Group、Billboard、Pitchfork、NME |
| AI／产业 | Music Business Worldwide、TechCrunch AI、The Verge AI |
| 社媒热点 | Daily Dot、Mashable、Reddit、Know Your Meme、TMZ |
| 文化艺术 | Variety、Deadline、The Hollywood Reporter、The Guardian |
| 国际政坛 | The Hill、NPR、BBC、The Guardian 等 |
| 节庆 | Nager.Date 公共假期 API |

完整列表以 [main.py](main.py) 中的 `FEED_SOURCES`、`HOLIDAY_COUNTRIES` 和 `PRICE_TRACKERS` 为准。信源可用性和 RSS 保留范围会影响当日覆盖；社媒栏目主要依赖报道和订阅源，并非各平台实时热榜的完整监控。

## 本地运行

建议使用 **Python 3.12**，与 Actions 保持一致。无需 `pip install`；部分网络请求失败后的备用路径会调用系统 `curl`。

在仓库目录中预览：

```bash
python3 main.py --dry-run --debug
```

如需模型加工，先在本地环境中配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`。GitHub Secrets 不会自动同步到本机，程序也不会自动读取 `.env` 文件。

正式发送前设置 `FEISHU_WEBHOOK_URL`，然后运行：

```bash
python3 main.py --send --skip-if-already-sent
```

指定报告日期可加 `--date YYYY-MM-DD`；不传 `--send` 或 `--dry-run` 时默认预览。本地预览会更新本地缓存和诊断文件，但不更新正式发送日期。

运行不调用外部服务的测试：

```bash
python3 -m unittest discover -s tests -v
```

## 维护入口

| 文件 | 用途 |
| --- | --- |
| [main.py](main.py) | 信源、筛选规则、翻译、模型加工和飞书发送 |
| [daily-report.yml](.github/workflows/daily-report.yml) | 定时／手动运行、状态缓存和产物归档 |
| [tests/](tests/) | 发送确认、模型降级、翻译及质量检查测试 |
| [运行与排错](docs/OPERATIONS.md) | 状态字段、诊断文件、失败处理和补跑 |
| [外部定时触发](EXTERNAL_CRON_SETUP.md) | 可选方案；默认运行无需配置 |

`data/state.json` 保存价格、翻译、模型缓存和最近一次成功发送记录。Actions 通过缓存恢复它；防重复发送依赖该状态，缓存缺失时无法确认是否已发送。更多限制见排错文档。
