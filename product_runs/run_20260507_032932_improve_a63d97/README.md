# Spring Boot + Vue Personnel Management System

Goal:

```text
写一个成熟的 Spring Boot + Vue 人员管理系统，包含员工 CRUD、部门岗位、工资、API 契约、数据库设计、测试、交付清单和静态预览。本次是 
```

This run was completed by Codex handoff execution after the local product shell created
`CODEX_TASK.md`. It turns the incomplete handoff package into a mature, inspectable
Spring Boot + Vue personnel management vertical slice.

## Product Scope

- Employee CRUD: create, list, update and delete staff records.
- Organization reference data: departments, positions and payroll rules.
- Frontend API wrapper with local fallback when the backend is not running.
- Static sandbox preview for product review without executing build scripts.
- Delivery docs: product spec, API contract, database schema and checklist.



## Backend

```bash
cd backend
mvn spring-boot:run
```

Endpoints:

- `GET /api/health`
- `GET /api/features`
- `GET /api/employees`
- `POST /api/employees`
- `PUT /api/employees/{id}`
- `DELETE /api/employees/{id}`
- `GET /api/reference/departments`
- `GET /api/reference/positions`
- `GET /api/reference/payroll-rules`



## Verify

```bash
cd backend
mvn test
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```
