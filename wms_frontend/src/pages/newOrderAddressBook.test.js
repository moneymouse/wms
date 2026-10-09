import { buildUniqueZipCodeOptions, filterReceiversByZipCode } from './newOrder';

const receivers = [
    { receiver_id: 1, zip_code: '10001' },
    { receiver_id: 2, zip_code: '10001' },
    { receiver_id: 3, zip_code: 10002 },
    { receiver_id: 4, zip_code: ' SW1A  1AA ' },
    { receiver_id: 5, zip_code: 'sw1a 1aa' },
    { receiver_id: 6, zip_code: null },
];

test('address book zip code options are normalized, sorted and deduplicated', () => {
    expect(buildUniqueZipCodeOptions(receivers)).toEqual([
        { label: '10001', value: '10001' },
        { label: '10002', value: '10002' },
        { label: 'SW1A 1AA', value: 'SW1A 1AA' },
    ]);
});

test('address book supports partial and case-insensitive zip code filtering', () => {
    expect(filterReceiversByZipCode(receivers, '1000')).toHaveLength(3);
    expect(filterReceiversByZipCode(receivers, 'sw1a')).toHaveLength(2);
    expect(filterReceiversByZipCode(receivers, '')).toBe(receivers);
});
