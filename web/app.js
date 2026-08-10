const ui = Object.fromEntries([
  "signalDot","status","detail","enterVr","sampleCount","rate","uploadState",
  "uploadDetail","headPose","headValid","headCard","leftPose","leftValid",
  "leftCard","rightPose","rightValid","rightCard","sessionLabel"
].map(id => [id, document.getElementById(id)]));

let xrSession = null;
let referenceSpace = null;
let renderer = null;
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

// Minimal WebGL renderer kept dependency-free so the Quest only needs the Mac LAN.
class XRScene {
  constructor(gl) {
    this.gl = gl;
    this.colorProgram = this.program(
      "attribute vec3 p;uniform mat4 projection,view,model;void main(){gl_Position=projection*view*model*vec4(p,1.);}",
      "precision mediump float;uniform vec4 color;void main(){gl_FragColor=color;}"
    );
    this.textureProgram = this.program(
      "attribute vec3 p;attribute vec2 uv;uniform mat4 projection,view,model;varying vec2 vuv;void main(){vuv=uv;gl_Position=projection*view*model*vec4(p,1.);}",
      "precision mediump float;uniform sampler2D image;varying vec2 vuv;void main(){gl_FragColor=texture2D(image,vuv);}"
    );
    this.skyProgram = this.program(
      "attribute vec2 p;varying vec2 screen;void main(){screen=p*.5+.5;gl_Position=vec4(p,1.,1.);}",
      "precision mediump float;varying vec2 screen;void main(){vec3 low=vec3(.055,.20,.23);vec3 high=vec3(.16,.34,.42);float glow=smoothstep(.0,1.,screen.y);vec3 c=mix(low,high,glow)+.035*(1.-distance(screen,vec2(.72,.78)));gl_FragColor=vec4(c,1.);}"
    );
    this.cube = this.buffer([
      -1,-1, 1, 1,-1, 1, 1, 1, 1, -1,-1, 1, 1, 1, 1,-1, 1, 1,
       1,-1,-1,-1,-1,-1,-1, 1,-1, 1,-1,-1,-1, 1,-1, 1, 1,-1,
      -1,-1,-1,-1,-1, 1,-1, 1, 1,-1,-1,-1,-1, 1, 1,-1, 1,-1,
       1,-1, 1, 1,-1,-1, 1, 1,-1, 1,-1, 1, 1, 1,-1, 1, 1, 1,
      -1, 1, 1, 1, 1, 1, 1, 1,-1,-1, 1, 1, 1, 1,-1,-1, 1,-1,
      -1,-1,-1, 1,-1,-1, 1,-1, 1,-1,-1,-1, 1,-1, 1,-1,-1, 1
    ]);
    this.quad = this.buffer([-1,-1,0, 1,-1,0, 1,1,0, -1,-1,0, 1,1,0, -1,1,0]);
    this.uv = this.buffer([0,1, 1,1, 1,0, 0,1, 1,0, 0,0]);
    this.sky = this.buffer([-1,-1, 3,-1, -1,3]);
    this.menuCanvas = document.createElement("canvas");
    this.menuCanvas.width = 1024;
    this.menuCanvas.height = 620;
    this.menuTexture = gl.createTexture();
    this.updateMenu(true);
  }

