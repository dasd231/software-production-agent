package com.example.software;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/audit")
public class AuditController {
    @GetMapping("/logs")
    public List<Map<String, Object>> logs() {
        return List.of(
            Map.of("actor", "admin", "action", "LOGIN", "target", "auth", "time", "2026-05-07 09:00"),
            Map.of("actor", "admin", "action", "UPDATE_EMPLOYEE", "target", "employee#1", "time", "2026-05-07 09:06"),
            Map.of("actor", "admin", "action", "APPROVE_WORKFLOW", "target", "approval#2", "time", "2026-05-07 09:12")
        );
    }
}
