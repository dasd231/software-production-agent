package com.example.software;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/employees")
@CrossOrigin(origins = "*")
public class EmployeeController {
    private final ConcurrentHashMap<Long, Employee> employees = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong();

    public EmployeeController() {
        save(new EmployeePayload("林夏", "研发部", "后端工程师", 15000, "在职"));
        save(new EmployeePayload("周澄", "研发部", "前端工程师", 13000, "试用"));
        save(new EmployeePayload("许诺", "财务部", "薪酬专员", 11000, "在职"));
        save(new EmployeePayload("陈一", "人事部", "HRBP", 12000, "待调岗"));
    }

    @GetMapping
    public List<Employee> list() {
        return employees.values().stream()
            .sorted(Comparator.comparingLong(Employee::id))
            .toList();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Employee create(@RequestBody EmployeePayload payload) {
        return save(payload);
    }

    @PutMapping("/{id}")
    public Employee update(@PathVariable long id, @RequestBody EmployeePayload payload) {
        if (!employees.containsKey(id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "employee not found");
        }
        Employee employee = fromPayload(id, payload);
        employees.put(id, employee);
        return employee;
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable long id) {
        Employee removed = employees.remove(id);
        if (removed == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "employee not found");
        }
        return Map.of("ok", true, "deletedId", id);
    }

    private Employee save(EmployeePayload payload) {
        long id = idSequence.incrementAndGet();
        Employee employee = fromPayload(id, payload);
        employees.put(id, employee);
        return employee;
    }

    private Employee fromPayload(long id, EmployeePayload payload) {
        return new Employee(
            id,
            text(payload.name(), "未命名"),
            text(payload.department(), "未分配"),
            text(payload.position(), "未定岗"),
            salary(payload.salary()),
            text(payload.status(), "在职")
        );
    }

    private String text(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value.trim();
    }

    private int salary(Integer value) {
        if (value == null || value < 0) {
            return 0;
        }
        return value;
    }

    public record Employee(long id, String name, String department, String position, int salary, String status) {}

    public record EmployeePayload(String name, String department, String position, Integer salary, String status) {}
}
