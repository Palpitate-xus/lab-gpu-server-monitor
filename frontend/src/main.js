import { createApp } from 'vue'
import {
  Alert as AntAlert,
  App as AntApp,
  Avatar as AntAvatar,
  Badge as AntBadge,
  Button as AntButton,
  Card as AntCard,
  Col as AntCol,
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
  Empty as AntEmpty,
  Progress as AntProgress,
  Result as AntResult,
  Row as AntRow,
  Skeleton as AntSkeleton,
  Spin as AntSpin,
  Statistic as AntStatistic,
  Steps as AntSteps,
  Table as AntTable,
  TableColumn as AntTableColumn,
  Tag as AntTag,
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
app.use(AntAlert)
app.use(AntApp)
app.use(AntAvatar)
app.use(AntBadge)
app.use(AntButton)
app.use(AntCard)
app.use(AntCol)
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
app.use(AntEmpty)
app.use(AntProgress)
app.use(AntResult)
app.use(AntRow)
app.use(AntSkeleton)
app.use(AntSpin)
app.use(AntStatistic)
app.use(AntSteps)
app.use(AntTable)
app.use(AntTableColumn)
app.use(AntTag)
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
