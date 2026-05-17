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
            "goal", "Spring Boot + Vue 管理后台",
            "features", List.of(
                "Dashboard shell",
                "REST health endpoint",
                "Feature list endpoint",
                "Vue single page client"
            )
        );
    }
}
