import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FinancePartnerStatement, { buildStatementPrintHtml } from './financePartnerStatement';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const statement = {
    company_name: '迅达货运', partner_type: 'customer', partner_id: 2, partner_name: '客户甲', currency: 'CNY',
    date_from: '2026-10-01', date_to: '2026-10-05', opening_balance: '100.00', closing_balance: '-25.00',
    total_increase: '50.00', total_decrease: '175.00', opening_confirmed: false,
    items: [{ entry_id: 1, entry_number: 'JV-001', entry_date: '2026-10-03', description: '客户收款核对', source_type: 'finance_payment', source_id: 9, increase: '50.00', decrease: '175.00', balance: '-25.00' }],
};
async function selectPartner(label = '客户甲') {
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '对账往来单位' }));
    fireEvent.click(await screen.findByText(label, { selector: '.ant-select-item-option-content' }));
}
async function createStatement() {
    await selectPartner();
    fireEvent.click(screen.getByRole('button', { name: /生成对账单/ }));
    return screen.findByRole('region', { name: '往来对账单' });
}
beforeEach(() => {
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    window.localStorage.setItem('jwt', 'demo.finance.token');
    global.fetch = jest.fn(url => {
        const path = String(url);
        if (path.includes('/partners?')) return response({ items: [{ id: 2, name: '客户甲' }, { id: 3, name: '供应商乙' }], total: 2 });
        if (path.includes('/partner-statement/export?')) return Promise.resolve({ ok: true, blob: async () => new Blob(['test'], { type: 'text/csv' }) });
        if (path.includes('/partner-statement?')) return response(statement);
        throw new Error(`Unexpected URL ${path}`);
    });
});
afterEach(() => { jest.restoreAllMocks(); });

test('a statement requires a partner, then shows server balances and the opening basis', async () => {
    render(<FinancePartnerStatement />);
    expect(screen.getByRole('button', { name: /下载 CSV/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /生成对账单/ }));
    expect(await screen.findByText('请选择需要对账的客户或供应商')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/partner-statement?'))).toBe(false);
    const region = await createStatement();
    expect(within(region).getByText('迅达货运')).toBeInTheDocument();
    expect(within(region).getByText('2026-10-01 至 2026-10-05')).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: '期末余额' })).getByText('-25.00')).toBeInTheDocument();
    expect(within(region).getByText('余额为正表示应收，余额为负表示预收或应退。')).toBeInTheDocument();
    expect(within(region).getByText('期初余额尚未核对，本对账单为待核对口径。')).toBeInTheDocument();
    const [url] = global.fetch.mock.calls.find(([url]) => String(url).includes('/partner-statement?'));
    const params = new URL(String(url), 'https://example.test').searchParams;
    expect(params.get('partner_id')).toBe('2');
    expect(params.get('partner_type')).toBe('customer');
    expect(params.get('date_from')).toMatch(/^\d{4}-\d{2}-01$/);
    expect(screen.getByRole('button', { name: /下载 CSV/ })).toBeEnabled();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/partners?') && String(url).includes('include_inactive=1'))).toBe(true);
});

test('switching partner type invalidates the report and ignores a previous pending response', async () => {
    let finish;
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/partner-statement?')
        ? new Promise(resolve => { finish = resolve; }) : original(url, options));
    render(<FinancePartnerStatement />);
    await selectPartner();
    fireEvent.click(screen.getByRole('button', { name: /生成对账单/ }));
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '对账往来类型' }));
    fireEvent.click(await screen.findByText('供应商对账', { selector: '.ant-select-item-option-content' }));
    await act(async () => finish({ ok: true, json: async () => ({ code: 200, data: statement }) }));
    expect(screen.queryByRole('region', { name: '往来对账单' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /下载 CSV/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /打印/ })).toBeDisabled();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/partners?partner_type=vendor'))).toBe(true);
});

test('failed report loading retains an explicit retry and never exposes a printable empty balance', async () => {
    let fail = true;
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/partner-statement?') && fail
        ? Promise.resolve({ ok: false, status: 500, json: async () => ({ code: 500, msg: '账簿查询暂不可用' }) }) : original(url, options));
    render(<FinancePartnerStatement />);
    await selectPartner();
    fireEvent.click(screen.getByRole('button', { name: /生成对账单/ }));
    expect(await screen.findByText('账簿查询暂不可用')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '往来对账单' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /打印/ })).toBeDisabled();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: /^重\s*试$/ }));
    expect(await screen.findByText('JV-001')).toBeInTheDocument();
});

test('CSV downloads use JWT and the displayed date range, while printing includes only the statement', async () => {
    const preview = { document: { write: jest.fn(), close: jest.fn() }, focus: jest.fn(), print: jest.fn() };
    jest.spyOn(window, 'open').mockReturnValue(preview);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: jest.fn(() => 'blob:statement') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: jest.fn() });
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<FinancePartnerStatement />);
    await createStatement();
    fireEvent.click(screen.getByRole('button', { name: /下载 CSV/ }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
    const [url, options] = global.fetch.mock.calls.find(([url]) => String(url).includes('/partner-statement/export?'));
    expect(options.headers['x-token']).toBe('demo.finance.token');
    const params = new URL(String(url), 'https://example.test').searchParams;
    expect(params.get('date_from')).toBe(statement.date_from);
    expect(params.get('date_to')).toBe(statement.date_to);
    expect(params.get('partner_id')).toBe('2');
    fireEvent.click(screen.getByRole('button', { name: /打印/ }));
    expect(preview.print).toHaveBeenCalledTimes(1);
    const html = preview.document.write.mock.calls[0][0];
    expect(html).toContain('JV-001');
    expect(html).toContain('客户甲');
    expect(html).not.toContain('生成对账单');
    expect(html).not.toContain('下载 CSV');
});

test('print output escapes stored text and contains all rows, including beyond the screen page', () => {
    const html = buildStatementPrintHtml({ ...statement, partner_type: 'vendor', partner_name: '<script>bad()</script>', items: Array.from({ length: 25 }, (_, index) => ({ ...statement.items[0], entry_id: index, entry_number: `JV-${index}`, description: 'a < b & "quoted"' })) });
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('a &lt; b &amp; &quot;quoted&quot;');
    expect(html).toContain('JV-24');
    expect(html).toContain('余额为正表示应付，余额为负表示预付或应退。');
    expect(html).toContain('期初余额尚未核对');
});
