const ui = Object.fromEntries([
  "signalDot","status","detail","enterVr","sampleCount","rate","uploadState",
  "uploadDetail","headPose","headValid","headCard","leftPose","leftValid",
  "leftCard","rightPose","rightValid","rightCard","sessionLabel"
].map(id => [id, document.getElementById(id)]));

let xrSession = null;
let referenceSpace = null;
let sequence = 0;
let sessionId = null;
let pending = [];
let sending = false;
let rateWindow = [];

const rounded = values => Array.from(values, n => Number(n.toFixed(4)));
const poseData = pose => pose ? {
  position: rounded([pose.transform.position.x, pose.transform.position.y, pose.transform.position.z]),
  orientation: rounded([pose.transform.orientation.x, pose.transform.orientation.y, pose.transform.orientation.z, pose.transform.orientation.w])
} : null;

function showPose(name, data) {
  const pose = ui[`${name}Pose`];
  const valid = ui[`${name}Valid`];
  const card = ui[`${name}Card`];
  if (!data) {
    pose.textContent = "posición  —\nrotación  —";
    valid.textContent = "SIN TRACKING";
    card.classList.remove("valid");
    return;
  }
  pose.textContent = `posición  ${data.position.join("  ")}\nrotación  ${data.orientation.join("  ")}`;
  valid.textContent = "VÁLIDO";
  card.classList.add("valid");
}

function controllerData(input, frame) {
  if (!input) return null;
  const gripPose = input.gripSpace ? frame.getPose(input.gripSpace, referenceSpace) : null;
  const rayPose = frame.getPose(input.targetRaySpace, referenceSpace);
  return {
    handedness: input.handedness,
    profiles: input.profiles,
    grip: poseData(gripPose),
    ray: poseData(rayPose),
    buttons: input.gamepad ? input.gamepad.buttons.map(b => ({pressed:b.pressed, touched:b.touched, value:Number(b.value.toFixed(4))})) : [],
    axes: input.gamepad ? rounded(input.gamepad.axes) : []
  };
}

async function flush() {
  if (sending || pending.length === 0) return;
  sending = true;
  const samples = pending.splice(0, 60);
  try {
    const response = await fetch("/api/samples", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({protocolVersion:1, sessionId, samples})
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    ui.uploadState.textContent = "OK";
    ui.uploadDetail.textContent = `${samples.length} últimas`;
  } catch (error) {
    pending.unshift(...samples);
    pending = pending.slice(-120);
    ui.uploadState.textContent = "ERROR";
    ui.uploadDetail.textContent = error.message;
  } finally { sending = false; }
}

function onXRFrame(time, frame) {
  xrSession.requestAnimationFrame(onXRFrame);
  const viewer = frame.getViewerPose(referenceSpace);
  const head = viewer ? poseData(viewer.views[0]) : null;
  const leftInput = [...xrSession.inputSources].find(x => x.handedness === "left");
  const rightInput = [...xrSession.inputSources].find(x => x.handedness === "right");
  const left = controllerData(leftInput, frame);
  const right = controllerData(rightInput, frame);
  const sample = {sequence:sequence++, clientTime:performance.now(), head, left, right};
  pending.push(sample);
  if (pending.length > 120) pending.shift();

  showPose("head", head);
  showPose("left", left?.grip || left?.ray || null);
  showPose("right", right?.grip || right?.ray || null);
  ui.sampleCount.textContent = sequence.toLocaleString();
  rateWindow.push(time);
  while (rateWindow.length && rateWindow[0] < time - 1000) rateWindow.shift();
  ui.rate.textContent = rateWindow.length;
}

async function enterVR() {
  try {
    sessionId = `${Date.now().toString(36)}-${crypto.randomUUID().slice(0,8)}`;
    sequence = 0; pending = [];
    xrSession = await navigator.xr.requestSession("immersive-vr", {requiredFeatures:["local-floor"]});
    const canvas = document.getElementById("xrCanvas");
    const gl = canvas.getContext("webgl", {xrCompatible:true});
    await gl.makeXRCompatible();
    xrSession.updateRenderState({baseLayer:new XRWebGLLayer(xrSession, gl)});
    referenceSpace = await xrSession.requestReferenceSpace("local-floor");
    xrSession.addEventListener("end", endSession);
    ui.status.textContent = "Capturando tracking";
    ui.detail.textContent = "Poses enviadas al Mac · ningún comando de robot";
    ui.signalDot.style.background = "var(--green)";
    ui.sessionLabel.textContent = `Sesión ${sessionId}`;
    ui.enterVr.textContent = "Salir de VR";
    ui.enterVr.onclick = () => xrSession.end();
    xrSession.requestAnimationFrame(onXRFrame);
  } catch (error) {
    ui.status.textContent = "No se pudo iniciar VR";
    ui.detail.textContent = error.message;
  }
}

function endSession() {
  xrSession = null; referenceSpace = null;
  flush();
  ui.status.textContent = "Quest listo";
  ui.detail.textContent = "La sesión terminó de forma segura";
  ui.enterVr.textContent = "Entrar en VR";
  ui.enterVr.onclick = enterVR;
}

async function boot() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("Servidor no disponible");
    if (!navigator.xr) throw new Error("Este navegador no expone WebXR");
    const supported = await navigator.xr.isSessionSupported("immersive-vr");
    if (!supported) throw new Error("Modo immersive-vr no disponible");
    ui.status.textContent = "Quest listo";
    ui.detail.textContent = "Servidor local conectado · WebXR disponible";
    ui.enterVr.disabled = false;
    ui.enterVr.onclick = enterVR;
    ui.signalDot.style.background = "var(--green)";
  } catch (error) {
    ui.status.textContent = "Abrí esta URL en el Quest";
    ui.detail.textContent = error.message;
  }
}

setInterval(flush, 100);
boot();
