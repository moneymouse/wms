// 与手动装箱录入共用的常用品名，服务端品名列表不可用时继续提供提示。
export const COMMON_GOODS_GROUPS = [
    {
        label: '服装类',
        items: ['T-恤', '衬衫', '背心', '布料', '荷兰布', '围巾', '头巾', '帽子', '连衣裙', '女套裙', '童裙', '童套装', '裤子', '牛仔裤', '西服', '卫衣', '休闲服', '运动套装', '毛衣', '毛巾', '枕头', '窗帘', '文胸'],
    },
    {
        label: '鞋包类',
        items: ['运动鞋', '女凉鞋', '男凉鞋', '高跟鞋', '拖鞋', '手提包', '钱包', '卡包', '皮带', '假发', '眼镜'],
    },
    { label: '首饰类', items: ['手镯', '耳环', '戒指', '项链', '铁牌'] },
    { label: '杂项', items: ['不锈钢锅', '不锈钢盆', '陶瓷盆', '陶瓷碗', '耳机'] },
];

export const chineseGoodsNameOptions = COMMON_GOODS_GROUPS.map(group => ({
    label: group.label,
    options: group.items.map(name => ({ label: name, value: name })),
}));
