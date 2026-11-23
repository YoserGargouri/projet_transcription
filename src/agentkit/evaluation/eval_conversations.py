"""
Scénarios de conversation de bout en bout, déclarés par le pack (evaluation.conversations).

    python -m agentkit.evaluation.eval_conversations --domaine imagerie_medicale --mode texte
    python -m agentkit.evaluation.eval_conversations --mode voix          # pipeline audio complet

Mode texte : chaque phrase est envoyée telle quelle à l'agent (les fautes écrites dans le
scénario, « ronds des vous », arrivent intactes au LLM).
Mode voix : la phrase de l'appelant est dite par une voix de synthèse gratuite (gTTS), puis
    audio -> qualité -> STT du pack -> agent (LLM) -> TTS du pack (ElevenLabs) -> audio,
et on vérifie que le texte envoyé au TTS est exactement la réponse produite, puis que l'audio
produit dit bien ce texte (retranscription par le STT, taux d'erreur de mots).

Pour chaque tour : LLM appelé ou non (et pourquoi), intention, sources citées, vérifications du
scénario, latences par étape. Rapport : results/<pack>/conversations_<mode>.md (+ .json).
Coût : appels LLM réels ; en mode voix, des caractères ElevenLabs (estimation affichée avant).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import yaml

from agentkit import config
from agentkit.domain import load_domain
from agentkit.nlu.text import normalise
from agentkit.llm.gateway import gateway_from_env
from agentkit.orchestrator import Orchestrator


def _agenda_neuf(pack, mode):
    """Agenda vide propre à cette évaluation (runtime/scenarios/) : les scénarios ne dépendent pas
    des réservations des essais précédents, et l'agenda simulé habituel n'est pas touché."""
    outils = []
    for t in pack.tools:
        if t.builtin == "calendar":
            base = config.runtime_dir("scenarios") / f"agenda_{mode}_{t.name}.sqlite"
            base.unlink(missing_ok=True)
            t = t.model_copy(update={"config": {**t.config, "database": str(base)}})
        outils.append(t)
    return pack.model_copy(update={"tools": outils})


def _remplir(texte: str, memo: dict) -> str:
    ref = memo.get("ref", "RDV-INCONNU")
    epelee = " ".join(c if c != "-" else "tiret" for c in ref)
    return texte.replace("{ref_epelee}", epelee).replace("{ref}", ref)


def _verifier(attendu: dict, r, trace: dict) -> list[tuple[str, bool]]:
    agent = trace.get("agent") or {}
    llm = bool(agent.get("llm_used")) and not trace.get("llm_failure")
    sources = (trace.get("knowledge") or {}).get("used") or agent.get("sources") or []
    rep = normalise(r.reply)
    checks = []
    if "llm" in attendu:
        checks.append((f"llm={attendu['llm']}", llm == attendu["llm"]))
    if "intent" in attendu:
        checks.append((f"intent={attendu['intent']}", agent.get("intent", r.intent) == attendu["intent"]))
    if "sources" in attendu:
        checks.append((f"sources∋{'|'.join(attendu['sources'])}", bool(set(sources) & set(attendu["sources"]))))
    for c in attendu.get("contient", []):
        checks.append((f"«{c}»", normalise(c) in rep))
    if "escalade" in attendu:
        checks.append((f"escalade={attendu['escalade']}", r.escalated == attendu["escalade"]))
    if attendu.get("reference"):
        checks.append(("reference", bool((trace.get("tool_result") or {}).get("reference"))))
    return checks


class _VoixAppelant:
    """Voix de l'appelant : gTTS (gratuit, sans crédit ElevenLabs), WAV 16 kHz mis en cache."""

    def __init__(self, langue: str):
        from agentkit.channels.audio.tts import GTTSEngine

        self.moteur = GTTSEngine(langue)
        self.dossier = config.runtime_dir("scenarios", "appelant")

    def wav(self, texte: str) -> Path:
        import soundfile as sf

        chemin = self.dossier / (hashlib.sha256(texte.encode()).hexdigest()[:20] + ".wav")
        if not chemin.exists():
            y, sr = self.moteur.synthesize(texte)
            if sr != 16000:
                import librosa

                y = librosa.resample(y, orig_sr=sr, target_sr=16000)
            sf.write(chemin, y, 16000, subtype="PCM_16")
        return chemin


