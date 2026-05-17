package com.example.software;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reference")
public class ReferenceDataController {
    @GetMapping("/departments")
    public List<Map<String, Object>> departments() {
        return List.of(
            Map.of("id", 1, "name", "研发部", "owner", "赵经理", "headcount", 18),
            Map.of("id", 2, "name", "财务部", "owner", "钱经理", "headcount", 7),
            Map.of("id", 3, "name", "人事部", "owner", "孙经理", "headcount", 6),
            Map.of("id", 4, "name", "市场部", "owner", "李经理", "headcount", 11)
        );
    }

    @GetMapping("/positions")
    public List<Map<String, Object>> positions() {
        return List.of(
            Map.of("id", 1, "name", "后端工程师", "level", "P5", "salaryMin", 12000, "salaryMax", 22000),
            Map.of("id", 2, "name", "前端工程师", "level", "P5", "salaryMin", 11000, "salaryMax", 21000),
            Map.of("id", 3, "name", "薪酬专员", "level", "P4", "salaryMin", 8000, "salaryMax", 15000),
            Map.of("id", 4, "name", "HRBP", "level", "P5", "salaryMin", 10000, "salaryMax", 18000),
            Map.of("id", 5, "name", "产品经理", "level", "P5", "salaryMin", 12000, "salaryMax", 23000)
        );
    }

    @GetMapping("/payroll-rules")
    public Map<String, Object> payrollRules() {
        return Map.of(
            "currency", "CNY",
            "salaryCycle", "monthly",
            "socialInsuranceRate", 0.105,
            "housingFundRate", 0.07,
            "overtimePolicy", "department approval required"
        );
    }
}
