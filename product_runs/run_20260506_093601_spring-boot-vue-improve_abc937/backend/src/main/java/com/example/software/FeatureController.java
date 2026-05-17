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
            "goal", "基于上一版软件方案继续改进，不要从零开始。 上一版 run: run_20260506_093527_spring-boot-vue-improve_249c6",
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
