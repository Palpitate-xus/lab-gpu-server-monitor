<template>
  <a-tooltip :title="tooltip" placement="bottom">
    <a-dropdown :trigger="['click']">
      <a-button type="text" shape="circle" :aria-label="tooltip">
        <DesktopOutlined v-if="mode === 'auto'" />
        <BulbOutlined v-else-if="mode === 'light'" />
        <EyeInvisibleOutlined v-else />
      </a-button>
      <template #overlay>
        <a-menu :selected-keys="[mode]" @click="onCommand">
          <a-menu-item key="auto">
            <DesktopOutlined />
            跟随系统
            <span class="theme-switch-hint">{{ systemHint }}</span>
          </a-menu-item>
          <a-menu-item key="light">
            <BulbOutlined />
            浅色模式
          </a-menu-item>
          <a-menu-item key="dark">
            <EyeInvisibleOutlined />
            深色模式
          </a-menu-item>
        </a-menu>
      </template>
    </a-dropdown>
  </a-tooltip>
</template>

<script setup>
import { computed } from 'vue'
import { BulbOutlined, DesktopOutlined, EyeInvisibleOutlined } from '@ant-design/icons-vue'
import { useTheme } from '../theme'

const { mode, resolved, setMode } = useTheme()

const tooltip = computed(() =>
  mode.value === 'auto'
    ? `主题：跟随系统（当前${resolved.value === 'dark' ? '深色' : '浅色'}）`
    : `主题：${mode.value === 'dark' ? '深色' : '浅色'}`
)
const systemHint = computed(() => (resolved.value === 'dark' ? '· 夜间' : '· 日间'))

function onCommand({ key }) {
  setMode(key)
}
</script>

<style scoped>
.theme-switch-hint {
  margin-left: 6px;
  font-size: 11px;
  color: var(--csub);
}
</style>
