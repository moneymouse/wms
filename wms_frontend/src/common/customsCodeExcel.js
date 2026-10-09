import * as XLSX from 'xlsx';

export class CustomsCodeExcelError extends Error {
    constructor(message, row = null) {
        super(message);
        this.name = 'CustomsCodeExcelError';
        this.row = row;
    }
}

export function parseCustomsCodeWorkbook(buffer) {
    let workbook;
    try {
        workbook = XLSX.read(buffer, { type: 'array' });
    } catch (error) {
        throw new CustomsCodeExcelError('Excel 文件无法读取');
    }

    const firstSheetName = workbook.SheetNames[0];
    if (!firstSheetName) throw new CustomsCodeExcelError('Excel 文件中没有工作表');

    const rows = XLSX.utils.sheet_to_json(workbook.Sheets[firstSheetName], {
        header: 1,
        raw: false,
        defval: '',
    });
    if (rows.length === 0) throw new CustomsCodeExcelError('Excel 文件内容为空');

    const headers = rows[0].map(value => String(value || '').trim().toLowerCase());
    const nameIndex = headers.indexOf('name');
    const codeIndex = headers.indexOf('code');
    if (nameIndex < 0 || codeIndex < 0) {
        throw new CustomsCodeExcelError('第一行必须包含 Name 和 Code 两个列名', 1);
    }

    const items = [];
    rows.slice(1).forEach((row, index) => {
        const excelRow = index + 2;
        const name = String(row[nameIndex] || '').trim();
        const code = String(row[codeIndex] || '').trim();
        if (!name && !code) return;
        if (!name) throw new CustomsCodeExcelError('Name 不能为空', excelRow);
        if (!code) throw new CustomsCodeExcelError('Code 不能为空', excelRow);
        items.push({ name, code });
    });

    if (items.length === 0) throw new CustomsCodeExcelError('Excel 中没有可导入的数据');
    return { sheetName: firstSheetName, items };
}

export async function readCustomsCodeExcelFile(file) {
    return parseCustomsCodeWorkbook(await file.arrayBuffer());
}
