import { getWaybillUploadResult } from './waybillUploadResult';

const saved = { uid: 'cargo-1', order_uid: 'order-1', order_id: 'ORDER-1', transfer_id: 'ORIGINAL-1', waybill_id: 'WB-SHARED' };
const failed = { uid: 'cargo-2', order_uid: 'order-2', order_id: 'ORDER-2', transfer_id: 'ORIGINAL-2', waybill_id: 'WB-SHARED', code: 400, reason: '箱子与订单的客户归属不一致' };

test('partial success identifies failed originals even when they share a saved waybill number', () => {
    const result = getWaybillUploadResult({
        code: 207, msg: '部分订单上传失败，其他订单已保存', cargo_count: 1,
        cargo_list: { 'ORIGINAL-1': 'WB-SHARED', 'ORIGINAL-2': 'WB-SHARED' },
        success_list: [['cargo-1', 'WB-SHARED']], success_items: [saved], failed_list: [failed],
    }, '转单表.xlsx');

    expect(result.savedCount).toBe(1);
    expect(result.failures).toEqual([failed]);
    expect(result.toast.type).toBe('warning');
    expect(result.status).toBe('error');
    const failedLine = result.reportLines.find(line => line.includes('失败原因: 箱子与订单'));
    expect(failedLine).toContain('订单号: ORDER-2；原单号: ORIGINAL-2；转单号: WB-SHARED');
    expect(result.reportLines.some(line => line.includes('订单号: ORDER-1'))).toBe(false);
});

test('success_items counts saved records including unchanged repeated submissions', () => {
    const result = getWaybillUploadResult({
        code: 200, cargo_count: 0, cargo_list: { 'ORIGINAL-1': 'WB-SHARED' },
        success_list: [], success_items: [saved], failed_list: [], tracking_error: null,
    });
    expect(result.savedCount).toBe(1);
    expect(result.failures).toEqual([]);
    expect(result.toast).toEqual({ type: 'success', message: '文件：已保存 1 条' });
    expect(result.status).toBe('done');
});

test('the server failure list is authoritative even if the mapping contains unmatched originals', () => {
    const result = getWaybillUploadResult({
        code: 200, cargo_list: { UNMATCHED: 'WB-OTHER' }, success_items: [], failed_list: [],
    });
    expect(result.failures).toEqual([]);
    expect(result.status).toBe('done');
});

test('all failed records include the order, original, waybill and reason in the report', () => {
    const result = getWaybillUploadResult({ code: 400, msg: '订单上传失败', success_items: [], failed_list: [failed] });
    expect(result.savedCount).toBe(0);
    expect(result.toast.type).toBe('error');
    expect(result.status).toBe('error');
    expect(result.reportLines.join('\n')).toContain('订单号: ORDER-2；原单号: ORIGINAL-2；转单号: WB-SHARED；失败原因: 箱子与订单的客户归属不一致');
});

test.each([502, 500])('tracking code %s preserves saved records and reports tracking separately', code => {
    const result = getWaybillUploadResult({
        code, msg: code === 502 ? '17track rejected' : 'Register Error',
        cargo_list: { 'ORIGINAL-1': 'WB-SHARED' }, success_items: [saved], failed_list: [],
        rejected: code === 502 ? [{ number: 'WB-SHARED' }] : [],
        tracking_error: { code, reason: '追踪服务暂时不可用' },
    });
    expect(result.savedCount).toBe(1);
    expect(result.failures).toEqual([]);
    expect(result.toast.type).toBe('warning');
    expect(result.toast.message).toContain('已保存 1 条，追踪注册失败');
    expect(result.reportLines.join('\n')).toContain('上传失败记录:\n无');
    expect(result.reportLines.join('\n')).toContain('追踪注册失败（已保存记录不会回滚）:\n追踪服务暂时不可用');
});

test('partial save and tracking failures appear independently', () => {
    const result = getWaybillUploadResult({
        code: 207, msg: '部分订单上传失败，其他订单已保存',
        success_items: [saved], failed_list: [failed],
        tracking_error: { code: 500, reason: '追踪服务连接失败' },
    });
    expect(result.failures).toEqual([failed]);
    expect(result.toast.message).toContain('已保存 1 条，1 条未保存，追踪注册失败');
    expect(result.reportLines.join('\n')).toContain('追踪服务连接失败');
});

test('legacy responses still infer unmatched waybills from cargo_list and success_list', () => {
    const result = getWaybillUploadResult({
        code: 200, cargo_count: 1, success_list: [['cargo-1', 'WB-SHARED']],
        cargo_list: { 'ORIGINAL-1': 'WB-SHARED', 'ORIGINAL-2': 'WB-MISSING', 'ORIGINAL-3': false },
    });
    expect(result.savedCount).toBe(1);
    expect(result.failures.map(item => item.transfer_id)).toEqual(['ORIGINAL-2', 'ORIGINAL-3']);
    expect(result.reportLines.join('\n')).toContain('转单号: 转单号未填');
    expect(result.toast.type).toBe('warning');
});

test('legacy tracking failures do not relabel saved records as upload failures', () => {
    const result = getWaybillUploadResult({
        code: 502, msg: '17track rejected', cargo_count: 1,
        success_list: [['cargo-1', 'WB-SHARED']], cargo_list: { 'ORIGINAL-1': 'WB-SHARED' },
        rejected: [{ number: 'WB-SHARED' }],
    });
    expect(result.failures).toEqual([]);
    expect(result.trackingFailed).toBe(true);
    expect(result.toast.type).toBe('warning');
});

test('a request failure before saving is not treated as a tracking failure', () => {
    const result = getWaybillUploadResult({ code: 500, msg: '上传转单号失败: 文件读取失败' });
    expect(result.trackingFailed).toBe(false);
    expect(result.toast.type).toBe('error');
    expect(result.reportLines.join('\n')).toContain('失败原因: 上传转单号失败: 文件读取失败');
});
