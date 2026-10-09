import { buildGoodsNameGroups } from './GoodName';

test('builds sorted category groups and puts uncategorized names last', () => {
    const groups = buildGoodsNameGroups([
        { name: 'WALLET', category: '鞋包' },
        { name: 'SHIRT', category: '服装' },
        { name: 'BAG', category: '鞋包' },
        { name: 'OTHER', category: null },
    ]);

    expect(groups.map(group => group.label)).toEqual(['服装', '鞋包', '未分类']);
    expect(groups[1].options.map(option => option.value)).toEqual(['BAG', 'WALLET']);
});
