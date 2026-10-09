import { getBoxEditPolicy, normalizeOrderEditPolicy, ORDER_EDIT_POLICY_KEYS } from './orderEditPolicy';

const editableDefaults = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));

test('fully outbound orders retain ordinary edit permissions', () => {
    const policy = normalizeOrderEditPolicy(null, {
        defaults: { ...editableDefaults, fully_outbound: true },
    });
    ORDER_EDIT_POLICY_KEYS.forEach(key => expect(policy[key]).toBe(true));
    expect(policy.fully_outbound).toBe(true);
});

test('obsolete business and financial metadata do not create editing restrictions', () => {
    const policy = normalizeOrderEditPolicy({
        ...editableDefaults,
        lock_status: 'locked',
        revision_open: true,
        financial_locked: true,
        has_receipt_history: true,
    });
    ORDER_EDIT_POLICY_KEYS.forEach(key => expect(policy[key]).toBe(true));
    expect(policy).not.toHaveProperty('lock_status');
    expect(policy).not.toHaveProperty('revision_open');
    expect(policy).not.toHaveProperty('financial_locked');
    expect(policy).not.toHaveProperty('has_receipt_history');
});

test('server permissions remain authoritative and missing permissions fail closed', () => {
    const policy = normalizeOrderEditPolicy({ tracking_numbers: true, box_content: false });
    expect(policy.tracking_numbers).toBe(true);
    expect(policy.box_content).toBe(false);
    expect(policy.box_weight).toBe(false);
});

test('legacy box lock metadata does not suppress role-based fallback permissions', () => {
    const policy = getBoxEditPolicy(
        { target_order_uid: 'order-1', order_lock_status: 'locked' },
        {},
        editableDefaults,
    );
    ORDER_EDIT_POLICY_KEYS.forEach(key => expect(policy[key]).toBe(true));
});
