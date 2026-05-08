import {AutoComplete} from "antd";
import React, {useEffect, useState} from "react";
import {endpoint} from "../config";
import getSafeHeader from "../common/safeHeader";

function groupByChannel(modes) {
    const groups = {};
    modes.forEach(m => {
        const group = m.channel_group || '其他';
        if (!groups[group]) groups[group] = [];
        groups[group].push({ label: m.name, value: m.name });
    });
    return Object.entries(groups).map(([label, options]) => ({ label, options }));
}

function filterGrouped(groups, keyword) {
    const lower = keyword.toLowerCase();
    return groups
        .map(g => ({
            label: g.label,
            options: g.options.filter(o => o.label.toLowerCase().includes(lower))
        }))
        .filter(g => g.options.length > 0);
}

export default function ({onChange, onBlur, onEnter, defaultValue}) {
    const [transferOptions, setTransferOptions] = useState([])
    const [allGrouped, setAllGrouped] = useState([])

    useEffect(() => {
        (async () => {
            try {
                const res = await (await fetch(`${endpoint}/transportation-modes`, {
                    headers: getSafeHeader()
                })).json();
                if (res.code === 200 && Array.isArray(res.data)) {
                    const grouped = groupByChannel(res.data);
                    setAllGrouped(grouped);
                    setTransferOptions(grouped);
                }
            } catch (e) {
                console.error('获取运输方式失败:', e);
            }
        })();
    }, []);

    return (<AutoComplete
        onSearch={(value => {
            if (value !== '') {
                setTransferOptions(filterGrouped(allGrouped, value));
            } else {
                setTransferOptions(allGrouped)
            }
        })}
        value={defaultValue}
        style={{width: "100%"}}
        onBlur={onBlur}
        onSelect={onBlur}
        onKeyUp={(e) => e.code === 'Enter' && onEnter && onEnter()}
        onChange={onChange}
        options={transferOptions.length === 0 ? allGrouped : transferOptions}
        placeholder={'DHL-F...'}/>)
}
