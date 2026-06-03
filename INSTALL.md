# Agent 安装说明

本文件给 Agent 使用。用户要求安装或初始化 `database-cli` 时，按下面步骤执行。

## 目标

把 `database-cli` 安装后配置好，使 Agent 可以通过本地 CLI 执行只读数据库查询。

## 步骤

1. 如果本地还没有仓库，优先用 GitHub CLI 克隆：

```bash
gh repo clone CassianFlorin/database-cli /Users/huapai/OpenSourceProject/database-cli
cd /Users/huapai/OpenSourceProject/database-cli
```

2. 把 Skill 暴露给 Codex 本地 skills 目录。开发/本机安装可以使用符号链接：

```bash
mkdir -p "$HOME/.codex/skills"
ln -sfn "$PWD/skills/database-cli" "$HOME/.codex/skills/database-cli"
```

3. 在插件根目录运行：

```bash
scripts/install
```

4. 如果提示缺少 `sq`，先询问用户是否允许用 Homebrew 安装。

5. 向用户索取数据库连接信息：

- 环境名，例如 `qa01`、`prod`
- driver，例如 `mysql`
- host 或域名
- 可选端口；如果域名或代理已处理端口，留空
- 可选默认 database/catalog
- 用户名
- 密码或密码环境变量

如果用户提供已有 DBHub TOML 路径，可以优先迁移，不必逐项询问：

```bash
scripts/init-config --from-dbhub-toml /path/to/dbhub.toml --force
```

只迁移某一个环境：

```bash
scripts/init-config --from-dbhub-toml /path/to/dbhub.toml --env qa01 --force
```

6. 生成配置后验证：

```bash
scripts/db-query --list-envs
```

7. 用非生产环境做最小真实连接验证：

```bash
scripts/db-query --env qa01 --sql "SELECT 1"
```

如果只有生产环境可用，只能在用户明确同意后执行 `SELECT 1`。

8. 不要猜测数据库地址、用户名、密码或访问范围。用户未提供时，停止并询问。

## 非交互式示例

如果用户已经提供连接信息，可以直接运行：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-qa01.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

然后验证：

```bash
scripts/db-query --list-envs
```

## DBHub TOML 迁移示例

```bash
scripts/init-config \
  --from-dbhub-toml /Users/huapai/docker_data/dbhub_docker/dbhub.toml \
  --force
scripts/db-query --list-envs
scripts/db-query --env qnvip-qa-01 --sql "SELECT 1"
```

不要把 TOML、DSN 或生成的 `connections.local.json` 内容输出给用户；只汇报环境名和验证结果。

## 安全边界

- 只允许通过 `scripts/db-query` 查询。
- 不执行写 SQL。
- 修数时只输出给人工执行的 SQL。
- 不展示或提交明文密码。
