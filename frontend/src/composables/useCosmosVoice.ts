import { computed, onBeforeUnmount, ref } from "vue";

import { cosmosError } from "@/api/cosmos";

const MIME_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];

export type VoiceActivity = "listening" | "finished" | "empty" | "limit";

/** Detector adaptativo: aprende o ruído do microfone e não o confunde com fala contínua. */
export function createVoiceActivityDetector(startedAt: number) {
  let noiseFloor = 0.008;
  let loudFrames = 0;
  let speechStarted = false;
  let quietSince: number | null = null;

  return (level: number, now: number): VoiceActivity => {
    const elapsed = now - startedAt;
    if (elapsed < 400) {
      noiseFloor = noiseFloor * 0.7 + level * 0.3;
      return "listening";
    }
    const threshold = Math.max(0.018, Math.min(0.075, noiseFloor * 1.8 + 0.008));
    if (level >= threshold) {
      loudFrames += 1;
      if (loudFrames >= 3) {
        speechStarted = true;
        quietSince = null;
      }
    } else {
      loudFrames = 0;
      if (speechStarted) quietSince ??= now;
      else noiseFloor = noiseFloor * 0.96 + level * 0.04;
    }
    if (speechStarted && quietSince !== null && now - quietSince >= 1200) return "finished";
    if (!speechStarted && elapsed >= 10_000) return "empty";
    if (elapsed >= 60_000) return "limit";
    return "listening";
  };
}

export function useCosmosVoice(transcribe: (audio: Blob) => Promise<string>, onTranscript: (text: string) => boolean,
                               canListen: () => boolean) {
  const active = ref(false);
  const listening = ref(false);
  const transcribing = ref(false);
  const interim = ref("");
  const error = ref("");
  const waitingReply = ref(false);
  const supported = Boolean(typeof navigator.mediaDevices?.getUserMedia === "function"
    && typeof MediaRecorder !== "undefined" && typeof AudioContext !== "undefined");

  let recorder: MediaRecorder | null = null;
  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let animationFrame: number | undefined;
  let retryTimer: number | undefined;
  let starting = false;
  let discardRecording = false;
  let chunks: Blob[] = [];

  const label = computed(() => {
    if (transcribing.value) return "Entendendo sua fala…";
    if (waitingReply.value) return "Cosmos está respondendo…";
    if (listening.value) return "Ouvindo…";
    return "Microfone ativo";
  });

  function cleanupInput() {
    if (animationFrame !== undefined) cancelAnimationFrame(animationFrame);
    animationFrame = undefined;
    void audioContext?.close().catch(() => undefined);
    audioContext = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
  }

  function scheduleListen(delay = 300) {
    window.clearTimeout(retryTimer);
    retryTimer = window.setTimeout(() => void listen(), delay);
  }

  function microphoneError(reason: unknown) {
    const name = reason instanceof DOMException ? reason.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") {
      active.value = false;
      return "Permita o uso do microfone no navegador para conversar por voz.";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      active.value = false;
      return "Nenhum microfone foi encontrado neste dispositivo.";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "O microfone está sendo usado por outro aplicativo. Feche-o e tente novamente.";
    }
    return "Não consegui acessar o microfone. Confira a permissão do navegador.";
  }

  function watchSilence(input: MediaStream) {
    audioContext = new AudioContext();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    audioContext.createMediaStreamSource(input).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const startedAt = performance.now();
    const activity = createVoiceActivityDetector(startedAt);

    const measure = (now: number) => {
      if (!recorder || recorder.state !== "recording") return;
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) energy += ((sample - 128) / 128) ** 2;
      const level = Math.sqrt(energy / samples.length);
      const state = activity(level, now);
      if (state === "finished" || state === "limit") return finish();
      if (state === "empty") {
        discardRecording = true;
        error.value = "Não ouvi nenhuma fala. Tente novamente mais perto do microfone.";
        return finish();
      }
      animationFrame = requestAnimationFrame(measure);
    };
    animationFrame = requestAnimationFrame(measure);
  }

  async function listen() {
    if (!supported || starting || listening.value || !active.value || waitingReply.value
      || transcribing.value || !canListen()) return;
    starting = true;
    discardRecording = false;
    chunks = [];
    try {
      const input = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!active.value) {
        input.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = input;
      const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(input, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => void recorded();
      recorder.start(250);
      listening.value = true;
      error.value = "";
      watchSilence(input);
    } catch (reason) {
      cleanupInput();
      error.value = microphoneError(reason);
      if (active.value) scheduleListen(1500);
    } finally {
      starting = false;
    }
  }

  async function recorded() {
    listening.value = false;
    const type = recorder?.mimeType || chunks[0]?.type || "audio/webm";
    const audio = new Blob(chunks, { type });
    cleanupInput();
    if (discardRecording || !active.value) {
      discardRecording = false;
      if (active.value) scheduleListen(1000);
      return;
    }
    transcribing.value = true;
    waitingReply.value = true;
    try {
      const text = (await transcribe(audio)).trim();
      if (!text || !onTranscript(text)) {
        waitingReply.value = false;
        scheduleListen();
      }
    } catch (reason) {
      waitingReply.value = false;
      error.value = cosmosError(reason, "Não consegui transcrever o áudio. Tente novamente.");
      scheduleListen(1500);
    } finally {
      transcribing.value = false;
    }
  }

  function finish() {
    if (recorder?.state === "recording") recorder.stop();
  }

  function start() {
    error.value = "";
    if (!supported) {
      error.value = "Este navegador não permite gravar áudio. Atualize o navegador.";
      return;
    }
    active.value = true;
    waitingReply.value = false;
    void listen();
  }

  function stop() {
    active.value = false;
    waitingReply.value = false;
    transcribing.value = false;
    listening.value = false;
    interim.value = "";
    discardRecording = true;
    window.clearTimeout(retryTimer);
    if (recorder?.state === "recording") recorder.stop();
    else cleanupInput();
  }

  /** Libera a escuta quando uma resposta foi parada ou terminou com erro antes de gerar uma fala. */
  function resume() {
    waitingReply.value = false;
    if (active.value) scheduleListen();
  }

  onBeforeUnmount(stop);
  return { active, listening, transcribing, interim, error, label, supported, start, stop, finish, resume };
}
