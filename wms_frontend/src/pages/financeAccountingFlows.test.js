import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as XLSX from 'xlsx';
import { AccountingPeriods, AccountingReports, BankReconciliation, JournalEditor, OpeningConfirmation, readBankImportFile } from './financeAccounting';

jest.mock('../components/FinanceHistoryDrawer', () => ({ open, historyUrl }) => open ? <div>{historyUrl}</div> : null);
jest.mock('./financeRevenue', () => () => null);
jest.mock('./financeLegacyMigration', () => () => null);
jest.mock('xlsx', () => ({ read: jest.fn(), utils: { sheet_to_json: jest.fn(), decode_range: jest.fn() } }));
const response = data => Promise.resolve({ ok: true, json: async () => ({ code: 200, data }) });
const funds = [{ id: 1, name: '银行甲', account_type: 'bank', active: true }, { id: 2, name: '银行乙', account_type: 'bank', active: true }];
const transactions = [{ id: 11, account_id: 1, reference: '流水甲', transaction_date: '2026-10-05', amount: '100.00', status: 'unmatched', version: 3 }, { id: 12, account_id: 2, reference: '流水乙', transaction_date: '2026-10-05', amount: '100.00', status: 'unmatched', version: 1 }];
const payment = (id, account_id = 1) => ({ id, number: `PAY-${id}`, account_id, partner_name: '客户甲', amount: '100.00', direction: 'incoming', status: 'posted' });
const report = {
    date_from: '2026-10-01', date_to: '2026-10-05', opening_confirmed: true,
    profit_loss: { revenue: '0', expense: '0', profit: '0', items: [] },
    balance_sheet: { difference: '0', assets: '200', liabilities: '0', equity: '200', unclosed_profit: '0', items: [] },
    trial_balance: [{ code: '1002', name: '银行存款', opening: '0', debit: '200', credit: '0', closing: '200' }],
    ledger: [101, 102].map(line_id => ({ line_id, entry_id: 1, entry_number: 'JV-1', account_code: '1002', account_name: '银行存款', debit: '100', credit: '0', entry_date: '2026-10-05' })),
    cashflow: {}, total_debit: '200', total_credit: '200',
};
async function select(label, option) {
    fireEvent.mouseDown(screen.getByRole('combobox', { name: label }));
    const options = await screen.findAllByText(option, { selector: '.ant-select-item-option-content' });
    fireEvent.click(options.find(item => !item.closest('.ant-select-dropdown-hidden')) || options[options.length - 1]);
}
function uploadFile(container, name = '流水.xlsx') {
    const file = new File(['data'], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    file.arrayBuffer = jest.fn(async () => new ArrayBuffer(8));
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } });
}
beforeEach(() => {
    localStorage.clear();
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    XLSX.read.mockReturnValue({ SheetNames: ['Sheet1'], Sheets: { Sheet1: { '!ref': 'A1:D2' } } });
    XLSX.utils.decode_range.mockImplementation(ref => ({ e: { r: Number(ref.split(':').pop().match(/\d+/)[0]) - 1 } }));
    XLSX.utils.sheet_to_json.mockReturnValue([{ 日期: '2026-10-05', 金额: 100, 流水号: 'BANK-1', 说明: '收款' }]);
    global.fetch = jest.fn(url => {
        const path = String(url);
        if (path.includes('/accounting/accounts')) return response([{ code: '1002', name: '银行存款' }, { code: '6602', name: '管理费用' }, { code: '4001', name: '实收资本' }]);
        if (path.includes('/finance/v2/accounts')) return response({ items: funds, total: funds.length });
        if (path.includes('/bank-transactions/preview')) return response({ items: [{ row: 1, transaction_date: '2026-10-05', amount: '100.00', reference: 'BANK-1' }], duplicates: 0 });
        if (path.includes('/bank-transactions/import')) return response({ imported: 1 });
        if (path.includes('/bank-transactions')) return response({ items: transactions, total: transactions.length });
        if (path.includes('/payments')) return response({ items: [payment(1)], total: 1 });
        if (path.includes('/reports/export')) return Promise.resolve({ ok: true, blob: async () => new Blob(['test']) });
        if (path.includes('/reports')) return response(report);
        return response({});
    });
});
afterEach(() => jest.restoreAllMocks());

