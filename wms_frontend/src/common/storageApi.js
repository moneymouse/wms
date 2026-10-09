import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export async function storageRequest(path, { method = 'GET', body, params, signal } = {}) {
    const query = new URLSearchParams(Object.entries(params || {})
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([key, value]) => [key, String(value)])).toString();
    const response = await fetch(`${endpoint}/storage${path}${query ? `?${query}` : ''}`, {
        method,
        signal,
        headers: { ...getSafeHeader(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error('服务器返回格式错误，请稍后重试'); }
    if (!response.ok || result?.code !== 200) {
        throw new Error(result?.msg || result?.message || '存储管理请求失败，请重试');
    }
    return result.data;
}

export async function storagePhotoRequest(intakeUid, photoUid, { signal } = {}) {
    const response = await fetch(`${endpoint}/storage/intakes/${encodeURIComponent(intakeUid)}/photos/${encodeURIComponent(photoUid)}`, {
        signal,
        headers: getSafeHeader(),
    });
    if (!response.ok) {
        let result;
        try { result = await response.json(); } catch { /* The file service may return a non-JSON error. */ }
        throw new Error(result?.msg || result?.message || '照片加载失败，请重试');
    }
    return response.blob();
}

export function formatStorageBytes(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
    const bytes = Math.max(0, Number(value));
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length);
    return `${(bytes / (1024 ** exponent)).toFixed(2)} ${units[exponent - 1]}`;
}
