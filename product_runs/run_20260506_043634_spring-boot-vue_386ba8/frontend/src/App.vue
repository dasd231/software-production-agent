<script setup>
const goal = 'Spring Boot + Vue 管理后台'
const features = [
  'Spring Boot REST API',
  'Vue dashboard shell',
  'Health and feature endpoints',
  'Offline generated project scaffold'
]
</script>

<template>
  <main class="shell">
    <section class="summary">
      <p class="eyebrow">Software Production Agent</p>
      <h1>Spring Boot + Vue Prototype</h1>
      <p>{{ goal }}</p>
    </section>
    <section class="panel">
      <h2>Generated Capabilities</h2>
      <ul>
        <li v-for="feature in features" :key="feature">{{ feature }}</li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(260px, 0.85fr) minmax(280px, 1fr);
  gap: 24px;
  align-items: center;
  padding: 48px;
  background: #f6f7f3;
  color: #151817;
  font-family: Inter, system-ui, sans-serif;
}
.summary h1 {
  margin: 0 0 12px;
  font-size: clamp(32px, 6vw, 64px);
  letter-spacing: 0;
}
.eyebrow {
  color: #1b7b54;
  font-weight: 760;
}
.panel {
  border: 1px solid #d9ded4;
  border-radius: 8px;
  padding: 22px;
  background: white;
  box-shadow: 0 16px 40px rgba(22, 28, 24, 0.08);
}
li { margin: 10px 0; }
@media (max-width: 760px) {
  .shell { grid-template-columns: 1fr; padding: 24px; }
}
</style>
