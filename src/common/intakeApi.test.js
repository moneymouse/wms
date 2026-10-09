import { emptyBox, hasCompleteIntakeItemCounts, MAX_INTAKE_REMARK_LENGTH, normalizeIntakeBox, normalizeIntakeDraft, validateIntakeDraft } from './intakeApi';

const box = { box_number: '1', item_name: '鞋', count: 2, weight: 3 };

test('legacy global workers fill only boxes without an explicit worker list', () => {
    const result = normalizeIntakeDraft({ mark: 'LEGACY', worker_ids: ['1', 1, 0, null, 'x', 2], boxes: [box, { ...box, worker_ids: [] }, { ...box, worker_ids: [3] }] });
    expect(result.boxes.map(item => item.worker_ids)).toEqual([[1, 2], [], [3]]);
    expect(result).not.toHaveProperty('worker_ids');
});

test('per box worker lists normalize independently and new boxes never inherit another box workers', () => {
    const result = normalizeIntakeDraft({ boxes: [{ ...box, worker_ids: ['3', 3, 2] }, { ...box, worker_ids: [1] }, emptyBox()] });
    expect(result.boxes.map(item => item.worker_ids)).toEqual([[3, 2], [1], []]);
    expect(emptyBox().worker_ids).toEqual([]);
});

test('box remarks survive draft normalization while legacy and new boxes start with empty remarks', () => {
    const remark = '易碎，请轻放\n到货前联系';
    const result = normalizeIntakeDraft({ boxes: [{ ...box, remark }, box, { ...box, remark: null }] });
    expect(result.boxes.map(item => item.remark)).toEqual([remark, '', '']);
    expect(normalizeIntakeBox({ ...box, remark }).remark).toBe(remark);
    expect(emptyBox().remark).toBe('');
    expect(normalizeIntakeDraft(result)).toEqual(result);
});

test.each(['注', '📦'])('remark validation counts Unicode characters for %s and accepts empty optional remarks', character => {
    const draft = { mark: 'TEST', boxes: [{ ...box, worker_ids: [1], remark: ` ${character.repeat(MAX_INTAKE_REMARK_LENGTH)} ` }] };
    expect(validateIntakeDraft(draft)).toBe('');
    expect(validateIntakeDraft({ ...draft, boxes: [{ ...draft.boxes[0], remark: character.repeat(MAX_INTAKE_REMARK_LENGTH + 1) }] })).toContain('第 1 箱的备注不能超过 512');
    expect(validateIntakeDraft({ ...draft, boxes: [{ ...draft.boxes[0], remark: '' }] })).toBe('');
});

test('upload validation identifies a missing or oversized worker assignment on its own box', () => {
    const draft = { mark: 'TEST', boxes: [{ ...box, worker_ids: [1] }, { ...box, box_number: '2', worker_ids: [] }] };
    expect(validateIntakeDraft(draft)).toContain('第 2 箱');
    expect(validateIntakeDraft({ ...draft, boxes: [draft.boxes[0], { ...draft.boxes[1], worker_ids: [1, 2, 3, 4, 5] }] })).toContain('第 2 箱最多选择 4');
    expect(validateIntakeDraft({ ...draft, boxes: [draft.boxes[0], { ...draft.boxes[1], worker_ids: [2] }] })).toBe('');
});

test('legacy single goods become one detail and explicit multi goods derive their summary and total', () => {
    const legacy = normalizeIntakeDraft({ boxes: [box] }).boxes[0];
    expect(legacy.item_details).toEqual([{ item_name: '鞋', piece_count: 2, customs_code: '' }]);
    const multi = normalizeIntakeBox({ ...box, item_name: '旧摘要', count: 99, item_details: [{ item_name: ' 运动鞋 ', piece_count: 2 }, { item_name: '拖鞋', piece_count: 3 }] });
    expect(multi.item_name).toBe('运动鞋、拖鞋');
    expect(multi.count).toBe(5);
    expect(hasCompleteIntakeItemCounts(multi)).toBe(true);
});

