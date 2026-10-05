const PENDING_CARGO_STATUSES = new Set([
    '',
    '0',
    'pending',
    'pending_assign',
    'pending_outbound',
    'in_stock',
    'instock',
]);

export const isCargoOutboundOrLater = (record) => {
    const status = record?.status;
    if (typeof status === 'number') return status >= 1;

    const normalized = String(status ?? '').trim();
    if (!normalized) return false;
    const numericStatus = Number(normalized);
    if (!Number.isNaN(numericStatus)) return numericStatus >= 1;
    return !PENDING_CARGO_STATUSES.has(normalized.toLowerCase());
};

export const isBoxIdentityEditable = (box) => !!box
    && box.identity_editable !== false
    && !isCargoOutboundOrLater(box);
