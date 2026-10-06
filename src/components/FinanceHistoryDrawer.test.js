import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FinanceHistoryDrawer, { AuditChanges } from './FinanceHistoryDrawer';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../common/safeHeader', () => () => ({ 'x-token': 'test' }));
const payload = items => ({ ok: true, json: async () => ({ code: 200, data: { items, total: items.length } }) });
const entry = { id: 1, action: 'receipt_approve', operator_name: '财务小林', operator_role: 'finance', create_date: '2026-10-05 10:00:00', remark: '已核对银行流水', correlation_id: 'transaction-1', changes: [{ field: 'status', before: 'pending', after: 'approved' }, { field: 'items[7].amount', before: '100.00', after: '120.00' }] };
beforeEach(() => {
    window.matchMedia = jest.fn().mockImplementation(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn() }));
    global.fetch = jest.fn().mockResolvedValue(payload([entry]));
});
afterEach(() => jest.restoreAllMocks());

test('renders readable field differences, actor, reason and correlation', async () => {
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    expect(await screen.findByText('通过收款单')).toBeInTheDocument();
    expect(screen.getByText('财务小林')).toBeInTheDocument();
    expect(screen.getByText('已核对银行流水', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('明细[7] · 金额')).toBeInTheDocument();
    expect(screen.getByText('待审核')).toBeInTheDocument();
    expect(screen.getByText('已通过')).toBeInTheDocument();
    expect(screen.getByText('120.00')).toBeInTheDocument();
    expect(screen.getByText('关联号 transaction-1')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith('/api/receipts/7/history?p=1&s=10', expect.objectContaining({ headers: { 'x-token': 'test' } }));
});

test('discloses legacy history gaps without inventing changes', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { items: [], total: 0, history_complete: false, notice: '旧记录可能不完整' } }) });
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    expect(await screen.findByText('旧记录可能不完整')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('暂无已保存的变更记录')).toBeInTheDocument();
});

test('complete history notice is secondary information rather than a warning', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { items: [entry], total: 1, history_complete: true, notice: '本单据已保存完整变更记录' } }) });
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    expect(await screen.findByText('本单据已保存完整变更记录')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('keeps business changes visible and retains technical fields in a secondary disclosure', () => {
    render(<AuditChanges record={{ before_data: null, after_data: { id: 73, created_at: '2026-10-05 10:00:00', updated_at: '2026-10-05 10:00:00', created_by_id: 19, amount: '125.00', document_date: '2026-10-05', customer_name: '客户甲', payment_status: 'partial' } }} />);
    expect(screen.getByText('金额')).toBeInTheDocument();
    expect(screen.getByText('账单日期')).toBeInTheDocument();
    expect(screen.getByText('客户甲')).toBeInTheDocument();
    expect(screen.getByText('核销状态')).toBeInTheDocument();
    expect(screen.getByText('部分结清')).toBeInTheDocument();
    expect(screen.queryByText('创建时间')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('系统字段（4 项）'));
    expect(screen.getByText('创建时间')).toBeInTheDocument();
    expect(screen.getByText('73')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();
});

test('failed request can retry and does not present stale data as a valid result', async () => {
    global.fetch.mockRejectedValueOnce(new Error('连接失败'));
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    expect(await screen.findByText('连接失败')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('通过收款单')).toBeInTheDocument();
    expect(screen.queryByText('连接失败')).not.toBeInTheDocument();
});

test('changing the document cancels the previous request', async () => {
    let resolveOld;
    global.fetch.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const { rerender } = render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const oldSignal = global.fetch.mock.calls[0][1].signal;
    rerender(<FinanceHistoryDrawer open historyUrl="/receipts/8/history" onClose={() => {}} />);
    expect(await screen.findByText('财务小林')).toBeInTheDocument();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { resolveOld(payload([{ ...entry, operator_name: '旧请求操作人' }])); });
    expect(screen.queryByText('旧请求操作人')).not.toBeInTheDocument();
});

test('legacy records fall back to Chinese changed fields', () => {
    render(<AuditChanges record={{ before_data: { amount: 10, status: 'pending' }, after_data: { amount: 12, status: 'pending' } }} />);
    expect(screen.getByText('金额')).toBeInTheDocument();
    expect(screen.queryByText('状态')).not.toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
});

test('groups records by date and keeps time, action and operator together', async () => {
    global.fetch.mockResolvedValue(payload([
        entry,
        { ...entry, id: 2, create_date: '2026-10-05 09:15:00', action: 'receipt_create', operator_name: '业务小周' },
        { ...entry, id: 3, create_date: '2026-10-04 16:30:00', action: 'update' },
    ]));
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    const currentDay = await screen.findByRole('region', { name: '2026-10-05 变更记录' });
    expect(within(currentDay).getAllByRole('article')).toHaveLength(2);
    const earlierDay = screen.getByRole('region', { name: '2026-10-04 变更记录' });
    expect(within(earlierDay).getAllByRole('article')).toHaveLength(1);
    const event = within(currentDay).getAllByRole('article')[0];
    expect(within(event).getByText('10:00:00')).toBeInTheDocument();
    expect(within(event).getByText('通过收款单')).toBeInTheDocument();
    expect(within(event).getByText('财务小林')).toBeInTheDocument();
    expect(within(event).getByText('财务')).toBeInTheDocument();
    expect(screen.queryByText(/每一笔金额的来处/)).not.toBeInTheDocument();
});

test('raw JSON stays collapsed behind the secondary disclosure', () => {
    render(<AuditChanges record={{ before_data: { amount: 10 }, after_data: { amount: 12 } }} />);
    expect(screen.queryByText(/"amount": 10/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('原始记录（JSON）'));
    expect(screen.getByText(/"amount": 10/)).toHaveTextContent('"amount": 12');
});

test('pagination continues to load the requested history page', async () => {
    global.fetch.mockImplementation(async url => ({ ok: true, json: async () => ({
        code: 200, data: { items: [{ ...entry, operator_name: url.includes('p=2') ? '第二页操作人' : '第一页操作人' }], total: 11 },
    }) }));
    render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    await screen.findByText('第一页操作人');
    fireEvent.click(screen.getByTitle('2'));
    expect(await screen.findByText('第二页操作人')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenLastCalledWith('/api/receipts/7/history?p=2&s=10', expect.any(Object));
});

test('closing the drawer cancels its pending history request', async () => {
    global.fetch.mockImplementation(() => new Promise(() => {}));
    const { rerender } = render(<FinanceHistoryDrawer open historyUrl="/receipts/7/history" onClose={() => {}} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const signal = global.fetch.mock.calls[0][1].signal;
    rerender(<FinanceHistoryDrawer open={false} historyUrl="/receipts/7/history" onClose={() => {}} />);
    expect(signal.aborted).toBe(true);
});
