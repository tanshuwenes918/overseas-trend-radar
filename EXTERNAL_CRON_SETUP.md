# 外部定时触发 GitHub Actions（可选）

[返回 README](README.md)

默认使用仓库内置的 GitHub Actions 定时即可，无需配置外部服务。仅在需要额外的触发来源时考虑本方案；外部触发仍依赖 GitHub Actions 可用，不保证准点执行。

调用方式：`cron-job.org` -> `GitHub workflow_dispatch` -> `GitHub Actions 执行脚本` -> `飞书`

这样做的原因很简单：

- GitHub 自带 `schedule` 事件偶尔会延迟或丢触发
- 外部 cron 可以增加一个独立的定时触发来源
- GitHub Actions 继续负责执行和产物归档

## 你需要准备的 2 个东西

### 1. 一个 GitHub Token

推荐新建一个专门用于触发这个仓库 workflow 的 token，不要直接复用主账号日常 token。

如果你使用 fine-grained token，建议：

- Repository access: 只选 `overseas-trend-radar`
- Permissions:
  - `Actions: Read and write`
  - `Contents: Read`

如果你使用 classic token，通常 `repo` 范围即可。

## 2. 在 cron-job.org 新建一个任务

推荐时间：

- 主任务：每天北京时间 `09:20`
- 兜底任务：每天北京时间 `09:30`

> 兜底任务建议与主任务错开 10 分钟，这样如果主任务偶发失败，补发任务还能接上。

## cron-job.org 填写方式

### URL

```text
https://api.github.com/repos/tanshuwenes918/overseas-trend-radar/actions/workflows/daily-report.yml/dispatches
```

### Method

```text
POST
```

### Headers

```text
Accept: application/vnd.github+json
Authorization: Bearer 你的_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

### Body

```json
{
  "ref": "main",
  "inputs": {
    "skip_if_already_sent": "true"
  }
}
```

说明：

- `ref` 固定填 `main`
- `skip_if_already_sent` 设为 `true`，当状态缓存中已记录该报告日期成功发送时会跳过。缓存缺失或发送结果未确认时仍需人工核对，详见 [补跑与防重复限制](docs/OPERATIONS.md#补跑与防重复限制)

## 如果你想指定某一天补发

把 Body 改成：

```json
{
  "ref": "main",
  "inputs": {
    "report_date": "2026-04-09",
    "skip_if_already_sent": "false"
  }
}
```

## 如何判断 cron 触发成功

成功后，GitHub Actions 页面会出现一条新的 `workflow_dispatch` 运行记录。

也可以在本地查看：

```bash
gh run list --repo tanshuwenes918/overseas-trend-radar --workflow daily-report.yml --limit 10
```

## 当前工作流里的防重复保护

仓库已经做了两层保护：

- `concurrency`：避免多个相同工作流并发挤在一起
- `skip_if_already_sent`：如果当天已经成功发过，就自动跳过

如果选择配置主任务和兜底任务，可使用：

- `09:20` 主任务
- `09:30` 兜底任务

主任务偶发失败时，兜底任务可以再次尝试。主任务成功且状态缓存恢复正常时，兜底任务会跳过。若前次发送结果未确认，自动兜底仍可能重发；无法接受这一重复风险时，只配置一个触发时间，核对群内消息后再手动补跑。
