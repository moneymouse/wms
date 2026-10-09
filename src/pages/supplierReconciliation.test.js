import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SupplierReconciliation from './supplierReconciliation';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const batch = { id: 2, version: 3, number: 'REC-002', vendor_id: 3, vendor_name: '极飞', period: '2026-10', filename: '极飞对账.xlsx', created_by_name: '文员甲', summary: { total_rows: 2, passed_rows: 1, exception_rows: 1, total_valid_amount: '150.00', passed_amount: '100.00' }, documents: [{ id: 7, number: 'BILL-007', status: 'draft', total_amount: '100.00' }] };
const passedRow = { id: 1, source_row: 2, original_number: 'OLD-001', waybill_number: 'NEW-001', system_waybill: 'NEW-001', weight: '10.000', system_weight: '10.000', weight_difference: '0', final_fee: '100.00', description: '运费', status: 'passed', issues: [], cargo_uid: 'cargo-1', match_type: 'cargo', order_uid: 'order-1', order_number: 'XD-001' };
const badRow = { id: 2, source_row: 3, original_number: 'OLD-002', waybill_number: 'NEW-002', weight: '12.000', system_weight: '10.000', weight_difference: '2.000', final_fee: '50.00', status: 'exception', issues: [{ code: 'weight_mismatch', message: '重量不一致：系统实重 10 kg，账单重量 12 kg' }] };
const detail = { batch, rows: { items: [passedRow, badRow], total: 2, page: 1, page_size: 20 } };
function renderPage(props = {}) { return render(<MemoryRouter><SupplierReconciliation {...props} /></MemoryRouter>); }
async function chooseVendor() {
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '对账供应商' }));
    fireEvent.click(await screen.findByText('极飞', { selector: '.ant-select-item-option-content' }));
}
function chooseFile(name = '极飞对账.xlsx') { fireEvent.change(screen.getByLabelText('上传账单文件'), { target: { files: [new File(['xlsx'], name)] } }); }

beforeEach(() => {
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    const payload = window.btoa(JSON.stringify({ user_id: 5, roles: ['clerk'] }));
    localStorage.setItem('jwt', `header.${payload}.signature`);
    global.fetch = jest.fn((url, options) => {
        const path = String(url);
        if (path.includes('/vendors?')) return response({ items: [{ id: 3, name: '极飞' }], total: 1 });
        if (options?.method === 'POST' && path.endsWith('/batches')) return response(detail);
        if (path.includes('/batches/2?')) {
            const onlyBad = path.includes('row_status=exception');
            return response(onlyBad ? { ...detail, rows: { ...detail.rows, items: [badRow], total: 1 } } : detail);
        }
        if (path.includes('/batches?')) return response({ items: [batch], total: 1 });
        throw new Error(`Unexpected URL ${path}`);
    });
});
afterEach(() => { jest.restoreAllMocks(); localStorage.clear(); });

test('weight guidance states the lower-only allowance and the signed difference including both bounds', async () => {
    renderPage();
    expect(screen.getByText(/上传重量须不超过系统实重，且最多比实重少 0.5 kg/)).toBeInTheDocument();
    expect(screen.getByText(/允许范围为 -0.5 至 0 kg（含边界）/)).toBeInTheDocument();
    expect(screen.getByText(/上传重量必须小于订单总实重，最多少 5 kg/)).toBeInTheDocument();
    expect(screen.getByText(/重量差允许 -5 至 0 kg（不含 0）/)).toBeInTheDocument();
    expect(screen.queryByText(/0.001 kg/)).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    const rows = await screen.findByRole('table', { name: '对账明细' });
    expect(within(rows).getByRole('columnheader', { name: '重量差（上传−实重）' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('region', { name: '批次对账结果' })).toHaveAttribute('aria-busy', 'false'));
});

test('distinguishes whole-order fees and total weights from package reconciliation', async () => {
    const orderRow = { ...passedRow, id: 3, source_row: 4, original_number: 'ORDER-WHOLE',
        cargo_uid: null, match_type: 'order', system_weight_scope: 'order_total',
        weight: '28.000', system_weight: '30.000', weight_difference: '-2.000',
        waybill_number: '供应商整单参考号', system_waybill: null, order_uid: 'whole-order', order_number: 'ORDER-WHOLE' };
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/batches/2?')
        ? response({ ...detail, rows: { ...detail.rows, items: [passedRow, orderRow] } }) : original(url, options));
    renderPage({ readOnly: true });
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    const table = await screen.findByRole('table', { name: '对账明细' });
    expect(within(table).getByText('包裹级')).toBeInTheDocument();
    expect(within(table).getByText('订单级')).toBeInTheDocument();
    expect(within(table).getByText('30.000 kg（订单总重）')).toBeInTheDocument();
    expect(within(table).getByText('订单级不按包裹核对')).toBeInTheDocument();
    expect(within(table).getByText('供应商整单参考号')).toBeInTheDocument();
    expect(within(table).getByRole('link', { name: 'ORDER-WHOLE' })).toHaveAttribute('href', '/orders/whole-order');
});

