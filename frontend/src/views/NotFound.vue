<template>
  <div class="not-found-page">
    <a-result status="404" title="404" sub-title="页面不存在，请检查地址是否正确。">
      <template #extra>
        <a-button type="primary" @click="$router.push('/cockpit')">返回驾驶舱</a-button>
      </template>
    </a-result>
  </div>
</template>

<style scoped>
.not-found-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--cbg);
}
</style>
