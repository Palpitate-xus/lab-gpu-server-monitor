import { createApp } from 'vue'
import {
  App as AntApp,
  Avatar as AntAvatar,
  Badge as AntBadge,
  Button as AntButton,
  Card as AntCard,
  ConfigProvider,
  Drawer as AntDrawer,
  Dropdown as AntDropdown,
  Form as AntForm,
  FormItem as AntFormItem,
  Input as AntInput,
  InputPassword as AntInputPassword,
  Layout as AntLayout,
  LayoutContent as AntLayoutContent,
  LayoutHeader as AntLayoutHeader,
  LayoutSider as AntLayoutSider,
  Menu as AntMenu,
  MenuItem as AntMenuItem,
  Result as AntResult,
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
app.use(AntAvatar)
app.use(AntBadge)
app.use(AntButton)
app.use(AntCard)
app.use(ConfigProvider)
app.use(AntDrawer)
app.use(AntDropdown)
app.use(AntForm)
app.use(AntFormItem)
app.use(AntInput)
app.use(AntInputPassword)
app.use(AntLayout)
app.use(AntLayoutContent)
app.use(AntLayoutHeader)
app.use(AntLayoutSider)
app.use(AntMenu)
app.use(AntMenuItem)
app.use(AntResult)
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
