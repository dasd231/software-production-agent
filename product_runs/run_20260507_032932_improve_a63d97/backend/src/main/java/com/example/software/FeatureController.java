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
            "goal", "写一个成熟的 Spring Boot + Vue 人员管理系统，包含员工 CRUD、部门岗位、工资、API 契约、数据库设计、测试、交付清单和静态预览。本次是 ",
            "features", List.of(
                "Employee CRUD API",
                "Department and position fields",
                "Salary management field",
                "Vue single page client",
                "Static sandbox preview"
                
            )
        );
    }
}