test('validates inputs, uploads one supplier/month file, and shows draft costs and excluded anomalies', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /上传并对账/ }));
    expect(await screen.findByText('请选择供应商、账期并上传 Excel 文件')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
    await chooseVendor();
    chooseFile();
    expect(await screen.findByText('极飞对账.xlsx', { selector: 'span' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /上传并对账/ }));
    expect(await screen.findByText('对账完成，已生成供应商应付账单草稿，等待财务审核确认。')).toBeInTheDocument();
    const rows = await screen.findByRole('table', { name: '对账明细' });
    expect(within(rows).getByText('OLD-001')).toBeInTheDocument();
    expect(within(rows).getByText('重量不一致：系统实重 10 kg，账单重量 12 kg')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: '通过费用' })).getByText('100.00')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: '暂未计入费用' })).getByText('50.00')).toBeInTheDocument();
    expect(screen.getByText(/BILL-007（草稿）/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'XD-001' })).toHaveAttribute('href', '/orders/order-1');
    expect(screen.queryByRole('link', { name: '查看财务账单' })).not.toBeInTheDocument();
    const [, options] = global.fetch.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(options.body.get('vendor_id')).toBe('3');
    expect(options.body.get('period')).toMatch(/^\d{4}-\d{2}$/);
    expect(options.body.get('file').name).toBe('极飞对账.xlsx');
    expect(global.fetch.mock.calls.some(([url]) => /\/post$/.test(String(url)))).toBe(false);
    await waitFor(() => expect(screen.getByRole('region', { name: '批次对账结果' })).toHaveAttribute('aria-busy', 'false'));
    await waitFor(() => expect(screen.getByRole('region', { name: '对账历史记录' })).toHaveAttribute('aria-busy', 'false'));
});

