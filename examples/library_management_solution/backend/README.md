# Backend Notes

Recommended backend stack: Spring Boot + MySQL + Redis.

Production notes:

- Use optimistic locking on book stock updates.
- Use idempotency key for return and fine adjustment.
- Protect manager-only APIs with RBAC.
- Write operator log before returning success on sensitive operations.
