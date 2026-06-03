# Database CLI Plugin

这是一个 CLI-first 的 Codex Plugin，内置 `database-cli` Skill。它面向数据库问题排查：查看表结构、搜索 schema/table/column/index/procedure、执行有范围的只读 SQL、跨环境核对记录，以及在需要修数时产出给人工执行的 SQL。

底层使用 [`sq`](https://sq.io/) 作为数据库 CLI 后端，并通过本项目的 wrapper 做安全限制。`scripts/db-query` 是唯一真实查询入口；`scripts/database-mcp` 是可选的薄适配层，只把同一套 CLI 能力暴露给支持 MCP 的客户端。

## 核心理念

`database-cli` 不是 DBHub 替代品，也不是 MCP 平台。它的核心是一个可安装、可审计、可由 Agent 和人类共同使用的数据库 CLI Skill。

项目边界：

- CLI 是产品本体：安装、配置、schema 搜索、只读查询、安全校验和修数 SQL 工作流都先落在 `scripts/db-query` 和 Skill 指令中。
- MCP 是适配层：`scripts/database-mcp` 不能另起查询逻辑，只能委托 CLI；安全规则必须由 CLI 层兜底。
- Skill 是使用规范：Agent 应按 `SKILL.md` 先确认环境、读取真实 schema、执行有界只读查询，需要改数据时只输出人工执行 SQL。
- 不追求 DBHub 平台能力：不做 Workbench、权限平台、多租户服务端或独立数据库管理产品。

## 能力范围

- 通过 `scripts/db-query` 执行只读 SQL，这是唯一真实查询入口。
- 通过 `SKILL.md` 固化 Agent 查询流程、安全边界和人工修数 SQL 输出规范。
- 通过 `scripts/database-mcp` 可选暴露 stdio MCP 工具；它只委托 `scripts/db-query`，不拥有独立查询逻辑。
- 通过本地 `connections.local.json` 保存连接配置。
- 按环境名管理连接，例如 `qa01`、`prod`，让 Agent 和开发者使用同一套入口。
- 默认按数据库实例/服务端连接，不把配置限制到某个 database/schema。
- 支持只配置域名，不配置端口；适用于域名或反向代理已处理端口的场景。
- 支持对象搜索：schema、table、column、index、procedure/function metadata，并支持 `names`、`summary`、`full` 三档详情。
- 支持配置级 `max_rows` 上限；`readonly=false` 会被拒绝，不会打开写权限。
- 拦截常见写入、DDL、权限、事务、过程、锁、导出和副作用 SQL。
- 避免把密码写入命令行 DSN；本地密钥文件不提交到仓库。

## 目录结构

```text
.
├── .codex-plugin/
│   └── plugin.json
├── INSTALL.md
├── README.md
├── skills/
│   └── database-cli/
│       ├── SKILL.md
│       ├── agents/openai.yaml
│       ├── references/
│       │   ├── config.example.json
│       │   └── config.md
│       └── scripts/
│           ├── database-mcp
│           ├── db-query
│           ├── install
│           └── init-config
└── scripts/
    ├── database-mcp
    ├── db-query
    ├── install
    └── init-config
```

## 安装并初始化

安装或复制这个 Plugin 后，在插件根目录运行安装入口：

```bash
scripts/install
```

这个命令会：

1. 检查本机是否已安装 `sq`。
2. 如果没有 `sq`，询问是否通过 Homebrew 安装。
3. 向用户收集数据库连接信息。
4. 生成本地 `connections.local.json`。

标准 Codex Plugin/Skill 安装机制不会自动执行任意 post-install hook。因此，`scripts/install` 是这个插件的安装后必跑配置入口。

## 从已有查询习惯迁移

如果你已经知道常用环境名和连接信息，不需要先理解 `sq` 的 source 管理方式，直接用 `scripts/init-config` 创建本地环境即可：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-qa01.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
scripts/db-query --list-envs
scripts/db-query --env qa01 --sql "SELECT 1"
```

建议保留你原来习惯的环境名，并在 SQL 里写全限定表名。这样 Agent 可以稳定复用同一套命令形态：

```bash
scripts/db-query --env qa01 --sql "SELECT id FROM qnvip_center_commerce.cc_order WHERE order_no = 'YP...'"
```

## 对象搜索

如果只知道表名、字段名或索引名的一部分，可以直接查 metadata，不必先手写 information_schema SQL：

```bash
scripts/db-query --env qa01 --search-objects "%cc_order%" --object-type table
scripts/db-query --env qa01 --search-objects "%order_no%" --object-type column --table cc_order
scripts/db-query --env qa01 --search-objects "%idx_order%" --object-type index --table cc_order
scripts/db-query --env qa01 --search-objects "%sync_order%" --object-type procedure
scripts/db-query --env qa01 --search-objects "%calc%" --object-type function --detail-level full
```

`--detail-level` 支持：

- `names`：只返回对象定位字段。
- `summary`：返回常用排查字段，默认值。
- `full`：返回更完整的 metadata，例如 MySQL routine definition、table comment、index detail 等。

当前对象搜索支持 MySQL/MariaDB/Postgres 直连配置。其他数据库或高级 `sq source` 配置仍可使用：

```bash
scripts/db-query --env qa01 --inspect
scripts/db-query --env qa01 --inspect cc_order
```

## 可选 MCP 适配层

`scripts/database-mcp` 是一个无额外 Python 依赖的 stdio MCP adapter。它不是独立产品入口，实际查询、校验、限流和连接配置仍全部复用 `scripts/db-query`。它提供：

- `list_envs`：列出当前配置的环境。
- `query_readonly`：执行只读 SQL。
- `inspect`：查看 source 或表结构。
- `search_objects`：搜索 schema/table/column/index/procedure/function metadata。
- `check_sql`：只校验 SQL 安全性，不执行。

每次 `tools/call` 都保留文本 `content`，并额外返回 `structuredContent`，包含 `exit_code`、`stdout`、`stderr`，以及 stdout 可解析为 JSON 时的 `json` 字段。

如果 `connections.local.json` 配置了 top-level `tools`，MCP `tools/list` 会额外暴露这些参数化工具。custom tool 是 MCP 适配层的辅助能力，不是项目主线。它的 SQL 使用 `:param_name` 占位，调用时会先把参数渲染为 SQL literal，再交给 `scripts/db-query` 做只读校验和 `max_rows` 限制。

```json
{
  "environments": {
    "qa01": {
      "driver": "mysql",
      "host": "mysql-qa01.example.internal",
      "username": "readonly_user",
      "password_env": "QA01_DB_PASSWORD",
      "max_rows": 100
    }
  },
  "tools": {
    "find_order": {
      "description": "Find one order by order number.",
      "env": "qa01",
      "sql": "SELECT id, order_no, status FROM cc_order WHERE order_no = :order_no",
      "parameters": {
        "order_no": {
          "type": "string",
          "description": "Order number."
        }
      }
    }
  }
}
```

MCP 客户端如需结构化工具入口，可以把 command 指到插件根目录下的入口：

```bash
/Users/huapai/OpenSourceProject/database-cli/scripts/database-mcp
```

也可以在安装到任意目录后使用对应的绝对路径。连接配置仍由 `connections.local.json` 或 `DATABASE_CLI_CONFIG` 控制。

## 通过 Agent 安装和修改配置

用户可以直接让 Agent 代为安装和初始化。推荐把下面这段发给 Agent：

```text
请使用 GitHub CLI 安装 database-cli：
1. 如果本地没有仓库，运行 gh repo clone CassianFlorin/database-cli /Users/huapai/OpenSourceProject/database-cli。
2. 进入 /Users/huapai/OpenSourceProject/database-cli。
3. 把 skills/database-cli 安装到 ~/.codex/skills/database-cli（可用符号链接）。
4. 运行 scripts/install，帮我完成 database-cli 的安装后配置。
如果缺少 sq，请先询问我是否允许用 Homebrew 安装。
数据库连接信息由我提供，不要猜测地址、用户名、密码或访问范围。
```

如果已经知道连接信息，也可以让 Agent 走非交互式配置：

```text
请为 database-cli 创建 qa01 环境配置：
driver=mysql
host=mysql-qa01.example.internal
port 留空
username=readonly_user
password 使用环境变量 QA01_DB_PASSWORD
然后运行 scripts/db-query --list-envs 验证配置已写入。
```

Agent 实际会执行类似命令：

```bash
gh repo clone CassianFlorin/database-cli /Users/huapai/OpenSourceProject/database-cli
cd /Users/huapai/OpenSourceProject/database-cli
ln -sfn "$PWD/skills/database-cli" "$HOME/.codex/skills/database-cli"
scripts/install
```

或非交互式创建配置：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-qa01.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

也可以更新已有环境：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-new.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --force
```

边界如下：

- Agent 可以运行 `scripts/install`、`scripts/init-config`、`scripts/db-query`。
- Agent 可以根据用户提供的信息创建或更新 `connections.local.json`。
- Agent 可以帮用户检查 `sq` 是否安装，并在用户允许时通过 Homebrew 安装。
- Agent 不会也不应该猜测数据库地址、用户名、密码或访问范围。
- 敏感密码优先由用户配置到环境变量，然后在配置中使用 `password_env`。
- 如果用户直接提供明文密码，Agent 只能写入本地且被 git 忽略的 `connections.local.json`，不应提交或展示。
- custom tools 只适合固化只读查询模板；不要把修数 SQL 写进配置。

## Codex 插件 Manifest

插件入口位于：

```text
.codex-plugin/plugin.json
```

它声明：

- 插件名：`database-cli`
- Skill 目录：`./skills/`
- UI 名称：`Database CLI`
- 能力：`Read`、`Write`、`Interactive`

这与 Superpowers 的插件化思路一致：插件安装负责把 Skill 暴露给 Codex，安装后的敏感连接配置由 `scripts/install` 向用户收集。

## 依赖

真实查询前需要安装 `sq`：

```bash
brew install sq
```

检查是否可用：

```bash
command -v sq
```

## 初始化数据库连接

如果只想创建或更新数据库配置，可以直接运行：

```bash
scripts/init-config
```

它会询问：

- 环境名，例如 `qa01`、`prod`
- 数据库类型，例如 `mysql`
- host 或域名
- 可选端口
- 可选默认 database/catalog
- 用户名
- 密码或密码环境变量

默认生成的配置路径是：

```text
skills/database-cli/connections.local.json
```

文件权限是 `0600`，并且已被 `.gitignore` 忽略。

非交互式示例：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-qa01.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

如果必须显式指定端口：

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql.example.internal \
  --port 3306 \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

## 配置示例

域名或代理已经处理端口时：

```json
{
  "environments": {
    "qa01": {
      "driver": "mysql",
      "host": "mysql-qa01.example.internal",
      "username": "readonly_user",
      "password_env": "QA01_DB_PASSWORD",
      "max_rows": 200,
      "limit_style": "limit"
    }
  }
}
```

显式端口：

```json
{
  "environments": {
    "qa01": {
      "driver": "mysql",
      "host": "mysql.example.internal",
      "port": 3306,
      "username": "readonly_user",
      "password_env": "QA01_DB_PASSWORD",
      "limit_style": "limit"
    }
  }
}
```

`database` 和 `schema` 都是可选默认值，不是访问范围限制。用户要查哪个库，优先在 SQL 里写全限定名：

```sql
SELECT id, order_no
FROM qnvip_center_commerce.cc_order
WHERE order_no = 'YP...'
```

对于支持三段式名称的数据库：

```sql
SELECT column_name
FROM dbname.schema_name.table_name
WHERE id = 1
```

## 查询用法

列出已配置环境：

```bash
scripts/db-query --list-envs
```

执行只读查询：

```bash
scripts/db-query --env qa01 --sql "SELECT id FROM qnvip_center_commerce.cc_order WHERE order_no = 'YP...'"
```

预览将要执行的 `sq` 命令，不真正查询数据库：

```bash
scripts/db-query --env qa01 --sql "SELECT 1" --print-command
```

查看数据源元信息：

```bash
scripts/db-query --env qa01 --inspect
```

查看表元信息：

```bash
scripts/db-query --env qa01 --inspect qnvip_center_commerce.cc_order
```

使用指定配置文件：

```bash
DATABASE_CLI_CONFIG=/path/to/connections.json scripts/db-query --list-envs
```

只校验 SQL，不执行：

```bash
scripts/db-query --check-sql "SELECT * FROM qnvip_center_commerce.cc_order WHERE order_no = 'YP...'"
```

## 安全规则

允许的起始关键字：

- `SELECT`
- `SHOW`
- `DESC`
- `DESCRIBE`
- `EXPLAIN`
- 只读的 `WITH ... SELECT`

会被拦截的示例：

- `INSERT`、`UPDATE`、`DELETE`、`REPLACE`、`MERGE`
- `CREATE`、`ALTER`、`DROP`、`TRUNCATE`
- `GRANT`、`REVOKE`
- `BEGIN`、`COMMIT`、`ROLLBACK`
- `CALL`、`EXEC`、`EXECUTE`
- `LOCK`、`UNLOCK`
- `SELECT ... FOR UPDATE`
- 具有副作用或风险的函数，例如 `nextval`、`setval`、`get_lock`、`sleep`、`pg_sleep`、`benchmark`、`dblink_exec`

`SELECT` 和 `WITH` 查询会自动补 `LIMIT 200`，除非 SQL 已经包含 limit，或显式使用 `--no-auto-limit`。

配置了 `max_rows` 时，它是硬上限；用户传入更大的 `--limit` 或 SQL 里已有更大的 `LIMIT`，都会被压到 `max_rows`。`readonly=false` 不会启用写 SQL，database-cli 会直接拒绝该配置。

## 密码处理

推荐使用环境变量保存密码：

```bash
export QA01_DB_PASSWORD='...'
```

配置里写：

```json
{
  "password_env": "QA01_DB_PASSWORD"
}
```

如果直接把 `password` 写进 `connections.local.json`，必须只保存在本地。Wrapper 会通过 `sq add --password` 的 stdin 传递密码，不会把密码放进命令行 DSN。

## 支持的 Driver

直连配置支持：

- `mysql`
- `mariadb`
- `postgres`
- `postgresql`
- `sqlite3`
- `duckdb`
- `sqlserver`
- `clickhouse`

其他 `sq` source 类型可以使用高级 handle 配置：

```json
{
  "sq_config": "/Users/me/.config/sq/sq.yml",
  "environments": {
    "qa01": {
      "source": "@qnvip_qa01_commerce"
    }
  }
}
```

## 修数 SQL 流程

不要通过这个 Skill 执行任何写 SQL。需要修数时，只输出给人工执行的 SQL，并包含：

- 目标环境
- 执行前 `SELECT` 校验
- 变更 SQL
- 执行后 `SELECT` 验证
- 回滚或恢复方案

## 验证

基础脚本校验：

```bash
python3 -m py_compile scripts/db-query scripts/init-config scripts/install
```

当环境里有 `PyYAML` 时，执行 Skill 校验：

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py /path/to/database-cli
```
