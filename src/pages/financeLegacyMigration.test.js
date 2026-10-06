import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import dayjs from 'dayjs';
import FinanceLegacyMigration from './financeLegacyMigration';
import { financeRequest } from '../common/financeApi';

jest.mock('../common/financeApi', () => ({ financeRequest: jest.fn(), mutationKey: () => 'legacy-command-key', money: value => Number(value || 0).toFixed(2) }));
jest.mock('../components/FinanceHistoryDrawer', () => () => null);
const today = dayjs().format('YYYY-MM-DD');
const settings = { configured: true, opening_date: today, opening_confirmed: false };
const snapshot = { order_uid: 'order-7', order_number: 'OLD-007', customer_id: 3, customer_name: '旧账客户', cutoff_date: today, snapshot_at: `${today} 10:00:00`, source_hash: 'verified-source-hash', source: { receivable_amount: '200.00', received_amount: '80.00', settlement_difference: '0.00', signed_balance: '120.00', receipts: [] }, import_kind: 'receivable', amount: '120.00', can_import: true, blockers: [] };
const link = { id: 11, version: 1, order_uid: 'order-7', order_number: 'OLD-007', customer_id: 3, customer_name: '旧账客户', cutoff_date: today, import_kind: 'receivable', amount: '120.00', document_id: 77, imported_at: `${today} 10:00:00`, drift: false, status: 'current', current_source_hash: 'verified-source-hash', current_preview: snapshot, delta: { receivable_amount: '0.00', received_amount: '0.00', settlement_difference: '0.00', signed_balance: '0.00' } };
function mockApi(preview = snapshot, saved = link) {
    financeRequest.mockImplementation(async (path, options) => {
        if (path === '/legacy/orders') return { items: [{ order_uid: 'order-7', order_number: 'OLD-007', customer_name: '旧账客户' }], total: 1 };
        if (path === '/legacy/preview') return preview;
        if (path === '/legacy/import') return saved;
        if (path === '/legacy/links') return { items: [saved], total: 1 };
        if (path === '/legacy/links/11') return saved;
        if (path === '/legacy/links/11/acknowledge') return { ...saved, status: 'current', drift: false };
        if (path === '/accounts') return { items: [{ id: 9, name: '公司银行' }], total: 1 };
        if (path === '/documents' || path === '/payments') return { items: [], total: 0 };
        throw new Error(`Unhandled ${path} ${options?.method || 'GET'}`);
    });
}
beforeEach(() => {
    window.matchMedia = jest.fn().mockImplementation(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn() }));
    financeRequest.mockReset(); mockApi();
});
async function previewOrder() {
    await screen.findByText('OLD-007');
    fireEvent.click(screen.getByRole('button', { name: /预览余额/ }));
    await screen.findByText('旧账净余额');
}
async function confirm() {
    fireEvent.change(screen.getByLabelText('核对依据'), { target: { value: '已按客户对账清单核对' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '我已核对来源和净余额，确认历史收款不会重复入账。' }));
    fireEvent.click(screen.getByRole('button', { name: /确认接入期初/ }));
}

test('preview requires explicit confirmation and sends source fingerprint without replaying old receipts', async () => {
    render(<FinanceLegacyMigration settings={settings} />);
    await previewOrder();
    fireEvent.click(screen.getByRole('button', { name: /确认接入期初/ }));
    expect(await screen.findByText('请填写余额核对依据')).toBeInTheDocument();
    expect(financeRequest.mock.calls.filter(([path]) => path === '/legacy/import')).toHaveLength(0);
    await confirm();
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/import', expect.objectContaining({ method: 'POST', body: { order_uid: 'order-7', cutoff_date: today, source_hash: 'verified-source-hash', reason: '已按客户对账清单核对', confirmed: true, idempotency_key: 'legacy-command-key' } })));
    expect(await screen.findByText('新账期初基线')).toBeInTheDocument();
});

