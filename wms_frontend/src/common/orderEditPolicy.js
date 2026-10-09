const POLICY_KEYS = [
    'order_fields',
    'transportation',
    'order_weight',
    'salesman',
    'customer_assignment',
    'cargo_content',
    'cargo_weight',
    'box_content',
    'box_weight',
    'tracking_numbers',
    'box_workers',
    'box_membership',
    'archive_or_delete',
];

const denyAll = Object.fromEntries(POLICY_KEYS.map(key => [key, false]));

export function normalizeOrderEditPolicy(policy, { defaults = {} } = {}) {
    const source = policy && typeof policy === 'object' ? policy : defaults;
    return {
        ...denyAll,
        ...Object.fromEntries(POLICY_KEYS.map(key => [key, source[key] === true])),
        fully_outbound: source.fully_outbound === true,
    };
}

export function getBoxEditPolicy(box, packingList, defaults = {}) {
    const orderUid = box?.target_order_uid;
    const policy = box?.edit_policy
        || box?.order_edit_policy
        || packingList?.order_edit_policies?.[orderUid]
        || packingList?.edit_policy_by_order?.[orderUid]
        || (!orderUid ? packingList?.edit_policy : null);
    return normalizeOrderEditPolicy(policy, { defaults });
}

export const ORDER_EDIT_POLICY_KEYS = POLICY_KEYS;
