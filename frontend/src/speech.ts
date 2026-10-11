/** Browser speech helpers (Web Speech API). Everything degrades gracefully where unsupported. */
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;
export function speak(text: string, lang = "en-US") {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/^\[DEMO MODE[^\]]*\]\s*/, ""));
  u.lang = lang; u.rate = 0.95;
  const v = window.speechSynthesis.getVoices().find((x) => x.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}
export const stopSpeaking = () => canSpeak() && window.speechSynthesis.cancel();

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Rec = (): any => typeof window === "undefined" ? null : (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition ?? null;
export const canListen = () => Rec() !== null;
/** One-shot dictation. Returns a stop function. */
export function listen(onText: (t: string) => void, onEnd: () => void, lang = "en-US"): () => void {
  const R = Rec(); if (!R) { onEnd(); return () => {}; }
  const r = new R(); r.lang = lang; r.interimResults = false; r.maxAlternatives = 1;
  r.onresult = (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => onText(e.results[0][0].transcript);
  r.onend = onEnd; r.onerror = onEnd;
  r.start();
  return () => r.stop();
}
