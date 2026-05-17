package com.example.software;

import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class EmployeeControllerTest {
    @Autowired
    private MockMvc mvc;

    @Test
    void employeeCrudFlowWorks() throws Exception {
        mvc.perform(get("/api/employees"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$", hasSize(4)));

        mvc.perform(post("/api/employees")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{"name":"王新","department":"市场部","position":"产品经理","salary":16000,"status":"在职"}"))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.name").value("王新"));

        mvc.perform(put("/api/employees/1")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{"name":"林夏","department":"研发部","position":"技术负责人","salary":21000,"status":"在职"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.position").value("技术负责人"));

        mvc.perform(delete("/api/employees/2"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.ok").value(true));
    }
}
