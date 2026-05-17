# Database Schema Draft

当前模板使用内存数据，下面是落库建议，可直接迁移到 MySQL/PostgreSQL/H2。

## employees

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint primary key | 员工 ID |
| name | varchar(64) | 姓名 |
| department_id | bigint | FK -> departments.id |
| position_id | bigint | FK -> positions.id |
| salary | decimal(12,2) | 月薪 |
| status | varchar(24) | 在职/试用/待调岗/离职 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

## departments

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint primary key | 部门 ID |
| name | varchar(64) | 部门名称 |
| owner | varchar(64) | 部门负责人 |

## positions

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint primary key | 岗位 ID |
| name | varchar(64) | 岗位名称 |
| level | varchar(16) | 职级 |
| salary_min | decimal(12,2) | 薪资下限 |
| salary_max | decimal(12,2) | 薪资上限 |

## audit_logs

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint primary key | 日志 ID |
| actor | varchar(64) | 操作人 |
| action | varchar(64) | 操作类型 |
| target_type | varchar(64) | 目标类型 |
| target_id | bigint | 目标 ID |
| payload | json/text | 变更摘要 |
| created_at | timestamp | 操作时间 |
