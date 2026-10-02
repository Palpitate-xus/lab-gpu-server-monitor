import { createApp } from 'vue'
import {
  Alert as AntAlert,
  App as AntApp,
  Avatar as AntAvatar,
  Badge as AntBadge,
  Button as AntButton,
  Card as AntCard,
  Col as AntCol,
  Collapse as AntCollapse,
  ConfigProvider,
  Descriptions as AntDescriptions,
  Drawer as AntDrawer,
  Dropdown as AntDropdown,
  Form as AntForm,
  Input as AntInput,
  InputNumber as AntInputNumber,
  Layout as AntLayout,
  Menu as AntMenu,
  Modal as AntModal,
  Empty as AntEmpty,
  PageHeader as AntPageHeader,
  Popconfirm as AntPopconfirm,
  Pagination as AntPagination,
  Progress as AntProgress,
  Radio as AntRadio,
  Result as AntResult,
  Row as AntRow,
  Skeleton as AntSkeleton,
  Slider as AntSlider,
  Select as AntSelect,
  Spin as AntSpin,
  Statistic as AntStatistic,
  Steps as AntSteps,
  Switch as AntSwitch,
  Table as AntTable,
  Tabs as AntTabs,
  Tag as AntTag,
  Tooltip as AntTooltip,
} from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import App from './App.vue'
import router from './router'
import './styles.css'
import './cockpit.css'
import './theme'

const app = createApp(App)

app.use(AntAlert)
app.use(AntApp)
app.use(AntAvatar)
app.use(AntBadge)
app.use(AntButton)
app.use(AntCard)
app.use(AntCol)
app.use(AntCollapse)
app.use(ConfigProvider)
app.use(AntDescriptions)
app.use(AntDrawer)
app.use(AntDropdown)
app.use(AntForm)
app.use(AntInput)
app.use(AntInputNumber)
app.use(AntLayout)
app.use(AntMenu)
app.use(AntModal)
app.use(AntEmpty)
app.use(AntPageHeader)
app.use(AntPopconfirm)
app.use(AntPagination)
app.use(AntProgress)
app.use(AntRadio)
app.use(AntResult)
app.use(AntRow)
app.use(AntSkeleton)
app.use(AntSlider)
app.use(AntSelect)
app.use(AntSpin)
app.use(AntStatistic)
app.use(AntSteps)
app.use(AntTable)
app.use(AntTabs)
app.use(AntTag)
app.use(AntSwitch)
app.use(AntTooltip)

// Public status renders immediately; authenticated navigation waits in the guard.
app.use(router)
app.mount('#app')
