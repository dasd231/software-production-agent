package com.example.software;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody LoginPayload payload) {
        String username = payload.username() == null ? "" : payload.username().trim();
        String password = payload.password() == null ? "" : payload.password().trim();
        if (!"admin".equals(username) || !"admin123".equals(password)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid username or password");
        }
        return Map.of(
            "ok", true,
            "token", "demo-admin-token",
            "user", Map.of(
                "username", "admin",
                "name", "系统管理员",
                "role", "HR_ADMIN",
                "permissions", new String[] {"employee:read", "employee:write", "payroll:read", "audit:read"}
            )
        );
    }

    @GetMapping("/me")
    public Map<String, Object> me() {
        return Map.of(
            "username", "admin",
            "name", "系统管理员",
            "role", "HR_ADMIN",
            "permissions", new String[] {"employee:read", "employee:write", "payroll:read", "audit:read"}
        );
    }

    @PostMapping("/logout")
    public Map<String, Object> logout() {
        return Map.of("ok", true);
    }

    public record LoginPayload(String username, String password) {}
}
