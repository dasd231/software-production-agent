# Approval Workflow

## Scope

- Salary adjustment approval
- Position transfer approval
- New employee onboarding approval

## API

- `GET /api/workflows/approvals`
- `POST /api/workflows/approvals/{id}/approve`

## Product Notes

The current implementation is an in-memory workflow demo. Production upgrades should add approver assignment, status history, comments and audit linkage.
