import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export const FINANCE_DOCUMENT_TYPES = {
    customer_invoice: { label: '客户账单', partner: 'customer', short: '应收' },
    vendor_bill: { label: '供应商账单', partner: 'vendor', short: '应付' },
    customer_credit: { label: '客户贷项', partner: 'customer', short: '客户退款 / 抵扣' },
    vendor_credit: { label: '供应商贷项', partner: 'vendor', short: '供应商退款 / 抵扣' },
};
export const FINANCE_STATUS = {
    draft: { label: '草稿', color: 'default' },
    pending: { label: '待财务确认', color: 'orange' },
    posted: { label: '已生效', color: 'blue' },
    cancelled: { label: '已取消', color: 'default' },
    reversed: { label: '已冲销', color: 'red' },
    active: { label: '已核销', color: 'green' },
    unpaid: { label: '未结清', color: 'orange' },
    partial: { label: '部分结清', color: 'gold' },
    paid: { label: '已结清', color: 'green' },
};
export const money = value => new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
export function mutationKey() {
    return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `finance-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
export function queryString(params = {}) {
    return new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => [key, String(value)])).toString();
}
export async function financeRequest(path, { method = 'GET', body, params, signal } = {}) {
    const query = params ? queryString(params) : '';
    const response = await fetch(`${endpoint}/finance/v2${path}${query ? `?${query}` : ''}`, {
        method, signal,
        headers: { ...getSafeHeader(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
    });
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('服务器返回格式错误，请稍后重试'); }
    if (!response.ok || result.code !== 200) {
        const error = new Error(result.msg || result.message || '财务请求失败');
        error.status = response.status;
        throw error;
    }
    return result.data;
}
export function paymentTargetType(payment) {
    if (payment.partner_type === 'customer') return payment.direction === 'incoming' ? 'customer_invoice' : 'customer_credit';
    return payment.direction === 'outgoing' ? 'vendor_bill' : 'vendor_credit';
}

export async function printFinancePayment(paymentId, messageApi) {
    const preview = window.open('', '_blank');
    if (!preview) { messageApi.warning('浏览器拦截了打印窗口，请允许弹窗后重试'); return; }
    preview.document.write('正在生成收付款凭证…');
    try {
        const encoded = await financeRequest(`/payments/${paymentId}/pdf`);
        const binary = window.atob(encoded);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
        preview.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { preview.close(); messageApi.error(error.message || '生成收付款凭证失败'); }
}
