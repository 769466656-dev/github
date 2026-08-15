# 数据库管理

## 内容边界

- `schema/` 保存可从空库创建表结构的 SQL。
- `migrations/` 保存按日期命名、只新增不覆盖的结构变更。
- `seeds/` 只允许保存小型、脱敏、教学用途的数据样本。
- 真实数据库、完整行情数据和数据库备份均不进入 Git；请保存到加密硬盘或私有云。

## 初始化

在目标 MySQL 数据库中执行：

```bash
mysql -u <用户名> -p <数据库名> < database/schema/wucai_trade.sql
mysql -u <用户名> -p <数据库名> < database/migrations/20260815_add_report_consensus_net_profit.sql
```

在运行案例前，把其 `.env.example` 复制为 `.env` 并填写本机连接信息。不要提交 `.env`。

## 新增迁移

每次更改表结构，新建 `database/migrations/YYYYMMDD_说明.sql`，不要修改已执行过的迁移文件；同时更新 `docs/data-dictionary.md`。

## 备份

完整备份仅在本机或加密存储中创建，例如：

```bash
mysqldump -u <用户名> -p <数据库名> | gzip > backups/<数据库名>-YYYYMMDD.sql.gz
```

`backups/` 和压缩 SQL 备份已被 Git 忽略。
