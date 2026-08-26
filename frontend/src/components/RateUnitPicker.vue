<template>
  <el-dropdown trigger="click" @command="onCommand">
    <span class="unit-pick" :title="`单位：${currentLabel}`">
      <el-icon :size="14"><Histogram /></el-icon>
      <span class="unit-pick-text">{{ currentLabel }}</span>
      <el-icon :size="10"><ArrowDown /></el-icon>
    </span>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled class="unit-group">{{ kind === 'net' ? '网络速率单位' : '磁盘速率单位' }}</el-dropdown-item>
        <el-dropdown-item
          v-for="opt in options" :key="opt.value"
          :command="opt.value" :class="{ active: opt.value === pref }">
          {{ opt.label }}
          <el-icon v-if="opt.value === pref" class="unit-check"><Check /></el-icon>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowDown, Check, Histogram } from '@element-plus/icons-vue'
import {
  DISK_UNIT_OPTIONS, NET_UNIT_OPTIONS,
  getDiskUnit, getNetUnit, setDiskUnit, setNetUnit,
} from '../format'

const props = defineProps({
  kind: { type: String, default: 'net' }, // 'net' | 'disk'
})
const emit = defineEmits(['change'])

const pref = ref(props.kind === 'net' ? getNetUnit() : getDiskUnit())
const options = props.kind === 'net' ? NET_UNIT_OPTIONS : DISK_UNIT_OPTIONS
const currentLabel = computed(() => (options.find(o => o.value === pref.value) || {}).label || pref.value)

function onCommand(v) {
  pref.value = v
  if (props.kind === 'net') setNetUnit(v)
  else setDiskUnit(v)
  emit('change', v)
}
</script>

<style scoped>
.unit-pick {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--cborder);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: var(--csub);
  background: var(--cpanel);
  transition: border-color 0.2s, color 0.2s;
  user-select: none;
}
.unit-pick:hover { border-color: var(--cprimary); color: var(--cprimary); }
.unit-pick-text { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unit-group { font-size: 11px; color: var(--csub); }
:deep(.el-dropdown-menu__item.active) { color: var(--cprimary); }
.unit-check { margin-left: 6px; }
</style>
