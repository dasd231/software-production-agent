# API Contract

Base URL: `/api`

## Health

- `GET /health`

## Feature Metadata

- `GET /features`

## Employee CRUD

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/employees` | List employees |
| `POST` | `/employees` | Create employee |
| `PUT` | `/employees/{id}` | Update employee |
| `DELETE` | `/employees/{id}` | Delete employee |

### Employee Payload

```json
{
  "name": "林夏",
  "department": "研发部",
  "position": "后端工程师",
  "salary": 15000,
  "status": "在职"
}
```

## Reference Data

- `GET /reference/departments`
- `GET /reference/positions`
- `GET /reference/payroll-rules`
