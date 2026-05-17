package com.example.software;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/exchange")
public class ImportExportController {
    @PostMapping("/employees/import")
    public Map<String, Object> importEmployees() {
        return Map.of("ok", true, "imported", 3, "skipped", 0, "format", "csv-demo");
    }

    @GetMapping("/employees/export")
    public List<Map<String, Object>> exportEmployees() {
        return List.of(
            Map.of("name", "林夏", "department", "研发部", "position", "后端工程师", "salary", 15000),
            Map.of("name", "许诺", "department", "财务部", "position", "薪酬专员", "salary", 11000)
        );
    }
}
