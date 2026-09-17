<template>
  <a-dropdown :trigger="['click']">
    <a-button size="small" :title="`单位：${currentLabel}`">
      <BarChartOutlined />
      <span class="unit-pick-text">{{ currentLabel }}</span>
      <DownOutlined />
    </a-button>
    <template #overlay>
      <a-menu :selected-keys="[pref]" @click="onCommand">
        <a-menu-item key="unit-heading" disabled>{{ kind === 'net' ? '网络速率单位' : '磁盘速率单位' }}</a-menu-item>
        <a-menu-item v-for="opt in options" :key="opt.value">
          {{ opt.label }}
          <CheckOutlined v-if="opt.value === pref" class="unit-check" />
        </a-menu-item>
      </a-menu>
    </template>
  </a-dropdown>
</template>

<script setup>
import { computed, ref } from 'vue'
import { BarChartOutlined, CheckOutlined, DownOutlined } from '@ant-design/icons-vue'
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

function onCommand({ key: v }) {
  pref.value = v
  if (props.kind === 'net') setNetUnit(v)
  else setDiskUnit(v)
  emit('change', v)
}
</script>

<style scoped>
.unit-pick-text { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unit-check { margin-left: 6px; }
</style>
