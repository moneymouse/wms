export const SETTLEMENT_OPTIONS = [
    { value: 'settled', label: '已结清' },
    { value: 'unsettled', label: '未结清' },
];

const SETTLEMENT_STATUSES = {
    settled: { label: '已结清', color: 'green' },
    unsettled: { label: '未结清', color: 'orange' },
};

export function getSettlementStatus(status) {
    return Object.prototype.hasOwnProperty.call(SETTLEMENT_STATUSES, status)
        ? SETTLEMENT_STATUSES[status] : { label: '未设置', color: 'default' };
}

export function amountToCents(value) {
    const amount = Number(value || 0);
    return Number.isFinite(amount) ? Math.round((amount + Number.EPSILON) * 100) : 0;
}

export function getRemainingReceivableCents(orders, amounts) {
    return orders.reduce((total, order) => (
        total + amountToCents(order.receivable_amount)
        - amountToCents(order.approved_received) - amountToCents(order.settlement_difference)
        - amountToCents(amounts[order.uid])
    ), 0);
}

export function getDefaultSettlementStatus(remainingCents) {
    return remainingCents < 3000 ? 'settled' : 'unsettled';
}

export function getSettlementDifferenceDisplay(receipt, item = {}) {
    if (receipt.status === 'approved') {
        return { label: '已生效结清差额', value: item.settlement_difference ?? null };
    }
    if (receipt.status === 'pending' && receipt.settlement_status === 'settled') {
        return { label: '预计结清差额', value: item.preview_settlement_difference ?? null };
    }
    return { label: '结清差额（未生效）', value: null };
}
