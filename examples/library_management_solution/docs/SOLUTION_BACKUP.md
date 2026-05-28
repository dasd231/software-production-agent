# Solution Backup: Library Management System

## 1. Domain model

Core entities:

- Book
- BookCopy
- Reader
- BorrowOrder
- Reservation
- FineBill
- OperatorLog
- Role / Permission

Key relationships:

- One Book has many BookCopy records.
- Reader creates BorrowOrder and Reservation.
- BorrowOrder drives BookCopy status changes.
- FineBill is generated from overdue BorrowOrder.
- OperatorLog records all sensitive actions.

## 2. Workflow

Borrow lifecycle:

```text
available -> borrowed -> returned
available -> reserved -> borrowed
borrowed -> overdue -> returned_with_fine
```

Controls:

- Reader borrow limit must be checked before creating an order.
- BookCopy stock must be locked or rechecked to avoid duplicate borrow.
- Return operation must be idempotent by `borrow_order_id + operation_type`.
- Fine adjustment must require manager permission and audit reason.

## 3. API design

- `GET /api/books` list and search books.
- `POST /api/books` create book.
- `GET /api/readers` list readers.
- `POST /api/borrow-orders` borrow a copy.
- `POST /api/borrow-orders/{id}/return` return and calculate fine.
- `POST /api/reservations` reserve book.
- `GET /api/dashboard/summary` overview metrics.
- `GET /api/operator-logs` audit trail.

## 4. Risks and tests

Risks:

- Duplicate borrow under concurrent click.
- Overdue fine calculated twice.
- Unauthorized fine exemption.
- Deleted book still has active borrow order.

Tests:

- Borrow succeeds only when stock is available.
- Return is idempotent.
- Overdue fine is generated once.
- Manager-only fine exemption is enforced.
- Audit log is written for borrow, return, exemption and delete.