def _wer(reference: str, hypothese: str) -> float:
    import jiwer

    ref, hyp = normalise(reference), normalise(hypothese)
    return round(jiwer.wer(ref, hyp), 3) if ref else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    ap.add_argument("--mode", choices=["texte", "voix"], default="texte")
    ap.add_argument("--scenarios", nargs="*", help="ids à jouer (défaut : tous)")
    ap.add_argument("--stt", help="forcer le moteur STT (mode voix)")
    ap.add_argument("--tts", choices=["elevenlabs", "gtts", "piper"], help="forcer le moteur TTS (mode voix)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    config.configurer_journal(args.verbose)

    pack = _agenda_neuf(load_domain(args.domaine), args.mode)
    if not pack.evaluation.conversations:
        sys.exit(f"le pack {pack.id} ne déclare pas evaluation.conversations")
    scenarios = yaml.safe_load(pack.path(pack.evaluation.conversations).read_text(encoding="utf-8"))
    if args.scenarios:
        scenarios = [s for s in scenarios if s["id"] in args.scenarios]

    stt = tts = appelant = None
    if args.mode == "voix":
        from agentkit.channels.audio.stt import creer_moteur
        from agentkit.channels.audio.tts import TTSService

        spec = pack.channels.audio
        stt = creer_moteur(args.stt or spec.stt.engine, langue=pack.language, prompt=spec.stt.prompt)
        tts = TTSService.from_pack(pack, engine=args.tts)
        appelant = _VoixAppelant(pack.language)
        envoye: list[str] = []
        synthese = tts.synthesize

        def espion(texte, sortie):                            # ce que reçoit réellement le TTS
            envoye.append(texte)
            return synthese(texte, sortie)
        tts.synthesize = espion
        n = sum(len(s["tours"]) for s in scenarios)
        print(f"[mode voix | STT {stt.nom} | TTS {tts.engines[0].name} | {n} tours, ≈ {n * 110} caractères "
              f"de TTS facturés au plus (cache : 0 pour une phrase déjà synthétisée)]")

    memo, lignes, bilan = {}, [], {"tours": 0, "checks": 0, "ok": 0, "llm": 0, "tts_chars": 0}
    for sc in scenarios:
        orch = Orchestrator(pack, gateway=gateway_from_env())
        if orch.gateway is None:
            sys.exit("aucun LLM configuré (.env) : ce test vérifie justement le LLM")
        orch.warmup()
        canal = None
        if args.mode == "voix":
            from agentkit.channels.audio.channel import AudioChannel

            canal = AudioChannel(orch, stt=stt, tts=tts)
        orch.start()
        dossier = config.runtime_dir("scenarios", f"{args.mode}_{sc['id']}")
        print(f"\n=== {sc['id']} : {sc['titre']}")
        for i, tour in enumerate(sc["tours"], start=1):
            dit = _remplir(tour["dit"], memo)
            ligne = {"scenario": sc["id"], "tour": i, "dit": dit}
            t0 = time.perf_counter()
            if canal is None:
                r = orch.handle_text(dit)
                ligne["timings"] = {"agent_s": round(time.perf_counter() - t0, 2)}
            else:
                envoye.clear()
                ar = canal.handle_audio(appelant.wav(dit), dossier / f"{i:02d}_agent.wav")
                r = ar.turn
                ligne.update(transcription=ar.transcript, confiance_stt=round(ar.stt_confidence, 2),
                             timings=ar.timings, tts_moteur=ar.timings.get("tts_engine"),
                             tts_texte_identique=envoye == [r.reply])
                if not ar.timings.get("tts_cached") and ar.timings.get("tts_engine") == "elevenlabs":
                    bilan["tts_chars"] += len(r.reply)
                retrans = stt.transcrire(ar.reply_audio)["texte"]     # l'audio dit-il bien la réponse ?
                ligne.update(audio_retranscrit=retrans, wer_audio=_wer(r.reply, retrans))
            trace = r.trace
            if (ref := (trace.get("tool_result") or {}).get("reference")) and tour.get("attendu", {}).get("reference"):
                memo["ref"] = ref
            checks = _verifier(tour.get("attendu", {}), r, trace)
            agent = trace.get("agent") or {}
            ligne.update(reponse=r.reply, resume_llm=config.resume_agent(trace),
                         llm_utilise=bool(agent.get("llm_used")) and not trace.get("llm_failure"),
                         intention=agent.get("intent", r.intent), sources=(trace.get("knowledge") or {}).get("used"),
                         escalade=r.escalation_reason, checks=[{"verif": c, "ok": ok} for c, ok in checks])
            lignes.append(ligne)
            bilan["tours"] += 1
            bilan["llm"] += ligne["llm_utilise"]
            bilan["checks"] += len(checks)
            bilan["ok"] += sum(ok for _, ok in checks)
            print(f"  appelant > {dit}")
            if canal is not None:
                print(f"  STT      > {ligne['transcription']}   [confiance {ligne['confiance_stt']}]")
            print(f"  agent    > {r.reply}")
            print(f"             {ligne['resume_llm']}")
            if canal is not None:
                print(f"             TTS {ligne['tts_moteur']} ; texte envoyé = réponse : {ligne['tts_texte_identique']} ;"
                      f" audio retranscrit (WER {ligne['wer_audio']}) : {ligne['audio_retranscrit']}")
            print(f"             vérifs : {' '.join(('✓ ' if ok else '✗ ') + c for c, ok in checks) or '-'}"
                  f"   latences : {json.dumps(ligne['timings'], ensure_ascii=False)}")
            if r.escalated:
                break
        if orch.gateway:
            bilan.setdefault("usage_llm", []).append(orch.gateway.usage.snapshot())

    _rapport(pack, args.mode, lignes, bilan)


def _rapport(pack, mode, lignes, bilan):
    dossier = config.REPO_ROOT / "results" / pack.id
    dossier.mkdir(parents=True, exist_ok=True)
    usage = bilan.pop("usage_llm", [])
    tot = {k: sum(u.get(k, 0) for u in usage) for k in ("logical_calls", "requests", "errors", "total_tokens")}
    lat = [l["timings"].get("total_s", l["timings"].get("agent_s", 0)) for l in lignes]
    md = [f"# Scénarios de conversation — {pack.id} — mode {mode}", "",
          f"- tours : {bilan['tours']} ; LLM utilisé : {bilan['llm']} tours",
          f"- vérifications réussies : {bilan['ok']} / {bilan['checks']}",
          f"- appels LLM : {tot['logical_calls']} (requêtes {tot['requests']}, erreurs {tot['errors']}, "
          f"jetons {tot['total_tokens']})",
          f"- latence par tour : moyenne {sum(lat) / max(len(lat), 1):.1f} s, max {max(lat or [0]):.1f} s"]
    if mode == "voix":
        wer = [l["wer_audio"] for l in lignes if "wer_audio" in l]
        md += [f"- caractères ElevenLabs facturés : {bilan['tts_chars']}",
               f"- texte envoyé au TTS = réponse de l'agent : {sum(l['tts_texte_identique'] for l in lignes)} / {len(lignes)}",
               f"- audio produit retranscrit : WER moyen {sum(wer) / max(len(wer), 1):.3f}"]
    md += ["", "| scénario | # | appelant | transcription | réponse de l'agent | LLM | vérifs | latence |",
           "|---|---|---|---|---|---|---|---|"]
    for l in lignes:
        v = " ".join(("✓" if c["ok"] else "✗") + c["verif"] for c in l["checks"]) or "-"
        t = l["timings"].get("total_s", l["timings"].get("agent_s"))
        cell = lambda x: str(x or "").replace("|", "/")
        md.append(f"| {l['scenario']} | {l['tour']} | {cell(l['dit'])} | {cell(l.get('transcription', '—'))} | "
                  f"{cell(l['reponse'])} | {cell(l['resume_llm'])} | {v} | {t} s |")
    (dossier / f"conversations_{mode}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (dossier / f"conversations_{mode}.json").write_text(
        json.dumps({"bilan": {**bilan, **tot}, "tours": lignes}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print("\n" + "\n".join(md[:8]))
    print(f"\nrapport : {dossier / f'conversations_{mode}.md'}")


if __name__ == "__main__":
    main()
