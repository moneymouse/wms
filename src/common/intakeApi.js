import { endpoint } from '../config';
import getSafeHeader from './safeHeader';

export async function downloadPaperIntakeTemplate() {
    const response = await fetch(`${endpoint}/intakes/template`, { headers: getSafeHeader() });
    if (!response.ok) {
        let result;
        try { result = await response.json(); } catch { /* 模板服务可能返回非 JSON 错误 */ }
        throw new Error(result?.msg || '模板下载失败，请重试');
    }
    const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
    if (contentType !== 'application/pdf') throw new Error('模板文件不可用，请重试');
    const blob = await response.blob();
    if (!blob.size) throw new Error('模板文件为空，请重试');
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'paper-packing-list-a4.pdf';
    document.body.appendChild(link);
    try { link.click(); }
    finally {
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
}

export async function intakeRequest(path = '', options = {}) {
    const { body, ...rest } = options;
    const isForm = body instanceof FormData;
    const response = await fetch(`${endpoint}/intakes${path}`, {
        ...rest,
        headers: { ...getSafeHeader(), ...(body && !isForm ? { 'Content-Type': 'application/json' } : {}) },
        ...(body ? { body: isForm ? body : JSON.stringify(body) } : {}),
    });
    const result = await response.json();
    if (!response.ok || ![200, 201, 202].includes(result.code)) {
        throw new Error(result.msg || result.message || '请求失败，请重试');
    }
    return result.data;
}

export function getIntakeRoles() {
    try {
        const payload = JSON.parse(atob(localStorage.getItem('jwt').split('.')[1]));
        const roles = Array.isArray(payload.roles) ? payload.roles : (typeof payload.roles === 'string' ? [payload.roles] : []);
        return [...new Set([...roles, ...(payload.role ? [payload.role] : [])])];
    } catch { return []; }
}

export const emptyBox = () => ({ box_number: '', item_name: '', count: null, weight: null });
export const MAX_INTAKE_WORKERS = 4;
export const normalizeIntakeDraft = draft => ({
    mark: draft?.mark || '',
    operator_name: draft?.operator_name || '',
    worker_ids: [...new Set((Array.isArray(draft?.worker_ids) ? draft.worker_ids : []).map(Number).filter(id => Number.isSafeInteger(id) && id > 0))],
    boxes: (draft?.boxes || []).map(box => ({
        box_number: box.box_number ?? '', item_name: box.item_name || '',
        count: box.count ?? null, weight: box.weight ?? null,
    })),
});

export function validateIntakeDraft(draft) {
    if (!draft.mark.trim()) return '请填写唛头';
    if (!draft.boxes.length) return '请至少添加一箱';
    if (!draft.worker_ids?.length) return '请选择至少一名实际操作人员';
    if (draft.worker_ids.length > MAX_INTAKE_WORKERS) return `最多选择 ${MAX_INTAKE_WORKERS} 名实际操作人员`;
    const numbers = new Set();
    for (let i = 0; i < draft.boxes.length; i += 1) {
        const box = draft.boxes[i];
        const number = String(box.box_number ?? '').trim();
        if (!number || !box.item_name.trim()) return `第 ${i + 1} 箱的箱号和品名不能为空`;
        if (!/^[1-9]\d*$/.test(number) || !Number.isSafeInteger(Number(number))) return `第 ${i + 1} 箱的箱号必须为正整数，不支持字母或前导 0`;
        if (Number(number) > 2147483647) return `第 ${i + 1} 箱的箱号不能超过 2147483647`;
        if (numbers.has(number)) return `箱号 ${number} 重复，请核对`;
        numbers.add(number);
        if (!Number.isInteger(Number(box.count)) || Number(box.count) <= 0) return `第 ${i + 1} 箱的件数必须为正整数`;
        if (box.weight === null || box.weight === '' || !Number.isFinite(Number(box.weight)) || Number(box.weight) <= 0) return `第 ${i + 1} 箱的重量必须大于 0`;
    }
    return '';
}
