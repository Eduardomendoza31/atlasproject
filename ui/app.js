const chatEl = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const micButton = document.getElementById("mic-button");

let ws = null;
let atlasBubble = null;
let typingBubble = null;

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function clearTyping() {
  if (typingBubble) {
    typingBubble.remove();
    typingBubble = null;
  }
}

function connect() {
  ws = new WebSocket("ws://127.0.0.1:8731/ws/chat");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "transcript") {
      addMessage(data.text, "user");
      typingBubble = addMessage("escribiendo…", "atlas typing");
    } else if (data.type === "chunk") {
      clearTyping();
      if (!atlasBubble) {
        atlasBubble = addMessage("", "atlas");
      }
      atlasBubble.textContent += data.text;
      chatEl.scrollTop = chatEl.scrollHeight;
    } else if (data.type === "done") {
      atlasBubble = null;
    } else if (data.type === "error") {
      clearTyping();
      atlasBubble = null;
      addMessage(`⚠️ ${data.text}`, "atlas");
    } else if (data.type === "audio_reply") {
      const audio = new Audio(`data:audio/mpeg;base64,${data.data}`);
      audio.play().catch(() => {});
    }
  };

  ws.onclose = () => {
    setTimeout(connect, 1000);
  };
}

connect();

function sendMessage(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addMessage("⚠️ Sin conexión con Atlas, reintentando...", "atlas");
    return false;
  }
  ws.send(JSON.stringify(payload));
  return true;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  if (!sendMessage({ type: "text", text })) return;
  addMessage(text, "user");
  input.value = "";
  typingBubble = addMessage("escribiendo…", "atlas typing");
});

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
