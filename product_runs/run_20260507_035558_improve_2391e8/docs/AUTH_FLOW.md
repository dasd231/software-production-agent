# Auth And Permission Flow

## Demo Account

- Username: `admin`
- Password: `admin123`
- Role: `HR_ADMIN`

## Generated Flow

1. User lands on the login page.
2. Frontend calls `POST /api/auth/login`.
3. Backend returns a demo token, user profile, role and permission list.
4. Frontend enters the personnel management workspace.
5. `POST /api/auth/logout` returns the UI to login state.

## Permission Scope

- `employee:read`
- `employee:write`
- `payroll:read`
- `audit:read`

## Production Upgrade

- Replace demo token with JWT or server session.
- Store users, roles and permissions in database tables.
- Add route guards and backend permission interceptors.
- Write auth audit logs for login, logout and permission changes.
