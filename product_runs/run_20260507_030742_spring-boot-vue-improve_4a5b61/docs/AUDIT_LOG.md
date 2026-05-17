# Audit Log

## Scope

- Login audit
- Employee update audit
- Workflow approval audit

## API

- `GET /api/audit/logs`

## Product Notes

Production upgrades should store immutable audit records and correlate them with users, roles, request IDs and changed payload snapshots.
