import {
    getDefaultSettlementStatus,
    getRemainingReceivableCents,
    getSettlementDifferenceDisplay,
    getSettlementStatus,
} from './receiptSettlement';

test.each([
    ['70.01', 2999, 'settled'],
    ['70.00', 3000, 'unsettled'],
])('the default uses the strict 30 CNY boundary after actual payment %s', (amount, expected, status) => {
    const remaining = getRemainingReceivableCents([
        { uid: 'one', receivable_amount: '120.00', approved_received: '20.00', pending_amount: '15.00' },
    ], { one: amount });
    expect(remaining).toBe(expected);
    expect(getDefaultSettlementStatus(remaining)).toBe(status);
});

test('remaining receivables sum all selected orders without subtracting other pending receipts', () => {
    const remaining = getRemainingReceivableCents([
        { uid: 'one', receivable_amount: 100, approved_received: 20, pending_amount: 15 },
        { uid: 'two', receivable_amount: 200, approved_received: 50, pending_amount: 20 },
    ], { one: 60, two: 130 });
    expect(remaining).toBe(4000);
    expect(getDefaultSettlementStatus(remaining)).toBe('unsettled');
});

test.each([
    [4, 2900, 'settled'],
    [3, 3000, 'unsettled'],
])('prior approved settlement differences count toward the remaining balance for payment %s', (amount, remaining, status) => {
    const balance = getRemainingReceivableCents([
        { uid: 'one', receivable_amount: 165, approved_received: 127, settlement_difference: 5, pending_amount: 10 },
    ], { one: amount });
    expect(balance).toBe(remaining);
    expect(getDefaultSettlementStatus(balance)).toBe(status);
});

test('decimal arithmetic and approved actual income determine zero balance', () => {
    expect(getRemainingReceivableCents([
        { uid: 'one', receivable_amount: 0.3, approved_received: 0.1 },
    ], { one: 0.2 })).toBe(0);
});

test('historic records stay unset and settlement differences distinguish preview and effective amounts', () => {
    expect(getSettlementStatus(null).label).toBe('未设置');
    expect(getSettlementStatus('settled').label).toBe('已结清');
    const item = { settlement_difference: '50.00', preview_settlement_difference: '60.00' };
    expect(getSettlementDifferenceDisplay({ status: 'approved', settlement_status: 'settled' }, item))
        .toEqual({ label: '已生效结清差额', value: '50.00' });
    expect(getSettlementDifferenceDisplay({ status: 'pending', settlement_status: 'settled' }, item))
        .toEqual({ label: '预计结清差额', value: '60.00' });
    expect(getSettlementDifferenceDisplay({ status: 'approved', settlement_status: null }, {}).value).toBeNull();
    expect(getSettlementDifferenceDisplay({ status: 'rejected', settlement_status: 'settled' }, item).value).toBeNull();
    expect(getSettlementDifferenceDisplay({ status: 'pending', settlement_status: 'unsettled' }, item).value).toBeNull();
});
