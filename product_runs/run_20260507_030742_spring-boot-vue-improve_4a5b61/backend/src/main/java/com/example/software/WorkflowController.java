package com.example.software;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/workflows")
public class WorkflowController {
    private final ConcurrentHashMap<Long, ApprovalItem> approvals = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong();

    public WorkflowController() {
        create("薪资调整审批", "林夏", "部门负责人审批中");
        create("岗位调动审批", "陈一", "人事复核中");
        create("新员工入职审批", "王新", "待提交材料");
    }

    @GetMapping("/approvals")
    public List<ApprovalItem> approvals() {
        return approvals.values().stream().sorted((a, b) -> Long.compare(a.id(), b.id())).toList();
    }

    @PostMapping("/approvals/{id}/approve")
    public ApprovalItem approve(@PathVariable long id) {
        ApprovalItem current = approvals.get(id);
        ApprovalItem next = new ApprovalItem(id, current.title(), current.employee(), "已通过");
        approvals.put(id, next);
        return next;
    }

    private void create(String title, String employee, String status) {
        long id = idSequence.incrementAndGet();
        approvals.put(id, new ApprovalItem(id, title, employee, status));
    }

    public record ApprovalItem(long id, String title, String employee, String status) {}
}
