import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

async function request(path, { body, params, acceptParcelData = false, ...options } = {}) {
    const query = new URLSearchParams(Object.entries(params || {})
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([key, value]) => [key, String(value)])).toString();
    const response = await fetch(`${endpoint}${path}${query ? `?${query}` : ''}`, {
        method: 'GET', ...options,
        headers: { ...getSafeHeader(), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json().catch(() => null);
    // The existing cargo endpoint still returns local parcel data when its
    // optional live tracking lookup fails (HTTP 200, business code 500).
    const parcelData = acceptParcelData && result?.code === 500 && Array.isArray(result.data);
    if (!response.ok || (![200, 201].includes(result?.code) && !parcelData)) {
        const error = new Error(result?.msg || result?.message || '异常订单请求失败，请重试');
        error.status = response.status;
        error.code = result?.code;
        throw error;
    }
    return result;
}

export const fetchOrderExceptions = ({ page = 1, pageSize = 20, status = 'open', salesmanId, ...options } = {}) =>
    request('/order-exceptions', { ...options, params: { page, page_size: pageSize, status, salesman_id: salesmanId } }).then(result => result.data);
export const fetchOrderException = (uid, options) =>
    request(`/order-exceptions/${encodeURIComponent(uid)}`, options).then(result => result.data);
export const fetchExceptionSalespeople = options => request('/order-exceptions/salespeople', options).then(result => result.data);
export const registerOrderException = (body, options) => request('/order-exceptions', { ...options, method: 'POST', body }).then(result => result.data);
export const addExceptionFollowup = (uid, body, options) =>
    request(`/order-exceptions/${encodeURIComponent(uid)}/followups`, { ...options, method: 'POST', body }).then(result => result.data);
export const resolveOrderException = (uid, body, options) =>
    request(`/order-exceptions/${encodeURIComponent(uid)}/resolve`, { ...options, method: 'POST', body }).then(result => result.data);

export const searchExceptionOrders = (query, options) =>
    request('/orders', { ...options, params: { q: query, p: 1, s: 20 } }).then(result => result.data || []);
export const fetchExceptionOrderCargos = (uid, options) =>
    request(`/orders/${encodeURIComponent(uid)}/cargo`, { ...options, acceptParcelData: true }).then(result => result.data || []);

export function createExceptionEventKey() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
        const value = Math.floor(Math.random() * 16);
        return (character === 'x' ? value : (value & 3) | 8).toString(16);
    });
}

// Reuse the same key after an uncertain response, while a changed submission is a new action.
export function exceptionSubmission(ref, body) {
    const fingerprint = JSON.stringify(body);
    if (ref.current?.fingerprint !== fingerprint) ref.current = { fingerprint, eventKey: createExceptionEventKey() };
    return { ...body, event_key: ref.current.eventKey };
}
