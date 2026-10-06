# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护中央厨房出品与用料树。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 打开「备料工作台」生成备料单：按需求占用库存（需求 = 数量 = 占用）。
4. 手改某一行：行内改或行上弹层保存同一口径——数量与占用在一个事务里同改同停；改后数量超过该行需求上限（或为负）则整单失败退回、占用不动。
5. 已作废的单不能再手改；重新生成会把更早的可改单整体存档（存档单只读，旧快照不改字）；作废/存档时释放占用。
6. 在「缺料」查看 need − stock 为正的原料；「库存」可看占用与可用量（库存 − 占用）。

## 开发与测试

```bash
docker compose exec api pytest -q
```
