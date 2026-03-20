import {AutoComplete} from "antd";
import React, {useState} from "react";

const goodList = [{'label': 'CLOTH', 'value': 'CLOTH'}, {
    'label': 'T-SHIRT', 'value': 'T-SHIRT'
}, {'label': 'SWEATSHIRT', 'value': 'SWEATSHIRT'}, {'label': 'VEST', 'value': 'VEST'}, {
    'label': 'DRESS', 'value': 'DRESS'
}, {'label': 'SUIT', 'value': 'SUIT'}, {'label': 'SCARF', 'value': 'SCARF'}, {
    'label': 'SHORTS', 'value': 'SHORTS'
}, {'label': 'SHIRT', 'value': 'SHIRT'}, {'label': 'SWEATER', 'value': 'SWEATER'}, {
    'label': 'BLAZER', 'value': 'BLAZER'
}, {'label': 'BAG', 'value': 'BAG'}, {'label': 'HAND BAG', 'value': 'HAND BAG'}, {
    'label': 'PURSE', 'value': 'PURSE'
}, {'label': 'WALLET', 'value': 'WALLET'}, {'label': 'BRIEFCASE', 'value': 'BRIEFCASE'}, {
    'label': 'SHOULDER BAG', 'value': 'SHOULDER BAG'
}, {'label': 'HOLDALL', 'value': 'HOLDALL'}, {'label': 'BACKPACK', 'value': 'BACKPACK'}, {
    'label': 'BROOCH', 'value': 'BROOCH'
}, {'label': 'CUFFINK', 'value': 'CUFFINK'}, {'label': 'PENDANT', 'value': 'PENDANT'}, {
    'label': 'EARRING', 'value': 'EARRING'
}, {'label': 'BUCKLE', 'value': 'BUCKLE'}, {'label': 'BUCKLE', 'value': 'BUCKLE'},
    {'label': 'LABEL', 'value': 'LABEL'}]

export default function ({onChange, onBlur, onEnter, defaultValue, ref}) {
    const [goodOptions, setGoodOptions] = useState([])

    return (<AutoComplete
        onSearch={(value => {
            if (value !== '') {
                const res = goodList.filter(val => val.label.toLowerCase().includes(value.toLowerCase()));
                setGoodOptions(res)
            } else {
                setGoodOptions(goodList)
            }

        })}
        ref={ref}
        defaultValue={defaultValue}
        onSelect={onBlur}
        style={{width: "100%"}}
        onBlur={onBlur}
        onKeyUp={(e) => e.code === 'Enter' && onEnter()}
        onChange={onChange}
        options={goodOptions.length === 0 ? goodList : goodOptions}/>)
}