import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export const MESSAGE_POLL_INTERVAL = 3 * 60 * 1000;

async function messageRequest(path, { method = 'GET', body, params, signal, token } = {}) {
    const query = new URLSearchParams(Object.entries(params || {})
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([key, value]) => [key, String(value)])).toString();
    const headers = getSafeHeader();
    if (token !== undefined) headers['x-token'] = token;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(`${endpoint}/messages${path}${query ? `?${query}` : ''}`, {
        method, signal, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    let result;
    try { result = await response.json(); }
    catch {
        const error = new Error('服务器返回格式错误，请稍后重试');
        error.status = response.status;
        throw error;
    }
    if (!response.ok || result?.code !== 200) {
        const error = new Error(result?.msg || result?.message || '消息请求失败，请重试');
        error.status = response.status;
        error.code = result?.code;
        throw error;
    }
    return result.data;
}

export const fetchMessages = ({ page = 1, pageSize = 20, status = 'all', ...options } = {}) =>
    messageRequest('', { ...options, params: { page, page_size: pageSize, status } });
export const fetchUnreadCount = (options) => messageRequest('/unread-count', options);
export const fetchMessage = (uid, options) => messageRequest(`/${encodeURIComponent(uid)}`, options);
export const markMessageRead = (uid, options) => messageRequest(`/${encodeURIComponent(uid)}/read`, { ...options, method: 'POST' });
export const markAllMessagesRead = (options) => messageRequest('/read-all', { ...options, method: 'POST' });
export const sendMessage = (body, options) => messageRequest('', { ...options, method: 'POST', body });

export function isInternalMessagePath(path) {
    return typeof path === 'string' && /^\/(?!\/)/.test(path) &&
        Array.from(path).every(character => character !== '\\' && character.charCodeAt(0) > 32 && character.charCodeAt(0) !== 127);
}
