package com.example.software;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class FeatureController {
    @GetMapping("/api/health")
    public Map<String, Object> health() {
        return Map.of("ok", true, "service", "spring-vue-prototype");
    }

    @GetMapping("/api/features")
    public Map<String, Object> features() {
        return Map.of(
            "goal", "写一个成熟的企业员工管理系统，包含部门、岗位、工资、登录权限和操作审计",
            "features", List.of(
                "Employee CRUD API",
                "Department and position fields",
                "Salary management field",
                "Vue single page client",
                "Static sandbox preview"
                ,
                "Login page and role permission flow",
                "Audit log module"
            )
        );
    }
}
