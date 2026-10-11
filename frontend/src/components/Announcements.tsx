import { useState } from "react";
import type { AnnouncementResponse, LangCode } from "../types";
import { Empty, Loading, Tag } from "./States";
import { canSpeak, speak } from "../speech";

const ALL: { code: LangCode; label: string }[] = [{ code: "en", label: "English" }, { code: "hi", label: "हिन्दी" }, { code: "ta", label: "தமிழ்" }, { code: "es", label: "Español" }];
interface Props { data: AnnouncementResponse | null; loading: boolean; error: string | null; onGenerate: (langs: LangCode[]) => void }

/** Multilingual PA announcements for passengers, drafted from live backend facts, with text-to-speech. */
export default function Announcements({ data, loading, error, onGenerate }: Props) {
  const [langs, setLangs] = useState<LangCode[]>(["en", "hi", "ta"]);
  const [copied, setCopied] = useState<string | null>(null);
  const toggle = (c: LangCode) => setLangs((l) => (l.includes(c) ? (l.length > 1 ? l.filter((x) => x !== c) : l) : [...l, c]));
  const copy = (code: string, text: string) => { navigator.clipboard?.writeText(text).then(() => { setCopied(code); setTimeout(() => setCopied(null), 1400); }).catch(() => {}); };
  return (
    <div className="pa">
      <div className="briefing-bar">
        <fieldset className="langs"><legend className="sr-only">Languages</legend>
          {ALL.map((l) => <label key={l.code} className={`lang ${langs.includes(l.code) ? "on" : ""}`}><input type="checkbox" checked={langs.includes(l.code)} onChange={() => toggle(l.code)} />{l.label}</label>)}
        </fieldset>
        <button className="btn btn-primary btn-glow" onClick={() => onGenerate(langs)} disabled={loading}><span aria-hidden>📢</span> Draft announcements</button>
      </div>
      {loading && <Loading label="Drafting announcements…" />}
      {error && <div className="state state-error" role="alert">{error}</div>}
      {!loading && !data && !error && <Empty>Pick languages and draft a passenger announcement: it names the crowded stop, a calmer alternative and a wait time - all taken from the forecast.</Empty>}
      {!loading && data && (
        <>
          <p className="pa-situation"><b>{data.situation}.</b>{data.alternative_stop && <> Suggested alternative: <b>{data.alternative_stop}</b>.</>}{data.wait_minutes ? <> Expected to ease in ~<b>{data.wait_minutes} min</b>.</> : null}
            {" "}{data.mode === "live_llm" ? <Tag kind="model">AI · {data.provider}/{data.model}</Tag> : <Tag kind="sim">Templates · not an LLM</Tag>}</p>
          {data.fallback_reason && <p className="hint warn">LLM unavailable: {data.fallback_reason}</p>}
          <div className="pa-cards">
            {data.announcements.map((a) => (
              <figure key={a.lang} className="pa-card">
                <figcaption><b>{a.language}</b><span className={`src src-${a.source}`}>{a.source === "llm" ? "AI-written" : "template"}</span></figcaption>
                <blockquote lang={a.lang}>{a.text}</blockquote>
                <div className="pa-actions">
                  {canSpeak() && <button className="btn btn-quiet" onClick={() => speak(a.text, a.speech_lang)}>🔊 Play</button>}
                  <button className="btn btn-quiet" onClick={() => copy(a.lang, a.text)}>{copied === a.lang ? "Copied ✓" : "Copy"}</button>
                </div>
              </figure>
            ))}
          </div>
          <p className="hint">{data.disclaimer}</p>
        </>
      )}
    </div>
  );
}
