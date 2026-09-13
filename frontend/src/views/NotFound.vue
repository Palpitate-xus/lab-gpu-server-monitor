<template>
  <div class="cockpit notfound-page">
    <div class="cockpit-panel notfound-panel">
      <div class="notfound-code">404</div>
      <div class="notfound-title">页面不存在</div>
      <p class="notfound-sub">请检查地址是否正确。</p>
      <el-button type="primary" @click="$router.push('/cockpit')">返回驾驶舱</el-button>
    </div>
  </div>
</template>

<style scoped>
.notfound-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
}
.notfound-panel {
  max-width: 420px;
  padding: 40px 32px;
  text-align: center;
}
.notfound-code {
  color: var(--cprimary);
  font: 700 44px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: .08em;
}
.notfound-title {
  margin-top: 12px;
  font-size: 18px;
  font-weight: 600;
}
.notfound-sub {
  margin: 8px 0 22px;
  color: var(--csub);
  font-size: 13px;
  line-height: 1.6;
}
</style>
