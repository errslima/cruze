const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['local','remote','placeholder','status','detail','connection','dot','start','next','stop','mic','camera','consent','play'].map(id => [id, $(id)]));
// Deliberately STUN-only. Never add TURN URLs to this configuration.
const rtcConfig = {iceServers: [{urls: 'stun:stun.l.google.com:19302'}]};
let stream, socket, peer, matchId, timer, generation = 0, active = false;
let pendingCandidates = [];
function status(title, detail, label = 'OFFLINE') {
  ui.status.textContent = title; ui.detail.textContent = detail;
  ui.connection.textContent = label;
  ui.dot.classList.toggle('live', label === 'CONNECTED');
  ui.placeholder.hidden = label === 'CONNECTED';
}
function send(data) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data)); }
function closePeer() {
  clearTimeout(timer); peer?.close(); peer = null; matchId = null;
  pendingCandidates = []; ui.remote.srcObject = null; ui.play.hidden = true;
}
function controls() {
  ui.start.hidden = active; ui.next.disabled = !active || socket?.readyState !== WebSocket.OPEN;
  ui.stop.disabled = !active; ui.mic.disabled = ui.camera.disabled = !stream;
  ui.consent.disabled = active;
}
function stop() {
  generation++; active = false; send({type:'stop'}); closePeer();
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  stream?.getTracks().forEach(track => track.stop()); stream = null; ui.local.srcObject = null;
  ui.mic.textContent = 'Mute mic'; ui.camera.textContent = 'Camera off';
  ui.mic.setAttribute('aria-pressed', 'false'); ui.camera.setAttribute('aria-pressed', 'false');
  controls();
}
function fail(message) {
  send({type:'stop'}); closePeer();
  status('This connection couldn’t get through.', message, 'CONNECTION FAILED');
  controls();
}
async function matched(message) {
  closePeer(); matchId = message.matchId;
  const id = matchId, pc = new RTCPeerConnection(rtcConfig); peer = pc;
  status('Making a connection…', 'Trying a direct route between your browsers.', 'CONNECTING');
  stream.getTracks().forEach(track => pc.addTrack(track, stream));
  const signal = data => { if (peer === pc) send({type:'signal', matchId:id, signal:data}); };
  pc.onicecandidate = event => { if (event.candidate) signal({type:'candidate', candidate:event.candidate.toJSON()}); };
  pc.ontrack = event => {
    if (peer !== pc) return;
    ui.remote.srcObject = event.streams[0];
    ui.remote.play().catch(() => { if (peer === pc) ui.play.hidden = false; });
  };
  pc.onconnectionstatechange = () => {
    if (peer !== pc) return;
    if (pc.connectionState === 'connected') {
      clearTimeout(timer); status('Connected', '', 'CONNECTED');
    } else if (pc.connectionState === 'failed') {
      fail('Your networks could not establish a direct connection. Try Next.');
    } else if (pc.connectionState === 'disconnected') {
      status('Connection interrupted…', 'Trying to reconnect.', 'CONNECTING');
      clearTimeout(timer); timer = setTimeout(() => { if (peer === pc) fail('Connection lost. Try Next.'); }, 10000);
    }
  };
  timer = setTimeout(() => { if (peer === pc) fail('No direct route was found within 15 seconds. Try Next.'); }, 15000);
  if (message.initiator) {
    await pc.setLocalDescription(await pc.createOffer());
    signal({type:pc.localDescription.type, sdp:pc.localDescription.sdp});
  }
}
async function receive(message) {
  if (!active) return;
  if (message.type === 'waiting') {
    closePeer(); status('Looking for someone new…', 'Keep this tab open. You’ll connect when someone is available.', 'WAITING');
  } else if (message.type === 'matched') {
    await matched(message);
  } else if (message.type === 'peer-left' && message.matchId === matchId) {
    closePeer(); status('They’ve moved on.', 'Finding your next conversation.', 'WAITING');
  } else if (message.type === 'signal' && message.matchId === matchId && peer) {
    const pc = peer, id = matchId, signal = message.signal;
    if (signal.type === 'candidate') {
      if (pc.remoteDescription) await pc.addIceCandidate(signal.candidate);
      else pendingCandidates.push(signal.candidate);
    } else {
      await pc.setRemoteDescription(signal);
      if (peer !== pc) return;
      for (const candidate of pendingCandidates) await pc.addIceCandidate(candidate);
      pendingCandidates = [];
      if (signal.type === 'offer') {
        await pc.setLocalDescription(await pc.createAnswer());
        if (peer === pc) send({type:'signal', matchId:id, signal:{type:pc.localDescription.type, sdp:pc.localDescription.sdp}});
      }
    }
  }
}
ui.start.onclick = async () => {
  if (!ui.consent.checked) { status('Confirm you’re 18 or older.', 'Check the box below to join this private test.'); return; }
  if (!navigator.mediaDevices?.getUserMedia) { status('Camera access needs a secure connection.', 'Open this site over HTTPS or localhost.'); return; }
  const run = ++generation; active = true; controls();
  status('Let’s get your camera ready.', 'Allow camera and microphone access in your browser.', 'STARTING');
  try {
    const media = await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:true});
    if (run !== generation) { media.getTracks().forEach(track => track.stop()); return; }
    stream = media; ui.local.srcObject = media; controls();
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`); socket = ws;
    const timeout = setTimeout(() => { if (socket === ws && ws.readyState !== WebSocket.OPEN) { stop(); status('Server unavailable.', 'Try starting again.'); } }, 10000);
    ws.onopen = () => { clearTimeout(timeout); if (run !== generation) return; send({type:'join'}); controls(); };
    let chain = Promise.resolve();
    ws.onmessage = event => {
      chain = chain.then(() => { if (run === generation) return receive(JSON.parse(event.data)); }).catch(() => {
        if (run === generation && peer) fail('Connection setup failed. Try Next.');
      });
    };
    ws.onclose = () => { clearTimeout(timeout); if (run !== generation) return; stop(); status('Disconnected from the server.', 'Start again to reconnect.'); };
  } catch (error) {
    if (run !== generation) return;
    stop(); status('Couldn’t open your camera.', error.name === 'NotAllowedError' ? 'Allow camera and microphone permissions, then try again.' : 'Check that your camera and microphone are available.');
  }
};
ui.next.onclick = () => { send({type:'next', matchId}); closePeer(); status('Looking for someone new…', 'Waiting for another available person.', 'WAITING'); };
ui.stop.onclick = () => { stop(); status('You’re off camera.', 'Start again whenever you feel like it.'); };
for (const [id, kind, off, on] of [['mic','audio','Mute mic','Unmute mic'],['camera','video','Camera off','Camera on']]) {
  ui[id].onclick = () => { const tracks = kind === 'audio' ? stream?.getAudioTracks() : stream?.getVideoTracks(); if (!tracks?.length) return; const enabled = !tracks[0].enabled; tracks.forEach(t => t.enabled = enabled); ui[id].textContent = enabled ? off : on; ui[id].setAttribute('aria-pressed', String(!enabled)); };
}
ui.play.onclick = () => ui.remote.play().then(() => { ui.play.hidden = true; }).catch(() => {});
window.addEventListener('pagehide', stop);
