<template>
  <el-tooltip :content="tooltip" placement="bottom">
    <el-dropdown trigger="click" @command="onCommand">
      <span class="theme-switch" :title="tooltip">
        <el-icon :size="17">
          <Monitor v-if="mode === 'auto'" />
          <Sunny v-else-if="mode === 'light'" />
          <Moon v-else />
        </el-icon>
        <span v-if="mode === 'auto'" class="theme-switch-tag">{{ resolved === 'dark' ? '夜' : '日' }}</span>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="auto" :class="{ active: mode === 'auto' }">
            <el-icon><Monitor /></el-icon>跟随系统
            <span class="theme-switch-hint">{{ systemHint }}</span>
          </el-dropdown-item>
          <el-dropdown-item command="light" :class="{ active: mode === 'light' }">
            <el-icon><Sunny /></el-icon>浅色模式
          </el-dropdown-item>
          <el-dropdown-item command="dark" :class="{ active: mode === 'dark' }">
            <el-icon><Moon /></el-icon>深色模式
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </el-tooltip>
</template>

<script setup>
import { computed } from 'vue'
import { Monitor, Sunny, Moon } from '@element-plus/icons-vue'
import { useTheme } from '../theme'

const { mode, resolved, setMode } = useTheme()

const tooltip = computed(() =>
  mode.value === 'auto'
    ? `主题：跟随系统（当前${resolved.value === 'dark' ? '深色' : '浅色'}）`
    : `主题：${mode.value === 'dark' ? '深色' : '浅色'}`
)
const systemHint = computed(() => (resolved.value === 'dark' ? '· 夜间' : '· 日间'))

function onCommand(cmd) {
  setMode(cmd)
}
</script>

<style scoped>
.theme-switch {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--csub);
  transition: background 0.2s, color 0.2s;
}
.theme-switch:hover {
  background: var(--ctable-hover);
  color: var(--cprimary);
}
.theme-switch-tag {
  font-size: 10px;
  line-height: 1;
  color: var(--cprimary);
}
.theme-switch-hint {
  margin-left: 6px;
  font-size: 11px;
  color: var(--csub);
}
:deep(.el-dropdown-menu__item.active) {
  color: var(--cprimary);
  background: var(--ctable-hover);
}
</style>
