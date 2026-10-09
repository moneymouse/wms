export default function () {
    const ip = localStorage.getItem("ip");
    return (ip || "32").toString() + (new Date()).getTime().toString();
}