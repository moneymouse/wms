import { BrowserMultiFormatReader, NotFoundException } from "@zxing/library";
import React, {useState} from "react";
import {useEffect, useRef} from "react";

//duration of the tone in milliseconds. Default is 500
//frequency of the tone in hertz. default is 440
//volume of the tone. Default is 1, off is 0.
//type of tone. Possible values are sine, square, sawtooth, triangle, and custom. Default is sine.
//callback to use on end of tone
function beep(duration, frequency, volume, type, callback) {
    //if you have another AudioContext class use that one, as some browsers have a limit
    let audioCtx = new (window.AudioContext || window.webkitAudioContext || window.audioContext);

    let oscillator = audioCtx.createOscillator();
    let gainNode = audioCtx.createGain();

    oscillator.connect(gainNode);
    gainNode.connect(audioCtx.destination);

    if (volume){gainNode.gain.value = volume;}
    if (frequency){oscillator.frequency.value = frequency;}
    if (type){oscillator.type = type;}
    if (callback){oscillator.onended = callback;}

    oscillator.start(audioCtx.currentTime);
    oscillator.stop(audioCtx.currentTime + ((duration || 500) / 1000));
};

export default function Scanner(){
    const videoRef = useRef(null);
    const [message, setMessage] = useState("");
    useEffect(() => {
        (async () => {
            const reader = new BrowserMultiFormatReader();
            const devices = await reader.listVideoInputDevices()
            if(!devices.length){
                setMessage("没有支持的设备。");
                return;
            }
            const deviceId = devices[0].deviceId
            await reader.decodeFromVideoDevice(deviceId ,videoRef.current, (res, err)=>{
                if (res) {
                    console.log(res)
                    setMessage(res.text)
                    beep(100, 1440, 0.8, 'sine');
                }
                if (err && !(err instanceof NotFoundException)) {
                    console.error(err)
                }
            });
            console.log(videoRef.current);
        })()
    }, [])
    return (
        <>
            <p>{message}</p>
            <button onClick={() => {beep(100, 1440, 0.8, 'sine')}}>beep</button>
            <video ref={videoRef} />
        </>
    )
}