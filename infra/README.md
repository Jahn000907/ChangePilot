# ChangePilot 基础设施

本目录保存基础设施配置。

后续包括：

- Docker
- Neo4j Schema
- 数据库初始化相关文件

数据库容器定义位于项目根目录 `docker-compose.yml`，包含 PostgreSQL 与 Neo4j Community 两个服务。

数据库 Schema、Migration 与 Seed 数据尚未实现。

## 启动数据库

在项目根目录执行（首次运行前先从 `.env.example` 复制出 `.env`，并填写数据库密码）：

```bash
docker compose up -d
```

## 停止数据库

```bash
docker compose down
```

## 查看容器状态

```bash
docker compose ps
```

## 查看日志

```bash
docker compose logs -f postgres
docker compose logs -f neo4j
```