  shader(type, source) {
    const shader = this.gl.createShader(type);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) throw new Error(this.gl.getShaderInfoLog(shader));
    return shader;
  }

  program(vertex, fragment) {
    const program = this.gl.createProgram();
    this.gl.attachShader(program, this.shader(this.gl.VERTEX_SHADER, vertex));
    this.gl.attachShader(program, this.shader(this.gl.FRAGMENT_SHADER, fragment));
    this.gl.linkProgram(program);
    if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) throw new Error(this.gl.getProgramInfoLog(program));
    return program;
  }

  buffer(values) {
    const buffer = this.gl.createBuffer();
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, buffer);
    this.gl.bufferData(this.gl.ARRAY_BUFFER, new Float32Array(values), this.gl.STATIC_DRAW);
    return buffer;
  }

  multiply(a, b) {
    const out = new Float32Array(16);
    for (let c=0;c<4;c++) for (let r=0;r<4;r++)
      out[c*4+r] = a[r]*b[c*4] + a[4+r]*b[c*4+1] + a[8+r]*b[c*4+2] + a[12+r]*b[c*4+3];
    return out;
  }

  transform(x,y,z,sx=1,sy=1,sz=1) {
    return new Float32Array([sx,0,0,0, 0,sy,0,0, 0,0,sz,0, x,y,z,1]);
  }

  updateMenu(force=false) {
    const now = performance.now();
    if (!force && this.menuUpdated && now-this.menuUpdated < 400) return;
    this.menuUpdated = now;
    const c = this.menuCanvas, ctx = c.getContext("2d");
    const bg = ctx.createLinearGradient(0,0,c.width,c.height);
    bg.addColorStop(0,"#102c2d"); bg.addColorStop(1,"#0a1a20");
    ctx.fillStyle=bg; ctx.fillRect(0,0,c.width,c.height);
    ctx.strokeStyle="#4e8f87"; ctx.lineWidth=4; ctx.strokeRect(2,2,c.width-4,c.height-4);
    ctx.fillStyle="#78f0bd"; ctx.font="700 26px system-ui"; ctx.fillText("UNITREE G1  ·  QUEST LINK",56,66);
    ctx.fillStyle="#f1faf7"; ctx.font="700 64px system-ui"; ctx.fillText("Menú principal",56,145);
    ctx.fillStyle="#92aaa6"; ctx.font="30px system-ui"; ctx.fillText("Transporte WebXR local · modo seguro",56,195);
    const cards = [
      [56,"TRACKING","ACTIVO","#78f0bd"],
      [354,"CALIBRAR","PRÓXIMAMENTE","#88a5ab"],
      [652,"CONECTAR G1","BLOQUEADO","#e8bd6b"]
    ];
    for (const [x,title,state,color] of cards) {
      ctx.fillStyle="#163238"; ctx.fillRect(x,245,270,180);
      ctx.fillStyle=color; ctx.font="700 20px system-ui"; ctx.fillText(state,x+24,285);
      ctx.fillStyle="#f1faf7"; ctx.font="700 29px system-ui"; ctx.fillText(title,x+24,340);
      ctx.fillStyle="#89a09d"; ctx.font="22px system-ui";
      ctx.fillText(title==="TRACKING" ? `${rateWindow.length} Hz · ${sequence} muestras` : title==="CALIBRAR" ? "Alinear torso y manos" : "Sin comandos DDS",x+24,386);
    }
    ctx.fillStyle="#6f8985"; ctx.font="22px system-ui";
    ctx.fillText("Los controles se visualizan en tiempo real",56,496);
    ctx.fillStyle="#78f0bd"; ctx.fillRect(56,540,10,10);
    ctx.fillStyle="#9bb1ad"; ctx.fillText("READ ONLY",80,555);
    const gl=this.gl;
    gl.bindTexture(gl.TEXTURE_2D,this.menuTexture);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,c);
  }

  bindAttribute(program, name, buffer, size) {
    const location=this.gl.getAttribLocation(program,name);
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER,buffer);
    this.gl.enableVertexAttribArray(location);
    this.gl.vertexAttribPointer(location,size,this.gl.FLOAT,false,0,0);
  }

  drawSky() {
    const gl=this.gl;
    gl.disable(gl.DEPTH_TEST); gl.useProgram(this.skyProgram);
    this.bindAttribute(this.skyProgram,"p",this.sky,2);
    gl.drawArrays(gl.TRIANGLES,0,3);
  }

  drawCube(projection,view,model,color) {
    const gl=this.gl,p=this.colorProgram;
    gl.useProgram(p); this.bindAttribute(p,"p",this.cube,3);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"projection"),false,projection);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"view"),false,view);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"model"),false,model);
    gl.uniform4fv(gl.getUniformLocation(p,"color"),color);
    gl.drawArrays(gl.TRIANGLES,0,36);
  }

  drawMenu(projection,view) {
    const gl=this.gl,p=this.textureProgram;
    gl.useProgram(p); this.bindAttribute(p,"p",this.quad,3); this.bindAttribute(p,"uv",this.uv,2);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"projection"),false,projection);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"view"),false,view);
    gl.uniformMatrix4fv(gl.getUniformLocation(p,"model"),false,this.transform(0,1.38,-1.7,.78,.47,1));
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D,this.menuTexture);
    gl.uniform1i(gl.getUniformLocation(p,"image"),0);
    gl.drawArrays(gl.TRIANGLES,0,6);
  }

  drawController(projection,view,pose,handedness,gamepad) {
    if (!pose) return;
    const base=pose.transform.matrix;
    const accent=handedness==="left" ? [.28,.92,.72,1] : [.35,.76,1,1];
    this.drawCube(projection,view,this.multiply(base,this.transform(0,-.035,.018,.034,.075,.034)),[.055,.075,.085,1]);
    this.drawCube(projection,view,this.multiply(base,this.transform(0,.047,0,.055,.025,.052)),[.09,.12,.13,1]);
    this.drawCube(projection,view,this.multiply(base,this.transform(0,.071,-.014,.019,.009,.019)),accent);
    if (gamepad?.buttons[0]?.pressed)
      this.drawCube(projection,view,this.multiply(base,this.transform(0,.071,-.014,.025,.014,.025)),[1,.82,.34,1]);
  }

  render(frame,viewer,leftInput,rightInput) {
    const gl=this.gl, layer=xrSession.renderState.baseLayer;
    gl.bindFramebuffer(gl.FRAMEBUFFER,layer.framebuffer);
    this.updateMenu();
    for (const view of viewer.views) {
      const viewport=layer.getViewport(view);
      gl.viewport(viewport.x,viewport.y,viewport.width,viewport.height);
      gl.enable(gl.SCISSOR_TEST); gl.scissor(viewport.x,viewport.y,viewport.width,viewport.height);
      this.drawSky();
      gl.clearDepth(1); gl.clear(gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL);
      const projection=view.projectionMatrix, camera=view.transform.inverse.matrix;
      this.drawCube(projection,camera,this.transform(0,-.055,-1.8,4,.025,4),[.045,.14,.15,1]);
      this.drawCube(projection,camera,this.transform(-1.65,.34,-2.1,.012,.38,.012),[.25,.7,.62,1]);
      this.drawCube(projection,camera,this.transform(1.65,.34,-2.1,.012,.38,.012),[.25,.7,.62,1]);
      this.drawMenu(projection,camera);
      const leftPose=leftInput?.gripSpace ? frame.getPose(leftInput.gripSpace,referenceSpace) : null;
      const rightPose=rightInput?.gripSpace ? frame.getPose(rightInput.gripSpace,referenceSpace) : null;
      this.drawController(projection,camera,leftPose,"left",leftInput?.gamepad);
      this.drawController(projection,camera,rightPose,"right",rightInput?.gamepad);
      gl.disable(gl.SCISSOR_TEST);
    }
  }
}

