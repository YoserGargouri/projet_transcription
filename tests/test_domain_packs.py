"""Les deux packs se chargent et se valident ; un pack incorrect est refusé avec un message clair."""
import shutil
from pathlib import Path

import pytest
import yaml

from agentkit.domain import DomainPack, DomainPackError, load_domain

DOMAINES = Path(__file__).resolve().parents[1] / "domains"


@pytest.mark.parametrize("nom", ["imagerie_medicale", "demo_minimal"])
def test_les_packs_se_chargent(nom):
    pack = load_domain(nom, recharger=True)
    assert pack.id == nom and pack.language == "fr"
    assert pack.default_intent.handler == "escalate"
    assert all(i.handler != "knowledge" or pack.knowledge for i in pack.intents)


def test_variables_d_environnement(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voix-test")
    pack = load_domain("imagerie_medicale", recharger=True)
    assert pack.channels.audio.tts.voice_id == "voix-test"
    assert pack.channels.audio.tts.model_id == "eleven_flash_v2_5"     # valeur par défaut ${...:-...}


def test_schema_json_exportable():
    """Le futur générateur de packs recevra ce schéma JSON."""
    schema = DomainPack.model_json_schema()
    assert {"intents", "catalogue", "workflows", "tools", "safety_scripts"} <= set(schema["properties"])


def _pack_modifie(tmp_path, modif):
    copie = tmp_path / "pack"
    shutil.copytree(DOMAINES / "demo_minimal", copie)
    data = yaml.safe_load((copie / "domain.yaml").read_text(encoding="utf-8"))
    modif(data)
    (copie / "domain.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return copie


@pytest.mark.parametrize("modif, message", [
    (lambda d: d["intents"].append(dict(d["intents"][0])), "en double"),
    (lambda d: d["intents"][1].update(handler="workflow:inconnu"), "workflow inconnu"),
    (lambda d: d.update(cle_inconnue=1), "cle_inconnue"),
    (lambda d: d["catalogue"].update(file="data/absent.csv"), "catalogue introuvable"),
    (lambda d: d["catalogue"]["attributes"][0].update(column="colonne_absente"), "colonne absente"),
    (lambda d: d["safety_scripts"][0].update(applies_if={"couleur": ["rouge"]}), "attributs inconnus"),
    (lambda d: d["tools"][0].update(entrypoint="../hors_pack.py:X"), "entrypoint"),
])
def test_un_pack_incorrect_est_refuse(tmp_path, modif, message):
    with pytest.raises(DomainPackError, match=message):
        load_domain(_pack_modifie(tmp_path, modif), recharger=True)


def test_cle_du_gazetteer_inconnue(tmp_path):
    copie = _pack_modifie(tmp_path, lambda d: None)
    (copie / "data" / "gazetteer.yaml").write_text("type:\n  tandem: [tandem]\n", encoding="utf-8")
    with pytest.raises(DomainPackError, match="tandem"):
        load_domain(copie, recharger=True)
