"""
Qualité audio mesurée AVANT la transcription (WP2).

estimer_snr() découpe l'audio en trames de 32 ms et compare les trames les plus fortes
(la parole) aux plus faibles (le bruit de fond, entre les mots).
Pas besoin de la version propre de l'audio : on peut l'utiliser sur un vrai appel.
decision() combine ces mesures et la confiance du STT : continuer, faire confirmer ou
redemander ; seuils fixés par le pack (channels.audio.quality).
"""
import librosa
import numpy as np

SNR_MAX = 60.0  # un audio parfaitement propre est plafonné à 60 dB


def estimer_snr(y: np.ndarray, sr: int) -> float:
    """SNR estimé en dB (approximatif : sert à classer les audios, pas à mesurer finement)."""
    energie = librosa.feature.rms(y=y, frame_length=512, hop_length=256)[0] ** 2
    p_bruit = np.percentile(energie, 10)   # trames les plus calmes : bruit de fond
    p_fort = np.percentile(energie, 90)    # trames les plus fortes : parole + bruit
    if p_bruit < 1e-10:
        return SNR_MAX
    snr = 10 * np.log10(max(p_fort - p_bruit, 1e-12) / p_bruit)
    return float(min(snr, SNR_MAX))


# --- Filtrage et décision qualité (seuils : channels.audio.quality du pack) ------------------
SR = 16000


def pretraiter(y: np.ndarray, sr: int):
    """Filtrage avant transcription : mono, 16 kHz, passe-haut 80 Hz (ronflement, souffle du
    micro), volume normalisé. Renvoie (signal, 16000)."""
    from scipy.signal import butter, sosfilt

    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    if len(y) > 2048:
        y = sosfilt(butter(4, 80, btype="highpass", fs=SR, output="sos"), y).astype(np.float32)
    pic = float(np.max(np.abs(y))) if len(y) else 0.0
    return (0.9 * y / pic if pic > 1e-6 else y), SR


def diagnostic(y: np.ndarray, sr: int, min_duration_s: float = 0.4) -> dict:
    """Mesures prises AVANT la transcription (sur le signal brut, avant normalisation)."""
    duree = len(y) / sr
    niveau = 20 * np.log10(np.sqrt(np.mean(np.square(y))) + 1e-12) if len(y) else -120.0
    return {"duree_s": round(duree, 2), "niveau_db": round(float(niveau), 1),
            "snr_db": round(estimer_snr(y, sr), 1) if duree >= min_duration_s else 0.0}


def decision(diag: dict, seuils, confiance_stt: float | None = None, texte: str | None = None) -> str:
    """« ok » | « confirmer » | « redemander ».

    seuils : channels.audio.quality du pack (min_duration_s, min_level_db, snr_bad_db,
    snr_medium_db, conf_bad, conf_medium). Le transfert après plusieurs échecs est décidé par
    la politique d'escalade (max_audio_failures).
    """
    if diag["duree_s"] < seuils.min_duration_s or diag["niveau_db"] < seuils.min_level_db:
        return "redemander"
    if texte is not None and not texte.strip():
        return "redemander"
    if confiance_stt is None:
        return "redemander" if diag["snr_db"] < seuils.snr_bad_db else "ok"
    if confiance_stt < seuils.conf_bad or (diag["snr_db"] < seuils.snr_bad_db and confiance_stt < seuils.conf_medium):
        return "redemander"
    if confiance_stt < seuils.conf_medium or diag["snr_db"] < seuils.snr_medium_db:
        return "confirmer"
    return "ok"
