import {
    decodeGoodsNameBuffer,
    GoodsNameTxtParseError,
    parseGoodsNameTxt,
} from './goodsNameTxt';

describe('parseGoodsNameTxt', () => {
    test('parses BOM, CRLF, blank lines and repeated categories', () => {
        const result = parseGoodsNameTxt('\uFEFF#鞋包\r\nSHOES\r\n\r\n#服装\r\nSHIRT\r\n#鞋包\r\nSANDAL');

        expect(result.items).toEqual([
            { name: 'SHOES', category: '鞋包' },
            { name: 'SHIRT', category: '服装' },
            { name: 'SANDAL', category: '鞋包' },
        ]);
        expect(result.groups).toEqual([
            { category: '鞋包', names: ['SHOES', 'SANDAL'] },
            { category: '服装', names: ['SHIRT'] },
        ]);
    });

    test('keeps duplicate names so the import API can report them as skipped', () => {
        const result = parseGoodsNameTxt('#鞋包\nSHOES\nshoes');
        expect(result.items).toHaveLength(2);
    });

    test.each([
        ['SHOES\n#鞋包\nSANDAL', 1, '品名必须位于'],
        ['#   \nSHOES', 1, '子标题不能为空'],
    ])('reports invalid content with a line number', (text, line, message) => {
        expect.assertions(3);
        try {
            parseGoodsNameTxt(text);
        } catch (error) {
            expect(error).toBeInstanceOf(GoodsNameTxtParseError);
            expect(error.line).toBe(line);
            expect(error.message).toContain(message);
        }
    });

    test('rejects a file without product names', () => {
        expect(() => parseGoodsNameTxt('#鞋包\n\n')).toThrow('文件中未找到');
    });
});

describe('decodeGoodsNameBuffer', () => {
    test('uses UTF-8 when strict decoding succeeds', () => {
        class Decoder {
            constructor(label) {
                this.label = label;
            }
            decode() {
                return '#鞋包\nSHOES';
            }
        }

        expect(decodeGoodsNameBuffer(new ArrayBuffer(0), Decoder)).toEqual({
            text: '#鞋包\nSHOES',
            encoding: 'UTF-8',
        });
    });

    test('falls back to GB18030 when UTF-8 decoding fails', () => {
        class Decoder {
            constructor(label) {
                this.label = label;
            }
            decode() {
                if (this.label === 'utf-8') throw new TypeError('invalid UTF-8');
                return '#鞋包\nSHOES';
            }
        }

        expect(decodeGoodsNameBuffer(new ArrayBuffer(0), Decoder)).toEqual({
            text: '#鞋包\nSHOES',
            encoding: 'GB18030',
        });
    });
});
