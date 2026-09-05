// ============================================================================
// ARCHIVO PROTEGIDO — sistema de rostro animado y captura de audio del mic.
// Copiado tal cual desde el app.js anterior a la Fase 6 (rediseño de UI).
// NO MODIFICAR esta logica: manifest/posicionamiento, parpadeo, lip-sync,
// y captura/codificacion de audio del microfono. Cualquier cambio visual
// de la interfaz nueva se hace en app.js/theme.css alrededor de esto, no
// aqui adentro.
// ============================================================================

const micButton = document.getElementById("mic-button");
const faceBaseEl = document.getElementById("face-base");
const faceMouthEl = document.getElementById("face-mouth");
const faceEyeLeftEl = document.getElementById("face-eye-left");
const faceEyeRightEl = document.getElementById("face-eye-right");

// --- Rostro animado: superpone una boca recortada sobre la foto base y la
// cambia de forma segun el volumen del audio que se esta reproduciendo
// (no hay timing real de visemas de edge-tts, asi que se aproxima por
// amplitud: silencio -> cerrada, volumen medio -> semi-abierta, fuerte ->
// abierta).
const manifest = window.FACE_MANIFEST;
let audioCtx = null;
let analyser = null;

function positionOverlay(el, bbox) {
  el.style.left = `${(bbox.x / manifest.base_size.w) * 100}%`;
  el.style.top = `${(bbox.y / manifest.base_size.h) * 100}%`;
  el.style.width = `${(bbox.w / manifest.base_size.w) * 100}%`;
  el.style.height = `${(bbox.h / manifest.base_size.h) * 100}%`;
  el.style.display = "block";
}

if (manifest) {
  faceBaseEl.src = manifest.base_image;

  faceMouthEl.src = manifest.mouth_shapes.closed;
  positionOverlay(faceMouthEl, manifest.mouth_bbox);

  faceEyeLeftEl.src = manifest.eyes.left.shapes.open;
  positionOverlay(faceEyeLeftEl, manifest.eyes.left.bbox);
  faceEyeRightEl.src = manifest.eyes.right.shapes.open;
  positionOverlay(faceEyeRightEl, manifest.eyes.right.bbox);

  scheduleBlink();
}

// --- Parpadeo: independiente del audio, en intervalos aleatorios para
// que no se vea como un metronomo.
function blinkOnce() {
  faceEyeLeftEl.src = manifest.eyes.left.shapes.closed;
  faceEyeRightEl.src = manifest.eyes.right.shapes.closed;
  setTimeout(() => {
    faceEyeLeftEl.src = manifest.eyes.left.shapes.open;
    faceEyeRightEl.src = manifest.eyes.right.shapes.open;
  }, 140);
}

function scheduleBlink() {
  const delay = 2500 + Math.random() * 3500;
  setTimeout(() => {
    blinkOnce();
    scheduleBlink();
  }, delay);
}

const MOUTH_RMS_HALF_OPEN = 0.02;
const MOUTH_RMS_OPEN = 0.06;

function setMouthShape(shape) {
  if (!manifest || faceMouthEl.dataset.shape === shape) return;
  faceMouthEl.dataset.shape = shape;
  faceMouthEl.src = manifest.mouth_shapes[shape];
}

function getAnalyser() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    analyser.connect(audioCtx.destination);
  }
  return analyser;
}

function playWithLipSync(audio) {
  if (!manifest) {
    audio.play().catch(() => {});
    return;
  }
  try {
    const activeAnalyser = getAnalyser();
    const source = audioCtx.createMediaElementSource(audio);
    source.connect(activeAnalyser);
    const samples = new Uint8Array(activeAnalyser.fftSize);
    let rafId = null;

    const tick = () => {
      activeAnalyser.getByteTimeDomainData(samples);
      let sumSquares = 0;
      for (let i = 0; i < samples.length; i++) {
        const v = (samples[i] - 128) / 128;
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / samples.length);
      if (rms > MOUTH_RMS_OPEN) setMouthShape("open");
      else if (rms > MOUTH_RMS_HALF_OPEN) setMouthShape("half_open");
      else setMouthShape("closed");
      rafId = requestAnimationFrame(tick);
    };

    audio.addEventListener("play", () => {
      rafId = requestAnimationFrame(tick);
    });
    audio.addEventListener("ended", () => {
      cancelAnimationFrame(rafId);
      setMouthShape("closed");
    });
    audio.play().catch(() => {});
  } catch (err) {
    audio.play().catch(() => {});
  }
}

// MediaRecorder.stop() tumba el proceso completo en este Chromium
// embebido (bug de la version de QtWebEngine, no del codec). Se evita
// por completo: se captura PCM crudo con Web Audio API y se arma un
// WAV a mano en JS.
let isRecording = false;
let audioContext = null;
let sourceNode = null;
let processorNode = null;
let micStream = null;
let pcmChunks = [];

async function startRecording() {
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });

  audioContext = new AudioContext();
  sourceNode = audioContext.createMediaStreamSource(micStream);
  processorNode = audioContext.createScriptProcessor(4096, 1, 1);
  pcmChunks = [];

  processorNode.onaudioprocess = (e) => {
    pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };

  // Chrome exige que el ScriptProcessorNode este conectado a un destino
  // para disparar onaudioprocess - se enruta a un gain en 0 para no
  // producir eco por los parlantes.
  const silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  sourceNode.connect(processorNode);
  processorNode.connect(silentGain);
  silentGain.connect(audioContext.destination);

  isRecording = true;
  micButton.classList.add("recording");
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, text) => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([view], { type: "audio/wav" });
}

function stopRecording() {
  isRecording = false;
  micButton.classList.remove("recording");

  processorNode.disconnect();
  sourceNode.disconnect();
  micStream.getTracks().forEach((track) => track.stop());
  audioContext.close();

  const totalLength = pcmChunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of pcmChunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }

  const wavBlob = encodeWav(merged, audioContext.sampleRate);

  blobToBase64(wavBlob).then((base64) => {
    sendMessage({ type: "audio", data: base64 });
  });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

micButton.addEventListener("click", async () => {
  if (isRecording) {
    stopRecording();
    return;
  }
  try {
    await startRecording();
  } catch (err) {
    addMessage(`⚠️ No pude acceder al micrófono: ${err.message}`, "atlas");
  }
});