test('pending finance activity blocks import and displays the concrete reason', async () => {
    mockApi({ ...snapshot, can_import: false, blockers: ['该订单存在待审核收款单'] });
    render(<FinanceLegacyMigration settings={settings} />);
    await previewOrder();
    expect(screen.getByText('该订单存在待审核收款单')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /确认接入期初/ })).toBeDisabled();
});

test('advance migration requires an explicit original fund account', async () => {
    mockApi({ ...snapshot, import_kind: 'advance', amount: '20.00', source: { ...snapshot.source, signed_balance: '-20.00' } });
    render(<FinanceLegacyMigration settings={settings} />);
    await previewOrder();
    await confirm();
    expect(await screen.findByText('请选择原收款对应的账户')).toBeInTheDocument();
    expect(financeRequest.mock.calls.some(([path]) => path === '/legacy/import')).toBe(false);
    fireEvent.mouseDown(screen.getByLabelText('原预收款对应资金账户'));
    fireEvent.click(await screen.findByText('公司银行'));
    fireEvent.click(screen.getByRole('button', { name: /确认接入期初/ }));
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/import', expect.objectContaining({ body: expect.objectContaining({ account_id: 9 }) })));
});

test('a source conflict keeps the preview visible for a deliberate refresh', async () => {
    mockApi();
    const normal = financeRequest.getMockImplementation();
    financeRequest.mockImplementation((path, options) => path === '/legacy/import' ? Promise.reject(new Error('来源已变化，请重新预览')) : normal(path, options));
    render(<FinanceLegacyMigration settings={settings} />);
    await previewOrder();
    await confirm();
    expect(await screen.findByText('来源已变化，请重新预览')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新读取并核对' }));
    await waitFor(() => expect(financeRequest.mock.calls.filter(([path]) => path === '/legacy/preview')).toHaveLength(2));
    expect(await screen.findByRole('checkbox')).not.toBeChecked();
});

test('source drift is shown separately from the preserved opening baseline and can be reconciled with a reason', async () => {
    const drifted = { ...link, drift: true, status: 'reconciliation_required', current_source_hash: 'new-source-hash' };
    mockApi(snapshot, drifted);
    render(<FinanceLegacyMigration settings={settings} />);
    fireEvent.click(screen.getByRole('tab', { name: '已接入与差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '核对差异' }));
    expect(await screen.findByText('原订单在接入后发生变化')).toBeInTheDocument();
    expect(screen.getByText('新账期初基线')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '登记差异处理依据' }));
    fireEvent.change(screen.getByLabelText('核对结果与处理说明'), { target: { value: '订单备注更正，金额无需调整' } });
    fireEvent.click(screen.getByRole('button', { name: '核对并保存' }));
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/links/11/acknowledge', expect.objectContaining({ body: { version: 1, source_hash: 'new-source-hash', reason: '订单备注更正，金额无需调整', related_document_ids: [], related_payment_ids: [], idempotency_key: 'legacy-command-key' } })));
});

test('monetary drift requires both matching invoice and cash evidence before acknowledgment', async () => {
    const drifted = { ...link, drift: true, status: 'reconciliation_required', current_source_hash: 'money-source-hash', delta: { receivable_amount: '20.00', received_amount: '10.00', settlement_difference: '0.00', signed_balance: '10.00' } };
    mockApi(snapshot, drifted);
    const normal = financeRequest.getMockImplementation();
    financeRequest.mockImplementation((path, options) => {
        if (path === '/documents') return Promise.resolve({ items: [{ id: 81, number: 'INV-ADJUST', document_type: 'customer_invoice', total_amount: '20.00', is_opening: false }] });
        if (path === '/payments') return Promise.resolve({ items: [{ id: 91, number: 'PAY-ADJUST', direction: 'incoming', amount: '10.00', is_opening: false }] });
        return normal(path, options);
    });
    render(<FinanceLegacyMigration settings={settings} />);
    fireEvent.click(screen.getByRole('tab', { name: '已接入与差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '核对差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '登记差异处理依据' }));
    fireEvent.change(screen.getByLabelText('核对结果与处理说明'), { target: { value: '补收差价已经新账登记' } });
    fireEvent.click(screen.getByRole('button', { name: '核对并保存' }));
    expect(await screen.findByText('请选择处理应收变化的新账单或贷项')).toBeInTheDocument();
    expect(financeRequest.mock.calls.some(([path]) => path.endsWith('/acknowledge'))).toBe(false);
    fireEvent.mouseDown(screen.getByLabelText('对应的新账单或贷项'));
    fireEvent.click(await screen.findByText('INV-ADJUST · 账单 · ¥ 20.00'));
    fireEvent.mouseDown(screen.getByLabelText('对应的新收款或退款'));
    fireEvent.click(await screen.findByText('PAY-ADJUST · 收款 · ¥ 10.00'));
    fireEvent.click(screen.getByRole('button', { name: '核对并保存' }));
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/links/11/acknowledge', expect.objectContaining({ body: expect.objectContaining({ related_document_ids: [81], related_payment_ids: [91], source_hash: 'money-source-hash' }) })));
});

test('invalidated cash evidence requires replacement even when the old source amount has not changed', async () => {
    const drifted = { ...link, drift: true, status: 'reconciliation_required', required_document_amount: '0.00', required_payment_amount: '25.00' };
    mockApi(snapshot, drifted);
    render(<FinanceLegacyMigration settings={settings} />);
    fireEvent.click(screen.getByRole('tab', { name: '已接入与差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '核对差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '登记差异处理依据' }));
    expect(screen.getByText(/收款净变化 ¥ 25.00/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('核对结果与处理说明'), { target: { value: '原资金凭据已冲销' } });
    fireEvent.click(screen.getByRole('button', { name: '核对并保存' }));
    expect(await screen.findByText('请选择处理收款变化的新收款或退款')).toBeInTheDocument();
    expect(financeRequest.mock.calls.some(([path]) => path.endsWith('/acknowledge'))).toBe(false);
});

test('revoking a permitted import requires a reason and preserves the record', async () => {
    const active = { ...link, link_status: 'active', can_revoke: true, revoke_blockers: [] };
    mockApi(snapshot, active);
    const normal = financeRequest.getMockImplementation();
    financeRequest.mockImplementation((path, options) => path === '/legacy/links/11/revoke' ? Promise.resolve({ ...active, link_status: 'revoked' }) : normal(path, options));
    render(<FinanceLegacyMigration settings={settings} />);
    fireEvent.click(screen.getByRole('tab', { name: '已接入与差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看记录' }));
    fireEvent.click(await screen.findByRole('button', { name: '撤销接入' }));
    expect(screen.getByRole('button', { name: '撤销并保留历史' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('撤销原因'), { target: { value: '切换余额核对有误' } });
    fireEvent.click(screen.getByRole('button', { name: '撤销并保留历史' }));
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/links/11/revoke', { method: 'POST', body: { version: 1, reason: '切换余额核对有误', idempotency_key: 'legacy-command-key' } }));
});

test('dashboard navigation opens the drift queue directly', async () => {
    render(<FinanceLegacyMigration settings={settings} initialTab="links" sectionToken={1} />);
    expect(screen.getByRole('tab', { name: '已接入与差异' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(financeRequest).toHaveBeenCalledWith('/legacy/links', expect.objectContaining({ params: expect.objectContaining({ status: 'drift', p: 1 }) })));
});

test('opening the new ledger closes the migration drawer before leaving the tab', async () => {
    const onOpenLedger = jest.fn();
    render(<FinanceLegacyMigration settings={settings} onOpenLedger={onOpenLedger} />);
    fireEvent.click(screen.getByRole('tab', { name: '已接入与差异' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看记录' }));
    fireEvent.click(await screen.findByRole('button', { name: '前往新账处理' }));
    expect(onOpenLedger).toHaveBeenCalledWith({ documentId: 77, paymentId: undefined, partnerId: 3 });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '接入记录与来源核对' })).not.toBeInTheDocument());
});
