export function findCustomsCodeForName(records, itemName) {
    const normalizedName = String(itemName || '').trim().toLocaleLowerCase();
    if (!normalizedName) return '';
    const matched = (records || []).find(
        record => String(record?.name || '').trim().toLocaleLowerCase() === normalizedName
    );
    return String(matched?.code || '').trim();
}

export function buildCustomsCodeOptions(records, itemName) {
    const keyword = String(itemName || '').trim().toLocaleLowerCase();
    return (records || [])
        .filter(record => !keyword || String(record?.name || '').toLocaleLowerCase().includes(keyword))
        .map(record => ({
            value: String(record.code || ''),
            label: `${record.code}（${record.name}）`,
        }));
}
