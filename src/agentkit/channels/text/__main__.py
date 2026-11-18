"""
Canal texte : conversation au clavier avec un pack de domaine.

    python -m agentkit.channels.text                      # pack de .env (DOMAIN)
    python -m agentkit.channels.text --domaine demo_minimal --trace

Le LLM est celui de .env (LLM_BASE_URL...) ; sans configuration, l'agent tourne avec les
règles seules. Taper « quit » pour arrêter.
"""
import argparse
import json

from agentkit import config
from agentkit.orchestrator import Orchestrator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    ap.add_argument("--sans-llm", action="store_true", help="forcer les règles seules")
    ap.add_argument("--trace", action="store_true", help="afficher la trace de chaque tour")
    args = ap.parse_args()

    orch = Orchestrator.from_domain(args.domaine, gateway=None if args.sans_llm else "env")
    print(f"[pack {orch.pack.id} | LLM : {orch.gateway.name if orch.gateway else 'aucun (règles seules)'}]")
    print(f"agent > {orch.start()}")
    while True:
        try:
            texte = input("vous  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texte.lower() in ("quit", "exit", "q"):
            break
        r = orch.handle_text(texte)
        print(f"agent > {r.reply}")
        if args.trace:
            print("        " + json.dumps(r.trace, ensure_ascii=False, default=str))
        if r.escalated:
            print(f"[transfert vers un humain : {r.escalation_reason}]")
            break
    if orch.gateway:
        print(f"[usage LLM : {orch.gateway.usage.snapshot()}]")


if __name__ == "__main__":
    main()
