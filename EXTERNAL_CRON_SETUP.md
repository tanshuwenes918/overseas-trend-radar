# 外部定时触发 GitHub Actions

推荐方案：`cron-job.org` -> `GitHub workflow_dispatch` -> `GitHub Actions 执行脚本` -> `飞书`

这样做的原因很简单：

- GitHub 自带 `schedule` 事件偶尔会延迟或丢触发
- 外部 cron 更适合做“准点叫醒”
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
- `skip_if_already_sent` 设为 `true`，这样就算主任务和兜底任务都打到了，也只会发一次

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

所以推荐保留两个外部任务：

- `09:20` 主任务
- `09:30` 兜底任务

这样即使主任务偶发失败，兜底任务还能接上；如果主任务成功，兜底任务会自动跳过，不会双发。