test('legacy multi names and explicit unknown quantities retain the paper total without inventing item counts', () => {
    const legacy = normalizeIntakeBox({ ...box, item_name: '运动鞋、拖鞋，帽子', count: 12, worker_ids: [1] });
    expect(legacy.item_details.map(row => row.piece_count)).toEqual([null, null, null]);
    expect(legacy.item_details.map(row => row.item_name)).toEqual(['运动鞋', '拖鞋', '帽子']);
    expect(legacy.count).toBe(12);
    expect(hasCompleteIntakeItemCounts(legacy)).toBe(false);
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [legacy] })).toContain('第 1 箱第 1 项的件数');
    const partial = normalizeIntakeBox({ ...legacy, item_details: [{ item_name: '运动鞋', piece_count: 2 }, { item_name: '拖鞋', piece_count: null }] });
    expect(partial.count).toBe(12);
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [partial] })).toContain('第 1 箱第 2 项的件数');
});

test('new blank item rows and invalid quantities remain editable but cannot pass confirmation validation', () => {
    expect(emptyBox().item_details).toEqual([{ item_name: '', piece_count: null, customs_code: '' }]);
    const base = { ...box, worker_ids: [1], item_details: [{ item_name: '运动鞋', piece_count: 2 }, { item_name: '', piece_count: 3 }] };
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [base] })).toContain('第 1 箱第 2 项的品名');
    for (const count of [null, '', 0, -1, 1.5, 'abc', true, Number.MAX_SAFE_INTEGER + 1]) {
        expect(validateIntakeDraft({ mark: 'TEST', boxes: [{ ...base, item_details: [{ item_name: '鞋', piece_count: count }] }] })).toContain('件数');
    }
});

test('an explicit empty item list is preserved rather than filled from a stale legacy summary', () => {
    const normalized = normalizeIntakeBox({ ...box, worker_ids: [1], item_details: [] });
    expect(normalized.item_details).toEqual([]);
    expect(normalized.item_name).toBe('');
    expect(normalized.count).toBe(2);
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [normalized] })).toContain('品名不能为空');
});

test('item totals and joined names must fit the persisted cargo fields', () => {
    const overflowingTotal = { ...box, worker_ids: [1], item_details: [{ item_name: '运动鞋', piece_count: 2147483647 }, { item_name: '帽子', piece_count: 1 }] };
    expect(hasCompleteIntakeItemCounts(overflowingTotal)).toBe(false);
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [overflowingTotal] })).toContain('总件数不能超过 2147483647');
    const overlongNames = { ...overflowingTotal, item_details: [{ item_name: '鞋'.repeat(128), piece_count: 1 }, { item_name: '帽'.repeat(128), piece_count: 1 }] };
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [overlongNames] })).toContain('品名合计不能超过 256');
    const tooManyItems = { ...overflowingTotal, item_details: Array.from({ length: 101 }, () => ({ item_name: '鞋', piece_count: 1 })) };
    expect(validateIntakeDraft({ mark: 'TEST', boxes: [tooManyItems] })).toContain('最多填写 100');
});

test('saved numeric strings canonicalize to integer payloads while existing customs codes survive normalization', () => {
    const draft = normalizeIntakeDraft({ mark: 'TEST', boxes: [{ ...box, worker_ids: [1], item_details: [{ item_name: '运动鞋', piece_count: '02', customs_code: '640411' }, { item_name: '帽子', piece_count: '1e2', customs_code: '' }] }] });
    expect(draft.boxes[0].item_details).toEqual([{ item_name: '运动鞋', piece_count: 2, customs_code: '640411' }, { item_name: '帽子', piece_count: 100, customs_code: '' }]);
    expect(draft.boxes[0].count).toBe(102);
    expect(validateIntakeDraft(draft)).toBe('');
    expect(normalizeIntakeDraft(draft)).toEqual(draft);
    expect(normalizeIntakeDraft({ boxes: [{ ...box, count: '02' }] }).boxes[0].item_details[0].piece_count).toBe(2);
});
