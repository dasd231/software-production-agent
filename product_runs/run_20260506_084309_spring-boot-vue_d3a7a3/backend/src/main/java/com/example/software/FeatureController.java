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
            "goal", "生成Spring Boot+Vue的人员管理系统，包含工资，部门，岗位啥的，标准的大学生毕业设计",
            "features", List.of(
                "Dashboard shell",
                "REST health endpoint",
                "Feature list endpoint",
                "Vue single page client"
            )
        );
    }
}
