import {endpoint} from "../config";

export default async function ({address, zip_code, country, receiver, receiver_phone}) {
    const res = await fetch(`${endpoint}/excel?address=${address || ""}&zip_code=${zip_code || ""}&country=${country || ""}&receiver=${receiver || ""}&receiver_phone=${receiver_phone || ""}`);
    const blob = await res.blob();

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const date = new Date();
    a.download = `运单预览_${date.getMonth()}${date.getDate()}${date.getHours()}${date.getMinutes()}${date.getSeconds()}.xlsx`
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url); // 清理
}