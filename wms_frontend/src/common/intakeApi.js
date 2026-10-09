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
        const error = new Error(result.msg || result.message || '请求失败，请重试');
        error.status = response.status;
        error.data = result.data;
        throw error;
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

export const emptyIntakeItemDetail = () => ({ item_name: '', piece_count: null, customs_code: '' });
export const emptyBox = () => ({ box_number: '', item_name: '', item_details: [emptyIntakeItemDetail()], count: null, weight: null, worker_ids: [], remark: '' });
export const MAX_INTAKE_WORKERS = 4;
export const MAX_INTAKE_ITEMS = 100;
export const MAX_INTAKE_PIECE_COUNT = 2147483647;
export const MAX_INTAKE_REMARK_LENGTH = 512;
export const normalizeIntakeWorkerIds = workerIds => [...new Set((Array.isArray(workerIds) ? workerIds : []).map(Number).filter(id => Number.isSafeInteger(id) && id > 0))];
const isPositiveCount = value => ['number', 'string'].includes(typeof value) && value !== '' && Number.isSafeInteger(Number(value)) && Number(value) > 0 && Number(value) <= MAX_INTAKE_PIECE_COUNT;
export const hasCompleteIntakeItemCounts = box => Array.isArray(box.item_details) && box.item_details.length > 0 && box.item_details.every(row => isPositiveCount(row.piece_count)) && isPositiveCount(box.item_details.reduce((sum, row) => sum + Number(row.piece_count), 0));

export function normalizeIntakeBox(box) {
    const legacyNames = String(box.item_name || '').split(/[、，,；;\n]+/).map(name => name.trim()).filter(Boolean);
    const sourceDetails = Array.isArray(box.item_details)
        ? box.item_details
        : legacyNames.length > 1
            ? legacyNames.map(item_name => ({ item_name, piece_count: null }))
            : [{ item_name: box.item_name || '', piece_count: box.count ?? null }];
    const itemDetails = sourceDetails.map(row => ({
        item_name: String(row?.item_name || ''),
        piece_count: isPositiveCount(row?.piece_count) ? Number(row.piece_count) : row?.piece_count ?? null,
        customs_code: String(row?.customs_code || ''),
    }));
    const total = itemDetails.reduce((sum, row) => sum + Number(row.piece_count), 0);
    return {
        ...box,
        remark: String(box.remark ?? ''),
        item_details: itemDetails,
        item_name: itemDetails.map(row => row.item_name.trim()).filter(Boolean).join('、'),
        // 未知的分项件数不能从纸单总件数推断；保留总件数供核对。
        count: hasCompleteIntakeItemCounts({ item_details: itemDetails }) ? total : box.count ?? null,
    };
}

export const normalizeIntakeDraft = draft => ({
    mark: draft?.mark || '',
    operator_name: draft?.operator_name || '',
    boxes: (draft?.boxes || []).map(box => normalizeIntakeBox({
        box_number: box.box_number ?? '', item_name: box.item_name || '',
        ...(Array.isArray(box.item_details) ? { item_details: box.item_details } : {}),
        count: box.count ?? null, weight: box.weight ?? null,
        remark: box.remark,
        worker_ids: normalizeIntakeWorkerIds(Object.prototype.hasOwnProperty.call(box, 'worker_ids') ? box.worker_ids : draft?.worker_ids),
    })),
});

export function validateIntakeDraft(draft) {
    if (!draft.mark.trim()) return '请填写唛头';
    if (!draft.boxes.length) return '请至少添加一箱';
    const numbers = new Set();
    for (let i = 0; i < draft.boxes.length; i += 1) {
        const box = normalizeIntakeBox(draft.boxes[i]);
        if (!box.worker_ids?.length) return `第 ${i + 1} 箱请选择至少一名实际操作人员`;
        if (box.worker_ids.length > MAX_INTAKE_WORKERS) return `第 ${i + 1} 箱最多选择 ${MAX_INTAKE_WORKERS} 名实际操作人员`;
        if (Array.from(box.remark.trim()).length > MAX_INTAKE_REMARK_LENGTH) return `第 ${i + 1} 箱的备注不能超过 ${MAX_INTAKE_REMARK_LENGTH} 个字符`;
        const number = String(box.box_number ?? '').trim();
        if (!number || !box.item_name.trim()) return `第 ${i + 1} 箱的箱号和品名不能为空`;
        if (!/^[1-9]\d*$/.test(number) || !Number.isSafeInteger(Number(number))) return `第 ${i + 1} 箱的箱号必须为正整数，不支持字母或前导 0`;
        if (Number(number) > 2147483647) return `第 ${i + 1} 箱的箱号不能超过 2147483647`;
        if (numbers.has(number)) return `箱号 ${number} 重复，请核对`;
        numbers.add(number);
        if (box.item_details.length > MAX_INTAKE_ITEMS) return `第 ${i + 1} 箱最多填写 ${MAX_INTAKE_ITEMS} 项品名`;
        if (Array.from(box.item_name).length > 256) return `第 ${i + 1} 箱的品名合计不能超过 256 个字符`;
        for (let j = 0; j < box.item_details.length; j += 1) {
            if (!box.item_details[j].item_name.trim()) return `第 ${i + 1} 箱第 ${j + 1} 项的品名不能为空`;
            if (Array.from(box.item_details[j].item_name.trim()).length > 256) return `第 ${i + 1} 箱第 ${j + 1} 项的品名不能超过 256 个字符`;
            if (Array.from(box.item_details[j].customs_code.trim()).length > 64) return `第 ${i + 1} 箱第 ${j + 1} 项的海关编码不能超过 64 个字符`;
            if (!isPositiveCount(box.item_details[j].piece_count)) return `第 ${i + 1} 箱第 ${j + 1} 项的件数必须为正整数且不能超过 ${MAX_INTAKE_PIECE_COUNT}`;
        }
        if (!isPositiveCount(box.item_details.reduce((sum, row) => sum + Number(row.piece_count), 0))) return `第 ${i + 1} 箱的总件数不能超过 ${MAX_INTAKE_PIECE_COUNT}`;
        if (box.weight === null || box.weight === '' || !Number.isFinite(Number(box.weight)) || Number(box.weight) <= 0) return `第 ${i + 1} 箱的重量必须大于 0`;
    }
    return '';
}
