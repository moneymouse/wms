export class GoodsNameTxtParseError extends Error {
    constructor(message, line = null) {
        super(message);
        this.name = 'GoodsNameTxtParseError';
        this.line = line;
    }
}

export function decodeGoodsNameBuffer(buffer, Decoder = TextDecoder) {
    try {
        return {
            text: new Decoder('utf-8', { fatal: true }).decode(buffer),
            encoding: 'UTF-8',
        };
    } catch (utf8Error) {
        try {
            return {
                text: new Decoder('gb18030', { fatal: true }).decode(buffer),
                encoding: 'GB18030',
            };
        } catch (gb18030Error) {
            throw new GoodsNameTxtParseError('文件编码无法识别，请使用 UTF-8 或 GB18030 编码');
        }
    }
}

export function parseGoodsNameTxt(text) {
    const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r\n|\n|\r/);
    const groupMap = new Map();
    const items = [];
    let currentCategory = null;

    lines.forEach((rawLine, index) => {
        const lineNumber = index + 1;
        const line = rawLine.trim();
        if (!line) return;

        if (line.startsWith('#')) {
            const category = line.slice(1).trim();
            if (!category) {
                throw new GoodsNameTxtParseError('子标题不能为空', lineNumber);
            }
            currentCategory = category;
            if (!groupMap.has(category)) groupMap.set(category, []);
            return;
        }

        if (!currentCategory) {
            throw new GoodsNameTxtParseError('品名必须位于一个 #子标题 之后', lineNumber);
        }

        groupMap.get(currentCategory).push(line);
        items.push({ name: line, category: currentCategory });
    });

    if (items.length === 0) {
        throw new GoodsNameTxtParseError('文件中未找到可导入的英文品名');
    }

    return {
        items,
        groups: Array.from(groupMap.entries())
            .filter(([, names]) => names.length > 0)
            .map(([category, names]) => ({ category, names })),
    };
}

export async function readGoodsNameTxtFile(file) {
    const buffer = await file.arrayBuffer();
    const decoded = decodeGoodsNameBuffer(buffer);
    return { ...parseGoodsNameTxt(decoded.text), encoding: decoded.encoding };
}
