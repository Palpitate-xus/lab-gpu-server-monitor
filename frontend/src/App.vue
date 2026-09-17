<template>
  <a-config-provider :locale="antZhCN" :theme="antThemeConfig">
    <a-app>
      <el-config-provider :locale="elementZhCN">
        <router-view />
      </el-config-provider>
    </a-app>
  </a-config-provider>
</template>

<script setup>
import antZhCN from 'ant-design-vue/es/locale/zh_CN'
import elementZhCN from 'element-plus/es/locale/lang/zh-cn'
import { antThemeConfig } from './theme'
</script>
