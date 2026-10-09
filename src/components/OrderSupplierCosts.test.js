import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import OrderSupplierCosts from './OrderSupplierCosts';
import { reconciliationRequest } from '../common/supplierReconciliationApi';

jest.mock('../common/supplierReconciliationApi', () => ({ reconciliationRequest: jest.fn() }));

const costs = {
    confirmed_amount: '100.00', confirmed_net_amount: '90.00', pending_amount: '50.00', total: 2,
    items: [
        { line_id: 1, number: 'BILL-1', document_type: 'vendor_bill', status: 'posted', description: '运费', total_amount: '120.00', source_batch_id: 3, source_row: 2 },
        { line_id: 2, number: 'CREDIT-1', document_type: 'vendor_credit', status: 'posted', description: '运费调减', total_amount: '-20.00' },
    ],
};

beforeEach(() => {
    reconciliationRequest.mockReset();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});

test('shows confirmed net cost, payable fees, pending drafts and signed credit sources separately', async () => {
    reconciliationRequest.mockResolvedValue(costs);
    render(<OrderSupplierCosts orderUid="order-1" />);
    expect(await screen.findByText('90.00 元')).toBeInTheDocument();
    expect(screen.getByText('100.00 元')).toBeInTheDocument();
    expect(screen.getByText('50.00 元')).toBeInTheDocument();
    expect(screen.getByText('-20.00')).toBeInTheDocument();
    expect(screen.getByText('批次 3 / Excel 第 2 行')).toBeInTheDocument();
    expect(reconciliationRequest).toHaveBeenCalledWith('/orders/order-1/costs', expect.objectContaining({ signal: expect.anything() }));
});

test('switching orders prevents an old delayed cost response from appearing on the next order', async () => {
    let resolveOld;
    reconciliationRequest.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
        .mockResolvedValueOnce({ ...costs, confirmed_net_amount: '321.00', items: [], total: 0 });
    const view = render(<OrderSupplierCosts orderUid="old" />);
    view.rerender(<OrderSupplierCosts orderUid="next" />);
    expect(await screen.findByText('321.00 元')).toBeInTheDocument();
    await act(async () => resolveOld({ ...costs, confirmed_net_amount: '999.00' }));
    expect(screen.queryByText('999.00 元')).not.toBeInTheDocument();
    expect(screen.getByText('321.00 元')).toBeInTheDocument();
    expect(reconciliationRequest.mock.calls[0][1].signal.aborted).toBe(true);
});

test('failed costs stay unavailable and can be refreshed instead of displaying zero cost', async () => {
    reconciliationRequest.mockRejectedValueOnce(new Error('成本查询失败')).mockResolvedValueOnce(costs);
    render(<OrderSupplierCosts orderUid="order-1" />);
    expect(await screen.findByText('成本查询失败')).toBeInTheDocument();
    expect(screen.queryByText('0.00 元')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新成本' }));
    expect(await screen.findByText('90.00 元')).toBeInTheDocument();
    expect(screen.queryByText('成本查询失败')).not.toBeInTheDocument();
});

test('identifies whole-order reconciliation without implying a specific package fee', async () => {
    reconciliationRequest.mockResolvedValue({ ...costs, items: [
        { ...costs.items[0], match_type: 'order', source_original_number: 'ORDER-1', source_system_weight: '30.000' },
        { ...costs.items[1], match_type: 'cargo' },
    ] });
    render(<OrderSupplierCosts orderUid="order-1" />);
    expect(await screen.findByText('整单对账')).toBeInTheDocument();
    expect(screen.getByText('包裹对账')).toBeInTheDocument();
    expect(screen.getByText('批次 3 / Excel 第 2 行')).toBeInTheDocument();
});