test('finance view reads history and filters anomalies without loading upload options', async () => {
    localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ roles: ['finance'] }))}.signature`);
    renderPage({ readOnly: true });
    expect(screen.queryByRole('button', { name: /上传并对账/ })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    await screen.findByText('OLD-001');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '对账明细范围' }));
    fireEvent.click(await screen.findByText('仅异常明细', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(screen.queryByText('OLD-001')).not.toBeInTheDocument());
    expect(screen.getByText('OLD-002')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看财务账单' })).toHaveAttribute('href', '/finance');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/vendors'))).toBe(false);
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('row_status=exception'))).toBe(true);
});

test('failed uploads keep the chosen file and never show success or an empty draft', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => options?.method === 'POST' ? Promise.resolve({ ok: false, status: 400, json: async () => ({ code: 400, msg: '缺少必填列：最终费用(元)' }) }) : original(url, options));
    renderPage();
    await chooseVendor(); chooseFile(); fireEvent.click(screen.getByRole('button', { name: /上传并对账/ }));
    expect(await screen.findByText('缺少必填列：最终费用(元)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /上传并对账/ })).toBeEnabled();
    expect(screen.getByText('极飞对账.xlsx', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '通过费用' })).not.toBeInTheDocument();
});

test('ignores an old batch response after selecting a newer history record', async () => {
    let finishOld;
    const second = { ...batch, id: 3, number: 'REC-003', filename: '最新对账.xlsx' };
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
        if (String(url).includes('/batches?')) return response({ items: [batch, second], total: 2 });
        if (String(url).includes('/batches/2?')) return new Promise(resolve => { finishOld = resolve; });
        if (String(url).includes('/batches/3?')) return response({ batch: second, rows: { items: [], total: 0 } });
        return original(url, options);
    });
    renderPage({ readOnly: true });
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    await waitFor(() => expect(finishOld).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'REC-003' }));
    await screen.findByText('REC-003 · 极飞 · 2026-10');
    await act(async () => finishOld({ ok: true, json: async () => ({ code: 200, data: detail }) }));
    expect(screen.getByText('REC-003 · 极飞 · 2026-10')).toBeInTheDocument();
    expect(screen.queryByText('OLD-001')).not.toBeInTheDocument();
});

test('reselecting an open history record reloads its detail', async () => {
    renderPage({ readOnly: true });
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    await screen.findByText('OLD-001');
    fireEvent.click(screen.getByRole('button', { name: 'REC-002' }));
    await screen.findByText('OLD-001');
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/batches/2?'))).toHaveLength(2);
    await waitFor(() => expect(screen.getByRole('region', { name: '批次对账结果' })).toHaveAttribute('aria-busy', 'false'));
    await waitFor(() => expect(screen.getByRole('region', { name: '对账历史记录' })).toHaveAttribute('aria-busy', 'false'));
});

test('rechecks exceptions using the batch version and preserves an existing posted bill', async () => {
    const original = global.fetch.getMockImplementation();
    const posted = { ...batch.documents[0], status: 'posted' };
    const existing = { ...detail, batch: { ...batch, documents: [posted] } };
    const additional = { id: 8, number: 'BILL-008', status: 'draft', total_amount: '50.00' };
    const corrected = { ...detail, batch: { ...existing.batch, version: 4, summary: { ...batch.summary, passed_rows: 2, exception_rows: 0, passed_amount: '150.00' }, documents: [posted, additional] }, rows: { ...detail.rows, items: [passedRow, { ...badRow, status: 'passed', issues: [] }] } };
    let current = existing;
    global.fetch.mockImplementation((url, options) => {
        if (String(url).endsWith('/batches/2/reconcile')) { current = corrected; return response(corrected); }
        if (String(url).includes('/batches/2?')) return response(current);
        return original(url, options);
    });
    renderPage(); fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    await screen.findByText('OLD-001');
    await waitFor(() => expect(screen.getByRole('button', { name: '重新核对异常' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '重新核对异常' }));
    expect(await screen.findByText('重新核对完成，新增 1 行通过，已生成追加应付草稿。')).toBeInTheDocument();
    const [, options] = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/batches/2/reconcile'));
    expect(JSON.parse(options.body)).toEqual({ version: 3 });
    expect(screen.getByText(/BILL-007（已生效）、BILL-008（草稿）/)).toBeInTheDocument();
    expect(screen.getByText('OLD-001')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重新核对异常' })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => /\/post$/.test(String(url)))).toBe(false);
    await waitFor(() => expect(screen.getByRole('region', { name: '批次对账结果' })).toHaveAttribute('aria-busy', 'false'));
    await waitFor(() => expect(screen.getByRole('region', { name: '对账历史记录' })).toHaveAttribute('aria-busy', 'false'));
});

test('shows invalid original cell text while excluding an invalid fee from the summary', async () => {
    const invalidRow = { ...badRow, original_number: '', waybill_number: '', weight: null, final_fee: null,
        raw_values: { 原单号: '=100+1', 转单号: '   ', '重量(kg)': '十公斤', '最终费用(元)': '=SUM(1,2)' },
        issues: [{ code: 'invalid_weight', message: '重量必须是数字' }, { code: 'invalid_fee', message: '最终费用不能是公式' }] };
    const invalidDetail = { ...detail, batch: { ...batch, summary: { ...batch.summary, total_valid_amount: '100.00' } }, rows: { ...detail.rows, items: [passedRow, invalidRow] } };
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/batches/2?') ? response(invalidDetail) : original(url, options));
    renderPage({ readOnly: true });
    fireEvent.click(await screen.findByRole('button', { name: 'REC-002' }));
    const rows = await screen.findByRole('table', { name: '对账明细' });
    expect(within(rows).getByText('无效值：=100+1')).toBeInTheDocument();
    expect(within(rows).getByText('无效值：十公斤')).toBeInTheDocument();
    expect(within(rows).getByText('无效值：=SUM(1,2)')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: '正数费用总额' })).getByText('100.00')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: '暂未计入费用' })).getByText('0.00')).toBeInTheDocument();
    expect(screen.queryByText('无效值：   ')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('region', { name: '批次对账结果' })).toHaveAttribute('aria-busy', 'false'));
});
