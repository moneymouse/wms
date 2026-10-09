import { endpoint } from '../config';
import getSafeHeader from './safeHeader';
import { queryString } from './financeApi';

const basePath = `${endpoint}/supplier-reconciliation`;

async function readResponse(response) {
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('服务器返回格式错误，请稍后重试'); }
    if (!response.ok || result.code !== 200) {
        const error = new Error(result.msg || '第三方账单处理失败');
        error.status = response.status;
        throw error;
    }
    return result.data;
}

export async function reconciliationRequest(path, { params, signal } = {}) {
    const query = params ? queryString(params) : '';
    return readResponse(await fetch(`${basePath}${path}${query ? `?${query}` : ''}`, {
        headers: getSafeHeader(), signal,
    }));
}

export async function uploadReconciliation({ file, vendorId, period }) {
    const body = new FormData();
    body.append('file', file);
    body.append('vendor_id', String(vendorId));
    body.append('period', period);
    return readResponse(await fetch(`${basePath}/batches`, {
        method: 'POST', headers: getSafeHeader(), body,
    }));
}

export async function reconcileBatch(id, version) {
    return readResponse(await fetch(`${basePath}/batches/${encodeURIComponent(id)}/reconcile`, {
        method: 'POST', headers: { ...getSafeHeader(), 'Content-Type': 'application/json' }, body: JSON.stringify({ version }),
    }));
}

export async function downloadReconciliationTemplate() {
    const response = await fetch(`${basePath}/template`, { headers: getSafeHeader() });
    if (!response.ok || response.headers?.get('Content-Type')?.includes('application/json')) {
        await readResponse(response);
        throw new Error('对账模板下载失败');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('对账模板为空，请重试');
    return blob;
}
