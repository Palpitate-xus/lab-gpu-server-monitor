<template>
  <a-config-provider :locale="antZhCN" :theme="antThemeConfig">
    <a-app>
      <router-view />
    </a-app>
  </a-config-provider>
</template>

<script setup>
import antZhCN from 'ant-design-vue/es/locale/zh_CN'
import { antThemeConfig } from './theme'
</script>