test('opening confirmation resets on reopen and a pending confirmation cannot close or double submit', async () => {
    let finish;
    global.fetch.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const changed = jest.fn();
    render(<OpeningConfirmation settings={{ version: 4, opening_confirmed: false }} onChanged={changed} />);
    fireEvent.click(screen.getByText('核对期初'));
    fireEvent.change(screen.getByLabelText('期初核对依据'), { target: { value: '已核对银行和往来余额' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }));
    fireEvent.click(screen.getByText('核对期初'));
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByLabelText('期初核对依据')).toHaveValue('');
    expect(screen.getByRole('button', { name: '确认核对完成' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('期初核对依据'), { target: { value: '重新逐项核实期初余额' } });
    fireEvent.click(screen.getByRole('checkbox'));
    const submit = screen.getByRole('button', { name: '确认核对完成' });
    fireEvent.click(submit); fireEvent.click(submit);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: /^取\s*消$/ })).toBeDisabled();
    expect(screen.getByLabelText('期初核对依据')).toBeDisabled();
    await act(async () => finish({ ok: true, json: async () => ({ code: 200, data: { opening_confirmed: true } }) }));
    expect(changed).toHaveBeenCalledTimes(1);
});

test('manual journal rejects imbalance and clears a fund account when changing to an expense account', async () => {
    const saved = jest.fn();
    render(<JournalEditor open onClose={jest.fn()} onSaved={saved} />);
    await waitFor(() => expect(screen.getByRole('button', { name: '保存草稿' })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('摘要'), { target: { value: '管理费用调整' } });
    await select('第 1 行科目', '1002 银行存款');
    await select('第 1 行资金账户', '银行甲');
    await select('第 1 行科目', '6602 管理费用');
    expect(screen.getByRole('combobox', { name: '第 1 行资金账户' })).toBeDisabled();
    await select('第 2 行科目', '4001 实收资本');
    fireEvent.change(screen.getByRole('spinbutton', { name: '第 1 行借方' }), { target: { value: '100' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: '第 2 行贷方' }), { target: { value: '90' } });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(await screen.findByText('借贷金额不平衡，请核对后再保存')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
    fireEvent.change(screen.getByRole('spinbutton', { name: '第 2 行贷方' }), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    const [, options] = global.fetch.mock.calls.find(([, options]) => options.method === 'POST');
    const body = JSON.parse(options.body);
    expect(body.lines[0].account_code).toBe('6602');
    expect(body.lines[0].fund_account_id).toBeUndefined();
    expect(body.lines[0].debit).toBe('100');
});

test('bank import rejects large files before parsing and never silently truncates a large sheet', async () => {
    const file = { size: 5 * 1024 * 1024 + 1, arrayBuffer: jest.fn() };
    await expect(readBankImportFile(file)).rejects.toThrow('文件不能超过 5 MB');
    expect(file.arrayBuffer).not.toHaveBeenCalled();
    XLSX.read.mockReturnValue({ SheetNames: ['Sheet1'], Sheets: { Sheet1: { '!ref': 'A1:D1002', '!fullref': 'A1:D2500' } } });
    await expect(readBankImportFile({ size: 1024, arrayBuffer: async () => new ArrayBuffer(2) })).rejects.toThrow('每次最多导入 1000 行');
});

test('an old bank preview cannot reappear after account change, and import uses the preview account', async () => {
    const original = global.fetch.getMockImplementation();
    let finish;
    global.fetch.mockImplementation((url, options) => String(url).includes('/bank-transactions/preview') && JSON.parse(options.body).account_id === 1
        ? new Promise(resolve => { finish = resolve; }) : original(url, options));
    const { container } = render(<BankReconciliation revision={0} onChanged={jest.fn()} />);
    await select('银行流水资金账户', '银行甲');
    uploadFile(container);
    await waitFor(() => expect(finish).toBeDefined());
    await select('银行流水资金账户', '银行乙');
    await act(async () => finish({ ok: true, json: async () => ({ code: 200, data: { items: [{ row: 1 }], duplicates: 0 } }) }));
    expect(screen.queryByText('导入预览 · 银行甲')).not.toBeInTheDocument();
    uploadFile(container, '流水乙.xlsx');
    expect(await screen.findByText('导入预览 · 银行乙')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认导入' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/bank-transactions/import'))).toBe(true));
    const [, options] = global.fetch.mock.calls.find(([url]) => String(url).includes('/bank-transactions/import'));
    expect(JSON.parse(options.body)).toMatchObject({ account_id: 2, rows: [{ reference: 'BANK-1', amount: '100' }] });
});

