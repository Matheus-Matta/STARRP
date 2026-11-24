import { describe, expect, it } from "vitest";

import { createVoiceActivityDetector } from "@/composables/useCosmosVoice";

describe("detector de silêncio da voz", () => {
  it("calibra ruído alto e encerra depois da fala", () => {
    const detect = createVoiceActivityDetector(0);
    for (let time = 0; time <= 400; time += 20) expect(detect(0.04, time)).toBe("listening");
    for (let time = 420; time <= 1200; time += 20) expect(detect(0.12, time)).toBe("listening");
    let state = detect(0.04, 1220);
    for (let time = 1240; time <= 2500; time += 20) state = detect(0.04, time);
    expect(state).toBe("finished");
  });

  it("não encerra durante uma pausa curta", () => {
    const detect = createVoiceActivityDetector(0);
    for (let time = 0; time <= 400; time += 20) detect(0.005, time);
    for (let time = 420; time <= 800; time += 20) detect(0.08, time);
    expect(detect(0.005, 820)).toBe("listening");
    expect(detect(0.005, 1800)).toBe("listening");
    expect(detect(0.005, 2020)).toBe("finished");
  });

  it("avisa quando ninguém fala", () => {
    const detect = createVoiceActivityDetector(0);
    for (let time = 0; time < 10_000; time += 100) detect(0.006, time);
    expect(detect(0.006, 10_000)).toBe("empty");
  });
});
