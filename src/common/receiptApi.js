import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export const PAYMENT_METHODS = [
    { value: 'cash', label: '现金 / Cash' },
    { value: 'bank_transfer', label: '银行转账 / Bank Transfer' },
    { value: 'wechat', label: '微信 / WeChat Pay' },
    { value: 'alipay', label: '支付宝 / Alipay' },
    { value: 'other', label: '其他 / Other' },
];

export async function createReceipt(body) {
    const response = await fetch(`${endpoint}/receipts`, {
        method: 'POST',
        headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok || result.code !== 200) throw new Error(result.msg || '提交收款单失败');
    return result.data;
}

function base64ToBlob(base64, mimeType) {
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mimeType });
}

export async function printReceipt(receiptId, messageApi) {
    const preview = window.open('', '_blank');
    if (!preview) {
        messageApi.warning('浏览器拦截了新窗口，请允许弹窗后重试');
        return;
    }
    preview.document.write('正在生成收款单 PDF...');
    try {
        const response = await fetch(`${endpoint}/receipts/${receiptId}/pdf`, { headers: getSafeHeader() });
        const result = await response.json();
        if (!response.ok || result.code !== 200) throw new Error(result.msg || '生成失败');
        const url = URL.createObjectURL(base64ToBlob(result.data, result.mime_type || 'application/pdf'));
        preview.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
        preview.close();
        messageApi.error(error.message || '生成收款单失败');
    }
}
