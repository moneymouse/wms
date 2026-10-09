import { buildParsedAddressValues } from './addressParsing';

test.each([
    ['US', 'USA'],
    [' nl ', 'NETHERLANDS, NL'],
    ['GB', 'UK'],
    ['ES', 'SPAIN'],
    ['RE', 'REUNION'],
    ['CW', 'CURACAO'],
    ['SX', 'ST., XM'],
    ['BL', 'ST., XY'],
])('maps country code %s to its exact existing form option', (code, country) => {
    expect(buildParsedAddressValues({ country: code })).toEqual({ country });
});

test('ignores parsed detailed address, keeps recognized nonempty strings, and preserves postal code leading zeroes', () => {
    expect(buildParsedAddressValues({
        country: 'ZZ',
        province: ' ',
        city: ' Delft ',
        address: ' 10 Main Street ',
        zip_code: ' 01234 ',
        receiver: null,
        receiver_phone: 12345,
        mail: '',
        customer_name: 'Do not replace the order customer',
        warnings: ['Please check'],
    })).toEqual({ city: 'Delft', zip_code: '01234' });
});

test.each([null, undefined, [], 'address'])('ignores malformed parsed data %s', (data) => {
    expect(buildParsedAddressValues(data)).toEqual({});
});
