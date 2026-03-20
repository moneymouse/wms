import {AutoComplete} from "antd";
import React, {useState} from "react";
import transportation from "../common/transportation";

export default function ({onChange, onBlur, onEnter, defaultValue}) {
    const [transferOptions, setTransferOptions] = useState([])

    return (<AutoComplete
        onSearch={(value => {
            if (value !== '') {
                const res = transportation.filter(val => val.label.toLowerCase().includes(value.toLowerCase()));
                setTransferOptions(res)
            } else {
                setTransferOptions(transportation)
            }

        })}
        value={defaultValue}
        style={{width: "100%"}}
        onBlur={onBlur}
        onSelect={onBlur}
        onKeyUp={(e) => e.code === 'Enter' && onEnter()}
        onChange={onChange}
        options={transferOptions.length === 0 ? transportation : transferOptions}
        placeholder={'DHL-F...'}/>)
}