import { buildCustomsCodeOptions, findCustomsCodeForName } from './customsCodeLookup';

const records = [
    { name: 'SHOES', code: '6404199000' },
    { name: 'SANDAL', code: '6402992900' },
    { name: 'BAG', code: '4202210090' },
];

test('finds an exact product name without case sensitivity', () => {
    expect(findCustomsCodeForName(records, ' shoes ')).toBe('6404199000');
    expect(findCustomsCodeForName(records, 'unknown')).toBe('');
});

test('builds customs code options filtered by a partial product name', () => {
    expect(buildCustomsCodeOptions(records, 'sh')).toEqual([
        { value: '6404199000', label: '6404199000（SHOES）' },
    ]);
});
