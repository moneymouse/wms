import * as XLSX from 'xlsx';

import { CustomsCodeExcelError, parseCustomsCodeWorkbook } from './customsCodeExcel';

function workbookBuffer(rows) {
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(rows), 'Codes');
    return XLSX.write(workbook, { type: 'array', bookType: 'xlsx' });
}

test('parses Name and Code columns and ignores unrelated columns', () => {
    const result = parseCustomsCodeWorkbook(workbookBuffer([
        ['Other', 'Code', 'Name'],
        ['x', '6404199000', 'SHOES'],
        ['y', '4202210090', 'BAG'],
    ]));

    expect(result).toEqual({
        sheetName: 'Codes',
        items: [
            { name: 'SHOES', code: '6404199000' },
            { name: 'BAG', code: '4202210090' },
        ],
    });
});

test('accepts case-insensitive headers', () => {
    const result = parseCustomsCodeWorkbook(workbookBuffer([
        [' name ', ' code '],
        ['SHOES', '6404199000'],
    ]));
    expect(result.items).toEqual([{ name: 'SHOES', code: '6404199000' }]);
});

test('rejects missing headers', () => {
    expect(() => parseCustomsCodeWorkbook(workbookBuffer([
        ['Product', 'HS'],
        ['SHOES', '6404199000'],
    ]))).toThrow('Name 和 Code');
});

test('reports incomplete rows with the Excel row number', () => {
    expect.assertions(3);
    try {
        parseCustomsCodeWorkbook(workbookBuffer([
            ['Name', 'Code'],
            ['SHOES', '6404199000'],
            ['BAG', ''],
        ]));
    } catch (error) {
        expect(error).toBeInstanceOf(CustomsCodeExcelError);
        expect(error.row).toBe(3);
        expect(error.message).toContain('Code 不能为空');
    }
});
