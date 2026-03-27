// WMS Frontend API配置
// 支持多环境部署和开发代理模式

const urlConfig = {
    // 开发模式 - 通过Nginx代理 (推荐)
    "development": "http://localhost:5001/api",
    // 生产模式 - 相对路径
    "production": "/api"
}

// 支持环境变量覆盖
const apiEndpoint = process.env.REACT_APP_API_ENDPOINT || urlConfig[process.env.NODE_ENV]

export const endpoint = apiEndpoint

// 调试信息
console.log(`🔗 API Endpoint: ${endpoint} (Environment: ${process.env.NODE_ENV})`)