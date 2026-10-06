import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export async function shippingConfirmationRequest(path, { body, headers, ...options } = {}) {
    const response = await fetch(`${endpoint}${path}`, {
        ...options,
        headers: { ...getSafeHeader(), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || ![200, 201].includes(result?.code)) {
        const error = new Error(result?.msg || '出货确认单请求失败，请重试');
        error.status = response.status;
        throw error;
    }
    return result.data;
}

export async function fetchShippingConfirmationPdf(uid, version) {
    const response = await fetch(`${endpoint}/shipping-confirmation-drafts/${encodeURIComponent(uid)}/pdf`, {
        method: 'POST',
        headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: version }),
    });
    const contentType = response.headers.get('content-type') || '';
    if (!response.ok || !contentType.toLowerCase().startsWith('application/pdf')) {
        const result = await response.json().catch(() => null);
        const error = new Error(result?.msg || '出货确认单 PDF 生成失败，请重试');
        error.status = response.status;
        throw error;
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('出货确认单 PDF 为空，请重试');
    return blob;
}
