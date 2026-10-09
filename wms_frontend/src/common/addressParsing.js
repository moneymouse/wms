import countryList from './countryList';

// These options still use legacy carrier codes in the existing country list.
const COUNTRY_VALUE_OVERRIDES = {
    RE: 'REUNION',
    CW: 'CURACAO',
    SX: 'ST., XM',
    BL: 'ST., XY',
};

export const PARSED_ADDRESS_FIELDS = [
    'country', 'province', 'city', 'zip_code',
    'receiver', 'receiver_phone', 'mail',
];

export function buildParsedAddressValues(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {};

    const values = {};
    PARSED_ADDRESS_FIELDS.forEach((field) => {
        if (typeof data[field] !== 'string') return;
        const value = data[field].trim();
        if (!value) return;
        if (field === 'country') {
            const code = value.toUpperCase() === 'UK' ? 'GB' : value.toUpperCase();
            const override = COUNTRY_VALUE_OVERRIDES[code];
            const option = countryList.find((country) => override ? country.value === override : (
                country.label.split(',').pop().trim().toUpperCase() === code ||
                country.value.toUpperCase() === code
            ));
            if (option) values.country = option.value;
        } else {
            values[field] = value;
        }
    });
    return values;
}
