const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['local','remote','placeholder','status','detail','connection','start','next','block','stop','mic','camera','play'].map(id => [id, $(id)]));
// Deliberately STUN-only. Never add TURN URLs to this configuration.
const rtcConfig = {iceServers: [{urls: 'stun:stun.l.google.com:19302'}]};
let stream, socket, peer, matchId, timer, generation = 0, active = false;
let pendingCandidates = [];
const cameraSelect = $('camera-select');
let preferredCamera = '';
try { preferredCamera = localStorage.getItem('cruze_camera') || ''; } catch {}
let switchingCamera = false;
let peerIp = null, blockTarget = null;
const blockDialog = $("block-dialog");
function status(title, detail, label = 'OFFLINE') {
  ui.status.textContent = title; ui.detail.textContent = detail;
  ui.connection.textContent = label;
  ui.placeholder.dataset.state = label;
  ui.placeholder.title = `${title} ${detail}`;
  ui.placeholder.hidden = label === 'CONNECTED';
}
function send(data) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data)); }
function closePeer() {
  clearTimeout(timer); peer?.close(); peer = null; matchId = null; peerIp = null; ui.block.disabled = true;
  pendingCandidates = []; ui.remote.srcObject = null; ui.play.hidden = true;
}
function controls() {
  ui.start.hidden = active; ui.next.hidden = !active; ui.next.disabled = !active || socket?.readyState !== WebSocket.OPEN;
  ui.block.disabled = !active || !peerIp;
  ui.stop.disabled = !active; ui.mic.disabled = ui.camera.disabled = !stream;
  ui.start.disabled = !ageConfirmed;
  cameraSelect.disabled = switchingCamera || (active && !stream);
}
function stop(reason = "stop") {
  $('camera-error').hidden = true;
  blockDialog.close(); blockTarget = null;
  generation++; active = false; send({type:'stop', reason}); closePeer();
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  stream?.getTracks().forEach(track => track.stop()); stream = null; ui.local.srcObject = null;
  ui.mic.setAttribute('aria-label', 'Mute microphone'); ui.mic.title = 'Mute microphone';
  ui.camera.setAttribute('aria-label', 'Turn camera off'); ui.camera.title = 'Turn camera off';
  ui.mic.setAttribute('aria-pressed', 'false'); ui.camera.setAttribute('aria-pressed', 'false');
  controls();
}
function fail(message) {
  send({type:'stop', reason:'connection_failed'}); closePeer();
  status('This connection couldn’t get through.', message, 'CONNECTION FAILED');
  controls();
}
async function matched(message) {
  closePeer(); matchId = message.matchId; peerIp = message.peerIp;
  controls();
  const id = matchId, pc = new RTCPeerConnection(rtcConfig); peer = pc;
  status('Making a connection…', 'Trying a direct route between your browsers.', 'CONNECTING');
  stream.getTracks().forEach(track => pc.addTrack(track, stream));
  const signal = data => { if (peer === pc) send({type:'signal', matchId:id, signal:data}); };
  pc.onicecandidate = event => { if (event.candidate) signal({type:'candidate', candidate:event.candidate.toJSON()}); };
  pc.ontrack = event => {
    if (peer !== pc) return;
    const incoming = event.streams[0];
    // Audio and video can announce the same stream separately. Reassigning
    // srcObject interrupts pending playback, especially in Safari.
    if (!incoming || ui.remote.srcObject === incoming) return;
    ui.remote.srcObject = incoming;
    playRemote();
  };
  pc.onconnectionstatechange = () => {
    if (peer !== pc) return;
    if (['connected', 'disconnected', 'failed'].includes(pc.connectionState)) send({type:'connection', matchId:id, state:pc.connectionState});
    if (pc.connectionState === 'connected') {
      clearTimeout(timer); status('Connected', '', 'CONNECTED');
    } else if (pc.connectionState === 'failed') {
      fail('Your networks could not establish a direct connection. Try Skip.');
    } else if (pc.connectionState === 'disconnected') {
      status('Connection interrupted…', 'Trying to reconnect.', 'CONNECTING');
      clearTimeout(timer); timer = setTimeout(() => { if (peer === pc) fail('Connection lost. Try Skip.'); }, 10000);
    }
  };
  timer = setTimeout(() => { if (peer === pc) fail('No direct route was found within 15 seconds. Try Skip.'); }, 15000);
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
  if (!ageConfirmed) { ageGate.showModal(); return; }
  if (!navigator.mediaDevices?.getUserMedia) { status('Camera access needs a secure connection.', 'Open this site over HTTPS or localhost.', 'ERROR'); return; }
  const run = ++generation; active = true; controls();
  status('Let’s get your camera ready.', 'Allow camera and microphone access in your browser.', 'STARTING');
  try {
    const media = await openCamera(preferredCamera, true);
    if (run !== generation) { media.getTracks().forEach(track => track.stop()); return; }
    stream = media; ui.local.srcObject = media; controls();
    refreshCameras();
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws?visit=${encodeURIComponent(document.querySelector('meta[name=cruze-visit]')?.content || '')}`); socket = ws;
    const timeout = setTimeout(() => { if (socket === ws && ws.readyState !== WebSocket.OPEN) { stop(); status('Server unavailable.', 'Try starting again.', 'ERROR'); } }, 10000);
    ws.onopen = () => { clearTimeout(timeout); if (run !== generation) return; send({type:'join'}); controls(); };
    let chain = Promise.resolve();
    ws.onmessage = event => {
      chain = chain.then(() => { if (run === generation) return receive(JSON.parse(event.data)); }).catch(() => {
        if (run === generation && peer) fail('Connection setup failed. Try Skip.');
      });
    };
    ws.onclose = () => { clearTimeout(timeout); if (run !== generation) return; stop(); status('Disconnected from the server.', 'Start again to reconnect.', 'ERROR'); };
  } catch (error) {
    if (run !== generation) return;
    stop(); status('Couldn’t open your camera.', error.name === 'NotAllowedError' ? 'Allow camera and microphone permissions, then try again.' : 'Check that your camera and microphone are available.', 'ERROR');
  }
};
ui.next.onclick = () => { send({type:'next', matchId}); closePeer(); status('Looking for someone new…', 'Waiting for another available person.', 'WAITING'); };
ui.stop.onclick = () => { stop(); status('You’re off camera.', 'Start again whenever you feel like it.'); };
for (const [id, kind, off, on] of [['mic','audio','Mute microphone','Unmute microphone'],['camera','video','Turn camera off','Turn camera on']]) {
  ui[id].onclick = () => { const tracks = kind === 'audio' ? stream?.getAudioTracks() : stream?.getVideoTracks(); if (!tracks?.length) return; const enabled = !tracks[0].enabled; tracks.forEach(t => t.enabled = enabled); ui[id].setAttribute('aria-label', enabled ? off : on); ui[id].title = enabled ? off : on; ui[id].setAttribute('aria-pressed', String(!enabled)); };
}
async function playRemote() {
  const currentPeer = peer, source = ui.remote.srcObject;
  if (!currentPeer || !source) return;
  try {
    await ui.remote.play();
    if (peer === currentPeer && ui.remote.srcObject === source) ui.play.hidden = true;
  } catch (error) {
    if (peer !== currentPeer || ui.remote.srcObject !== source) return;
    // An interrupted play() is not an autoplay-permission failure. Also
    // ignore late failures after another attempt has already started video.
    ui.play.hidden = error.name !== 'NotAllowedError' || !ui.remote.paused;
  }
}
ui.remote.addEventListener('playing', () => {
  if (!ui.remote.paused) ui.play.hidden = true;
});
ui.play.onclick = playRemote;
window.addEventListener('pagehide', () => stop('page_closed'));

// Remember only the age declaration; never start media automatically.
const ageGate = $('age-gate');
let ageConfirmed = document.cookie.split(';').some(cookie => cookie.trim() === 'cruze_adult=1');
ageGate.addEventListener('cancel', event => event.preventDefault());
$('confirm-age').onclick = () => {
  const secure = location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `cruze_adult=1; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;
  ageConfirmed = true;
  ageGate.close();
  controls();
  ui.start.focus();
};
$('leave').onclick = () => { stop(); location.replace('about:blank'); };
controls();
if (!ageConfirmed) ageGate.showModal();

function savedBlocks() {
  try {
    const value = document.cookie.split(';').map(part => part.trim()).find(part => part.startsWith('cruze_blocks='));
    const entries = JSON.parse(decodeURIComponent(value?.slice('cruze_blocks='.length) || '{}'));
    if (!entries || typeof entries !== 'object' || Array.isArray(entries)) return {};
    return Object.fromEntries(Object.entries(entries).filter(([, expiry]) => Number.isFinite(expiry) && expiry > Date.now()));
  } catch { return {}; }
}
ui.block.onclick = () => {
  if (!peerIp) return;
  blockTarget = {ip: peerIp, matchId};
  $('block-error').hidden = true;
  blockDialog.showModal();
};
$('cancel-block').onclick = () => { blockDialog.close(); blockTarget = null; };
blockDialog.addEventListener('cancel', () => { blockTarget = null; });
$('confirm-block').onclick = () => {
  if (!blockTarget) return;
  const entries = savedBlocks();
  entries[blockTarget.ip] = Date.now() + 31536000000;
  const value = encodeURIComponent(JSON.stringify(entries));
  const error = $('block-error');
  if (value.length > 3500) {
    error.textContent = 'Your saved block list is full. This block could not be saved.';
    error.hidden = false; return;
  }
  document.cookie = `cruze_blocks=${value}; Max-Age=31536000; Path=/; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
  if (savedBlocks()[blockTarget.ip] !== entries[blockTarget.ip]) {
    error.textContent = 'Enable cookies to save this block.';
    error.hidden = false; return;
  }
  send({type: 'block', ...blockTarget});
  // Keep the captured target if the partner skipped while the popup was open.
  if (peerIp === blockTarget.ip) {
    closePeer(); status('User blocked.', 'Looking for someone else.', 'WAITING');
  }
  blockTarget = null; blockDialog.close();
};

function cameraConstraints(deviceId) {
  return {width: {ideal: 1280}, height: {ideal: 720}, ...(deviceId ? {deviceId: {exact: deviceId}} : {})};
}
async function openCamera(deviceId, audio) {
  try {
    return await navigator.mediaDevices.getUserMedia({video: cameraConstraints(deviceId), audio});
  } catch (error) {
    // A remembered unplugged camera should not prevent starting a new call.
    if (!audio || !deviceId || !['NotFoundError', 'OverconstrainedError'].includes(error.name)) throw error;
    return navigator.mediaDevices.getUserMedia({video: cameraConstraints(''), audio});
  }
}
async function refreshCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput' && device.deviceId);
    const selected = stream?.getVideoTracks()[0]?.getSettings().deviceId || preferredCamera;
    cameraSelect.replaceChildren(new Option('Default camera', ''));
    devices.forEach((device, index) => cameraSelect.add(new Option(device.label || `Camera ${index + 1}`, device.deviceId)));
    cameraSelect.value = devices.some(device => device.deviceId === selected) ? selected : '';
    controls();
  } catch { /* Permissions or device lists may be unavailable until Start. */ }
}
function rememberCamera(deviceId) {
  preferredCamera = deviceId;
  try { localStorage.setItem('cruze_camera', deviceId); } catch {}
}
async function switchCamera(deviceId) {
  if (switchingCamera) return;
  if (!stream) { rememberCamera(deviceId); return; }
  const run = generation, localStream = stream, oldTrack = stream.getVideoTracks()[0];
  switchingCamera = true; controls(); $('camera-error').hidden = true;
  let media, adopted = false;
  try {
    media = await openCamera(deviceId, false);
    const track = media.getVideoTracks()[0];
    if (!track) throw new Error('No video track');
    if (run !== generation || stream !== localStream) return;
    track.enabled = oldTrack?.enabled ?? true;
    // If Skip changes the peer while replaceTrack is pending, update the new
    // sender too before retiring the old track. The microphone stays intact.
    while (peer) {
      const currentPeer = peer;
      const sender = currentPeer.getSenders().find(sender => sender.track?.kind === 'video');
      if (sender) {
        try { await sender.replaceTrack(track); }
        catch (error) { if (peer === currentPeer) throw error; }
      }
      if (run !== generation || stream !== localStream) return;
      if (peer === currentPeer) break;
    }
    // Respect toggles made while the camera was opening.
    track.enabled = oldTrack?.enabled ?? true;
    if (oldTrack) localStream.removeTrack(oldTrack);
    localStream.addTrack(track);
    ui.local.srcObject = localStream;
    adopted = true;
    oldTrack?.stop();
    rememberCamera(deviceId);
  } catch {
    if (run === generation && stream === localStream) {
      $('camera-error').textContent = 'Couldn’t switch cameras. Your previous camera is still selected.';
      $('camera-error').hidden = false;
    }
  } finally {
    if (!adopted) media?.getTracks().forEach(track => track.stop());
    switchingCamera = false;
    controls(); refreshCameras();
  }
}
cameraSelect.onchange = () => switchCamera(cameraSelect.value);
navigator.mediaDevices?.addEventListener('devicechange', refreshCameras);
refreshCameras();