async function flush() {
  if (sending || pending.length === 0) return;
  sending = true;
  const samples = pending.splice(0,60);
  try {
    const response = await fetch("/api/samples", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({protocolVersion:1,sessionId,samples})});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    ui.uploadState.textContent="OK"; ui.uploadDetail.textContent=`${samples.length} últimas`;
  } catch (error) {
    pending.unshift(...samples); pending=pending.slice(-120);
    ui.uploadState.textContent="ERROR"; ui.uploadDetail.textContent=error.message;
  } finally { sending=false; }
}

function onXRFrame(time,frame) {
  xrSession.requestAnimationFrame(onXRFrame);
  const viewer=frame.getViewerPose(referenceSpace);
  const head=viewer ? poseData(viewer.views[0]) : null;
  const leftInput=[...xrSession.inputSources].find(x=>x.handedness==="left");
  const rightInput=[...xrSession.inputSources].find(x=>x.handedness==="right");
  const left=controllerData(leftInput,frame), right=controllerData(rightInput,frame);
  pending.push({sequence:sequence++,clientTime:performance.now(),head,left,right});
  if (pending.length>120) pending.shift();
  showPose("head",head); showPose("left",left?.grip||left?.ray||null); showPose("right",right?.grip||right?.ray||null);
  ui.sampleCount.textContent=sequence.toLocaleString();
  rateWindow.push(time); while(rateWindow.length&&rateWindow[0]<time-1000) rateWindow.shift();
  ui.rate.textContent=rateWindow.length;
  if (viewer) renderer.render(frame,viewer,leftInput,rightInput);
}

async function enterVR() {
  try {
    sessionId=`${Date.now().toString(36)}-${crypto.randomUUID().slice(0,8)}`; sequence=0; pending=[];
    xrSession=await navigator.xr.requestSession("immersive-vr",{requiredFeatures:["local-floor"]});
    const canvas=document.getElementById("xrCanvas"), gl=canvas.getContext("webgl",{xrCompatible:true,alpha:false,antialias:true});
    await gl.makeXRCompatible();
    xrSession.updateRenderState({baseLayer:new XRWebGLLayer(xrSession,gl),depthNear:.05,depthFar:30});
    referenceSpace=await xrSession.requestReferenceSpace("local-floor");
    renderer=new XRScene(gl);
    xrSession.addEventListener("end",endSession);
    ui.status.textContent="Capturando tracking"; ui.detail.textContent="Entorno activo · ningún comando de robot";
    ui.signalDot.style.background="var(--green)"; ui.sessionLabel.textContent=`Sesión ${sessionId}`;
    ui.enterVr.textContent="Salir de VR"; ui.enterVr.onclick=()=>xrSession.end();
    xrSession.requestAnimationFrame(onXRFrame);
  } catch(error) { ui.status.textContent="No se pudo iniciar VR"; ui.detail.textContent=error.message; }
}

function endSession() {
  xrSession=null; referenceSpace=null; renderer=null; flush();
  ui.status.textContent="Quest listo"; ui.detail.textContent="La sesión terminó de forma segura";
  ui.enterVr.textContent="Entrar en VR"; ui.enterVr.onclick=enterVR;
}

async function boot() {
  try {
    const response=await fetch("/api/status"); if(!response.ok) throw new Error("Servidor no disponible");
    if(!navigator.xr) throw new Error("Este navegador no expone WebXR");
    if(!await navigator.xr.isSessionSupported("immersive-vr")) throw new Error("Modo immersive-vr no disponible");
    ui.status.textContent="Quest listo"; ui.detail.textContent="Servidor local conectado · WebXR disponible";
    ui.enterVr.disabled=false; ui.enterVr.onclick=enterVR; ui.signalDot.style.background="var(--green)";
  } catch(error) { ui.status.textContent="Abrí esta URL en el Quest"; ui.detail.textContent=error.message; }
}

setInterval(flush,100);
boot();
