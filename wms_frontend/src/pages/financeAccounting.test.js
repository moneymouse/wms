import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FinanceAccounting, { AccountingSetup, AccountingPeriods, AccountingJournals, AccountingReports } from './financeAccounting';

jest.mock('../components/FinanceHistoryDrawer', () => () => null);
jest.mock('./financeRevenue', () => () => <div>履约收入</div>);
const response = data => Promise.resolve({ ok: true, json: async () => ({ code: 200, data }) });
beforeEach(() => {
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(() => response([]));
});
afterEach(() => jest.restoreAllMocks());

test('an unconfigured ledger opens an explicit setup form before accounting actions', async () => {
    global.fetch = jest.fn(() => response({ configured: false, currency: 'CNY' }));
    render(<FinanceAccounting />);
    await screen.findByText('开始建账');
    expect(screen.getByText('建立账簿与初始科目')).toBeInTheDocument();
    expect(screen.queryByText('确认关账')).not.toBeInTheDocument();
});

test('setup sends selected accounting policy and date only after explicit save', async () => {
    const saved = jest.fn();
    render(<AccountingSetup settings={{ configured: false }} onSaved={saved} />);
    fireEvent.change(screen.getByLabelText('账簿主体'), { target: { value: '测试公司' } });
    fireEvent.change(screen.getByLabelText('建账日期'), { target: { value: '2026-10-01' } });
    expect(global.fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('建立账簿与初始科目'));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    const [, options] = global.fetch.mock.calls[0];
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body)).toMatchObject({ company_name: '测试公司', opening_date: '2026-10-01', revenue_policy: 'deferred' });
});

test('a failed closing check disables period close even when a reason is given', async () => {
    global.fetch = jest.fn(url => String(url).includes('/checks') ? response({ can_close: false, checks: [{ key: 'opening', label: '期初未核对', count: 1, passed: false }] }) : response([{ id: 3, name: '十月', date_from: '2026-10-01', date_to: '2026-10-31', status: 'open', version: 1 }]));
    render(<AccountingPeriods revision={0} onChanged={jest.fn()} />);
    fireEvent.click(await screen.findByText('检查与关账'));
    await screen.findByText('期初未核对');
    fireEvent.change(screen.getByLabelText('期间操作依据'), { target: { value: '已检查' } });
    expect(screen.getByRole('button', { name: /确认关账/ })).toBeDisabled();
    expect(global.fetch.mock.calls.every(([, options]) => options.method === 'GET')).toBe(true);
});

test('source journals expose history and cannot be manually reversed', async () => {
    const entry = { id: 8, number: 'JV-SOURCE', entry_date: '2026-10-05', status: 'posted', source_type: 'finance_document', description: '客户账单', total_debit: '100', total_credit: '100', lines: [] };
    global.fetch = jest.fn(() => response({ items: [entry], total: 1 }));
    render(<AccountingJournals revision={0} onChanged={jest.fn()} />);
    fireEvent.click(await screen.findByText('JV-SOURCE'));
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getByText('修改历史')).toBeInTheDocument();
    expect(within(drawer).queryByText('生成冲销凭证')).not.toBeInTheDocument();
    expect(within(drawer).getByText('该凭证由业务单据生成，更正请回到来源账单或收付款。')).toBeInTheDocument();
});

test('report request failure does not render a statement or allow export', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, json: async () => ({ code: 500, msg: '账簿暂不可用' }) }));
    render(<AccountingReports revision={0} />);
    await screen.findByText('账簿暂不可用');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /导出试算表/ })).toBeDisabled();
});

test('report URL restores date ranges, report view, and account filters', async () => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: false, json: async () => ({ code: 500, msg: '报表数据暂不可用' }) }));
    const params = new URLSearchParams({ reportDates: JSON.stringify(['2026-09-01', '2026-09-30']), reportView: 'ledger', reportAccount: '1122' });
    render(<MemoryRouter initialEntries={[`/finance?${params}`]}><AccountingReports revision={0} /></MemoryRouter>);
    await screen.findByText('报表数据暂不可用');
    expect(screen.getByPlaceholderText('Start date')).toHaveValue('2026-09-01');
    expect(screen.getByPlaceholderText('End date')).toHaveValue('2026-09-30');
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const search = new URL(url, 'http://localhost').searchParams;
        return search.get('date_from') === '2026-09-01' && search.get('date_to') === '2026-09-30' && search.get('account_code') === '1122';
    })).toBe(true));
    expect(screen.getByRole('combobox', { name: '报表科目筛选' })).toBeInTheDocument();
});
