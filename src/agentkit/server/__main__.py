"""
Plateforme web : API + application.

    python -m agentkit.server                       # http://127.0.0.1:8000 (web/dist doit être construit)
    python -m agentkit.server --port 8000 -v        # étapes du moteur dans la console
    python -m agentkit.server import-logs --email vous@exemple.com --pack imagerie_medicale

Développement de l'interface : `cd web && npm run dev` (http://localhost:5173, l'API est relayée).
"""
from __future__ import annotations

import argparse
import sys

from agentkit import config


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m agentkit.server")
    sous = ap.add_subparsers(dest="cmd")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("-v", "--verbose", action="store_true", help="étapes du moteur (sans texte ni clé)")
    imp = sous.add_parser("import-logs", help="importer les journaux des essais CLI dans un espace de travail")
    imp.add_argument("--email", required=True, help="compte dont l'espace de travail reçoit l'import")
    imp.add_argument("--pack", default=config.domaine_par_defaut())
    args = ap.parse_args()

    if args.cmd == "import-logs":
        from agentkit.server.db import Database
        from agentkit.server.importer import import_logs

        db = Database()
        m = db.one("""SELECT m.workspace_id FROM members m JOIN users u ON u.id = m.user_id WHERE u.email = ?
                      ORDER BY m.rowid LIMIT 1""", (args.email.strip().lower(),))
        if m is None:
            sys.exit("aucun compte pour cet e-mail : créez-le d'abord dans l'application")
        print(import_logs(db, m["workspace_id"], args.pack))
        return

    import uvicorn

    from agentkit.server.app import create_app, web_dist_path

    config.configurer_journal(args.verbose)
    if not web_dist_path().exists():
        print("web/dist absent : seule l'API est servie (cd web && npm install && npm run build)")
    print(f"Plateforme : http://{args.host}:{args.port}   (API : /api/docs)")
    app = create_app()
    app.state.platform.sessions.preload_stt = True     # Whisper chargé dès qu'une conversation vocale commence
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
