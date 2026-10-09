// WMS API安全头部工具
// 为API请求添加时间戳和JWT令牌

export default function getSafeHeader() {
    const timestamp = (new Date()).getTime().toString(16);
    const jwt = localStorage.getItem('jwt');

    return {
        'x-time': timestamp,
        'x-token': jwt || ''  // 确保token为空时不传null
    }
}
