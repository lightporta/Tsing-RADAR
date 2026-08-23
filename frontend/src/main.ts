import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './assets/styles/global.scss'

// =====================================================================
// 应用入口
// =====================================================================

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
