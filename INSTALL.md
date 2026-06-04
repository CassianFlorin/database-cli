# Agent 安装说明

本文件给 Agent 使用。用户要求安装或初始化 `database-cli` 时，按下面步骤执行。

## 目标

把 `database-cli` 安装后配置好，使 Agent 和人类可以通过本地 CLI 执行只读数据库查询、schema 搜索和人工修数 SQL 准备。stdio MCP server 只是可选适配层。

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

3. 在插件根目录运行安装入口。没有连接参数时它会交互式询问：

```bash
scripts/install
```

如果用户已经给出连接信息，优先一条命令完成依赖检查和配置写入：

```bash
scripts/install \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal" \
  --display-name "QNVIP QA01" \
  --environment qa01 \
  --project qnvip \
  --description "QA01 shared readonly connection; search all visible schemas unless narrowed." \
  --alias qa-01 \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --non-interactive
```

如需写到指定配置文件，加 `--config /path/to/connections.local.json`。如需覆盖已有环境，加 `--force`。

4. 如果提示缺少 `sq`，先询问用户是否允许用 Homebrew 安装。

5. 向用户索取数据库连接信息：

- 连接链接或 host/domain，例如 `mysql://mysql-qa01.example.internal:3306/dbname`
- 环境名，例如 `qa01`、`prod`
- 展示名，例如 `QNVIP QA01`
- 环境标签，例如 `qa01`、`prod`、`staging`
- 项目或业务域，例如 `qnvip`
- 用途说明，例如“QA01 共享只读连接，默认搜索账号可见库”
- 可选别名，例如 `qa-01`
- driver，例如 `mysql`
- host 或域名
- 可选端口；如果域名或代理已处理端口，留空
- 可选默认 database/catalog；通常留空，不要为了每个 database 创建一个连接
- 用户名
- 密码或密码环境变量

如果用户只给了部分信息，继续向用户询问缺失项。不要猜测连接链接、用户名、密码或访问范围。

6. 生成配置后验证：

```bash
scripts/db-query --list-envs
```

7. 用非生产环境做最小真实连接验证：

```bash
scripts/db-query --env qa01 --sql "SELECT 1"
```

如果只有生产环境可用，只能在用户明确同意后执行 `SELECT 1`。

8. 如果用户或客户端需要 MCP 工具入口，再验证 MCP adapter 可启动：

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n' | scripts/database-mcp
```

9. 不要猜测数据库地址、用户名、密码或访问范围。用户未提供时，停止并询问。

## 非交互式示例

如果用户已经提供连接信息，可以直接运行 `scripts/install`。它会检查 `sq` 并把连接参数透传给 `scripts/init-config`：

```bash
scripts/install \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal" \
  --display-name "QNVIP QA01" \
  --environment qa01 \
  --project qnvip \
  --description "QA01 shared readonly connection; search all visible schemas unless narrowed." \
  --alias qa-01 \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --non-interactive
```

然后验证：

```bash
scripts/db-query --list-envs
```

## 安全边界

- 只允许通过 `scripts/db-query` 查询；这是唯一真实执行入口。
- 需要 Agent 结构化工具入口时，使用 `scripts/database-mcp`；它只是适配层，仍然委托 `scripts/db-query` 执行实际查询。
- 运行中的 Agent 需要新增连接时，优先调用 MCP `add_connection` 工具；调用成功后无需重启 Agent，后续工具调用会读取新配置。
- 不执行写 SQL。
- 修数时只输出给人工执行的 SQL。
- 不展示或提交明文密码。
