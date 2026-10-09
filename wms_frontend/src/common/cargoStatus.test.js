import { isBoxIdentityEditable, isBoxOriginalNumberEditable, isCargoOutboundOrLater } from './cargoStatus';

test.each([0, '0', 'pending_outbound', 'in_stock'])('returned box status %s permits original number changes while protecting its box number', status => {
    const box = { status, date: null, identity_editable: false, original_number_editable: true };
    expect(isBoxOriginalNumberEditable(box)).toBe(true);
    expect(isBoxIdentityEditable(box)).toBe(false);
});

test.each([1, '2', 'outbound', 'InTransit_Other'])('outbound status %s protects the original number even with permissive metadata', status => {
    expect(isCargoOutboundOrLater({ status })).toBe(true);
    expect(isBoxOriginalNumberEditable({ status, original_number_editable: true })).toBe(false);
});

test('a current shipment date and an explicit denial protect the original number', () => {
    expect(isBoxOriginalNumberEditable({ status: 0, date: '2026-10-06', original_number_editable: true })).toBe(false);
    expect(isBoxOriginalNumberEditable({ status: 0, identity_editable: true, original_number_editable: false })).toBe(false);
    expect(isBoxOriginalNumberEditable(null)).toBe(false);
});

test('legacy responses fall back to box identity permission', () => {
    expect(isBoxOriginalNumberEditable({ status: 0, identity_editable: false })).toBe(false);
    expect(isBoxOriginalNumberEditable({ status: 0, identity_editable: true })).toBe(true);
    expect(isBoxOriginalNumberEditable({ status: 0 })).toBe(true);
});
