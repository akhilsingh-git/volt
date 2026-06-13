/* Volt WebRTC — WHIP publish (browser go-live, no OBS) + WHEP playback (sub-second).
   Talks directly to mediamtx on :8889 (CORS-enabled). Shares page globals
   (channel, me, $, play, hls, setLive) via the global lexical scope. */

const WEBRTC_BASE = `${location.protocol}//${location.hostname}:8889`;

let playMode = 'hls';      // 'hls' (LL-HLS) | 'webrtc' (WHEP)
let rtPc = null;           // current WHEP playback peer connection
let pubPc = null;          // current WHIP publish peer connection
let pubStream = null;      // local capture stream while broadcasting

// Wait for ICE gathering (non-trickle WHIP/WHEP: send the complete offer).
function waitIce(pc){
  return new Promise(res=>{
    if (pc.iceGatheringState === 'complete') return res();
    const to = setTimeout(res, 1500);
    pc.addEventListener('icegatheringstatechange', ()=>{
      if (pc.iceGatheringState === 'complete'){ clearTimeout(to); res(); }
    });
  });
}

async function sdpExchange(url, sdp, headers){
  const res = await fetch(url, {
    method:'POST',
    headers: Object.assign({ 'Content-Type':'application/sdp' }, headers||{}),
    body: sdp
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.text();
}

// ── WHEP: low-latency playback ────────────────────────────────────────
async function whepStart(name){
  whepStop();
  const pc = new RTCPeerConnection({ iceServers: [] });
  rtPc = pc;
  pc.addTransceiver('video', { direction:'recvonly' });
  pc.addTransceiver('audio', { direction:'recvonly' });
  const ms = new MediaStream();
  pc.ontrack = e => { ms.addTrack(e.track); video.srcObject = ms; video.play().catch(()=>{}); };
  pc.addEventListener('connectionstatechange', ()=>{
    if (['failed','disconnected','closed'].includes(pc.connectionState)) setLive(false);
    if (pc.connectionState === 'connected') setLive(true);
  });
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitIce(pc);
  try{
    const answer = await sdpExchange(`${WEBRTC_BASE}/${name}/whep`, pc.localDescription.sdp);
    await pc.setRemoteDescription({ type:'answer', sdp:answer });
  }catch(e){ console.warn('WHEP failed', e); setLive(false); }
}
function whepStop(){
  if (rtPc){ try{ rtPc.close(); }catch{} rtPc = null; }
  if (video.srcObject){ video.srcObject = null; }
}

// ── playback mode switch (used by switchChannel + the toggle button) ──
function startPlayback(name){
  if (playMode === 'webrtc') whepStart(name);
  else play(name);                          // play() = LL-HLS (in index.html)
}
function toggleRealtime(){
  playMode = (playMode === 'webrtc') ? 'hls' : 'webrtc';
  const btn = $('#rtBtn');
  btn.classList.toggle('on', playMode === 'webrtc');
  btn.textContent = playMode === 'webrtc' ? '⚡ Real-time ON' : '⚡ Real-time';
  $('#quality').style.display = playMode === 'webrtc' ? 'none' : '';
  // tear down the other engine, then (re)start current channel
  if (hls){ try{ hls.destroy(); }catch{} hls = null; }
  whepStop();
  if (channel) startPlayback(channel);
}

// ── WHIP: browser "go live" (no OBS) ──────────────────────────────────
async function goLive(kind){
  if (!me) return openAuth('login');
  const statusEl = $('#goliveStatus');
  try{
    statusEl.textContent = 'requesting ' + kind + '…';
    pubStream = kind === 'screen'
      ? await navigator.mediaDevices.getDisplayMedia({ video:{ frameRate:30 }, audio:true })
      : await navigator.mediaDevices.getUserMedia({ video:{ width:{ideal:1920}, height:{ideal:1080}, frameRate:30 }, audio:true });
    $('#selfPreview').srcObject = pubStream;
    $('#selfPreview').style.display = '';

    const pc = new RTCPeerConnection({ iceServers: [] });
    pubPc = pc;
    pubStream.getTracks().forEach(t => pc.addTrack(t, pubStream));
    // Prefer H264 so the same stream is also playable via LL-HLS (which can't
    // carry VP8/VP9/AV1). Audio stays Opus (WebRTC-native).
    try{
      const vt = pc.getTransceivers().find(t => t.sender.track && t.sender.track.kind === 'video');
      if (vt && vt.setCodecPreferences){
        const caps = RTCRtpSender.getCapabilities('video').codecs;
        const h264 = caps.filter(c => /H264/i.test(c.mimeType));
        const rest = caps.filter(c => !/H264/i.test(c.mimeType));
        if (h264.length) vt.setCodecPreferences([...h264, ...rest]);
      }
    }catch(e){ /* setCodecPreferences unsupported — let mediamtx negotiate */ }
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitIce(pc);
    statusEl.textContent = 'connecting…';
    const auth = 'Basic ' + btoa(`${me.username}:${me.stream_key}`);
    const answer = await sdpExchange(`${WEBRTC_BASE}/${me.username}/whip`,
                                     pc.localDescription.sdp, { 'Authorization': auth });
    await pc.setRemoteDescription({ type:'answer', sdp:answer });

    // If the local capture ends (e.g. user stops screen share), tear down.
    pubStream.getVideoTracks()[0].addEventListener('ended', stopGoLive);
    pc.addEventListener('connectionstatechange', ()=>{
      statusEl.textContent = 'status: ' + pc.connectionState;
      if (pc.connectionState === 'connected'){
        statusEl.innerHTML = '🔴 <b>LIVE</b> as @' + me.username + ' — viewers can watch now.';
      }
    });
    $('#goliveStart').style.display = 'none';
    $('#goliveStop').style.display = '';
  }catch(e){
    statusEl.textContent = 'go-live failed: ' + e.message;
    stopGoLive();
  }
}
function stopGoLive(){
  if (pubPc){ try{ pubPc.close(); }catch{} pubPc = null; }
  if (pubStream){ pubStream.getTracks().forEach(t=>t.stop()); pubStream = null; }
  const p = $('#selfPreview'); if (p){ p.srcObject = null; p.style.display = 'none'; }
  const s = $('#goliveStart'), e = $('#goliveStop'); if (s) s.style.display = ''; if (e) e.style.display = 'none';
  const st = $('#goliveStatus'); if (st) st.textContent = 'not broadcasting';
}
