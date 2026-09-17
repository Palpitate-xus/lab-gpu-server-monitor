import { createApp } from 'vue'
import {
  App as AntApp,
  Button as AntButton,
  ConfigProvider,
  Dropdown as AntDropdown,
  Menu as AntMenu,
  MenuItem as AntMenuItem,
  Tooltip as AntTooltip,
} from 'ant-design-vue'
import {
  ElAlert,
  ElAside,
  ElAvatar,
  ElButton,
  ElButtonGroup,
  ElCard,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLink,
  ElLoading,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPageHeader,
  ElPagination,
  ElPopconfirm,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
} from 'element-plus'
import 'ant-design-vue/dist/reset.css'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import router from './router'
import { bootstrapSession } from './composables'
import './styles.css'
import './cockpit.css'
import './theme'

const app = createApp(App)

app.use(router)
app.use(AntApp)
app.use(AntButton)
app.use(ConfigProvider)
app.use(AntDropdown)
app.use(AntMenu)
app.use(AntMenuItem)
app.use(AntTooltip)
for (const component of [
  ElAlert,
  ElAside,
  ElAvatar,
  ElButton,
  ElButtonGroup,
  ElCard,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElConfigProvider,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLink,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPageHeader,
  ElPagination,
  ElPopconfirm,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
]) {
  app.use(component)
}
app.use(ElLoading)

bootstrapSession().finally(() => app.mount('#app'))