test('bank matching requests the selected account on the server and pages beyond the first candidates', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
        if (String(url).includes('/payments?')) {
            const params = new URL(String(url), 'https://example.test').searchParams;
            return response({ items: params.get('p') === '2' ? [payment(999)] : Array.from({ length: 50 }, (_, index) => payment(index + 1)), total: 51 });
        }
        return original(url, options);
    });
    render(<BankReconciliation revision={0} onChanged={jest.fn()} />);
    fireEvent.click((await screen.findAllByText('匹配收付款'))[0]);
    await screen.findByText('已加载 50 / 51 笔资金记录，50 笔金额匹配。');
    const [url] = global.fetch.mock.calls.find(([url]) => String(url).includes('/payments?'));
    const params = new URL(String(url), 'https://example.test').searchParams;
    expect(params.get('account_id')).toBe('1'); expect(params.get('direction')).toBe('incoming');
    fireEvent.click(screen.getByRole('button', { name: '加载更多收付款' }));
    await screen.findByText('已加载 51 / 51 笔资金记录，51 笔金额匹配。');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '匹配收付款候选' }));
    // The candidate is present in the controlled option data even if virtualization omits its visible row.
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('p=2'))).toBe(true);
    expect(screen.queryByRole('button', { name: '加载更多收付款' })).not.toBeInTheDocument();
});

test('a late bank match search from a closed transaction cannot replace the next account candidates', async () => {
    const original = global.fetch.getMockImplementation();
    let finish;
    global.fetch.mockImplementation((url, options) => {
        if (String(url).includes('/payments?')) {
            return String(url).includes('account_id=1') ? new Promise(resolve => { finish = resolve; }) : response({ items: [payment(222, 2)], total: 1 });
        }
        return original(url, options);
    });
    render(<BankReconciliation revision={0} onChanged={jest.fn()} />);
    fireEvent.click((await screen.findAllByText('匹配收付款'))[0]);
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }));
    fireEvent.click(screen.getAllByText('匹配收付款')[1]);
    await screen.findByText('已加载 1 / 1 笔资金记录，1 笔金额匹配。');
    await act(async () => finish({ ok: true, json: async () => ({ code: 200, data: { items: [payment(111)], total: 1 } }) }));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '匹配收付款候选' }));
    expect(await screen.findByText('PAY-222 · 客户甲 · 100.00', { selector: '.ant-select-item-option-content' })).toBeInTheDocument();
    expect(screen.queryByText('PAY-111 · 客户甲 · 100.00')).not.toBeInTheDocument();
});

test('reports use distinct ledger line IDs and omit an unset account from CSV export', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: jest.fn(() => 'blob:test') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: jest.fn() });
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const { container } = render(<AccountingReports revision={0} />);
    await screen.findByText('已过账账簿');
    await select('报表类型', '科目明细');
    expect(container.querySelector('tr[data-row-key="101"]')).toBeInTheDocument();
    expect(container.querySelector('tr[data-row-key="102"]')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /导出试算表/ }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
    const [url] = global.fetch.mock.calls.find(([url]) => String(url).includes('/reports/export?'));
    const params = new URL(String(url), 'https://example.test').searchParams;
    expect(params.has('account_code')).toBe(false); expect(params.toString()).not.toContain('undefined');
});

test('a finance-only user cannot start reopening a closed period', async () => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: ['finance'] }))}.signature`);
    global.fetch.mockImplementation(() => response([{ id: 1, name: '九月', status: 'closed', date_from: '2026-09-01', date_to: '2026-09-30' }]));
    render(<AccountingPeriods revision={0} onChanged={jest.fn()} />);
    expect(await screen.findByText('重开需管理员')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重开期间' })).not.toBeInTheDocument();
});


test('changing a report filter disables export until the new response and keeps the ledger view selected', async () => {
    const original = global.fetch.getMockImplementation();
    let finish;
    global.fetch.mockImplementation((url, options) => String(url).includes('/reports?') && String(url).includes('account_code=1002')
        ? new Promise(resolve => { finish = resolve; }) : original(url, options));
    render(<AccountingReports revision={0} />);
    await screen.findByText('已过账账簿');
    await select('报表类型', '科目明细');
    await select('报表科目筛选', '1002 银行存款');
    await waitFor(() => expect(finish).toBeDefined());
    expect(screen.getByRole('button', { name: /导出试算表/ })).toBeDisabled();
    await act(async () => finish({ ok: true, json: async () => ({ code: 200, data: report }) }));
    expect(screen.getByText('科目明细', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /导出试算表/ })).toBeEnabled();
});

test('period and bank histories use their authorized object-scoped endpoints', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/periods') ? response([{ id: 5, name: '十月', status: 'open' }]) : original(url, options));
    const periods = render(<AccountingPeriods revision={0} onChanged={jest.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /^历\s*史$/ }));
    expect(await screen.findByText('/finance/v2/accounting/periods/5/history')).toBeInTheDocument();
    periods.unmount();
    render(<BankReconciliation revision={0} onChanged={jest.fn()} />);
    fireEvent.click((await screen.findAllByRole('button', { name: /^历\s*史$/ }))[0]);
    expect(await screen.findByText('/finance/v2/accounting/bank-transactions/11/history')).toBeInTheDocument();
});
