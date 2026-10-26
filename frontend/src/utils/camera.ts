/** Há câmera neste navegador? (o botão de ler pela câmera só aparece com ela; exige HTTPS ou localhost) */
export const cameraAvailable = () => typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
