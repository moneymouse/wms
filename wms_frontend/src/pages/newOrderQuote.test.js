import { buildCreateOrderPayload } from './newOrder';

test('quote draft is submitted with the selected salesman only when creating the order', () => {
    const quote = {
        unit_price: 12.5,
        surcharge: 8,
        quote_remark: '首版报价',
    };

    expect(buildCreateOrderPayload({
        salesman_id: '3',
        en_name: 'shoes',
        customer_name: '测试客户',
    }, quote, 4)).toEqual({
        salesman_id: 3,
        en_name: 'SHOES',
        customer_name: '测试客户',
        quote,
    });
});

test('create payload omits quote when no draft was saved', () => {
    expect(buildCreateOrderPayload({ salesman_id: 3 }, null, 4)).toEqual({
        salesman_id: 3,
        en_name: '',
    });
});
