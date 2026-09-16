import {
    calculateBillingWeight,
    calculateOrderBillingWeight,
    calculateReceivable,
} from './receivable';

test('receivable calculation rounds fractional weight up to a whole kilogram', () => {
    expect(calculateBillingWeight(43.2)).toBe(44);
    expect(calculateReceivable(43.2, 10, 5)).toBe(445);
    expect(calculateReceivable(43, 10, 5)).toBe(435);
});

test('order billing weight rounds each package before summing', () => {
    expect(calculateOrderBillingWeight([21.2, 21.2])).toBe(44);
    expect(calculateOrderBillingWeight([10, null, 3.1])).toBe(14);
});
