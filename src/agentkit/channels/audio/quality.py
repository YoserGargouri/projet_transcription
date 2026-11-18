"""
Qualité audio mesurée AVANT la transcription (WP2).

estimer_snr() découpe l'audio en trames de 32 ms et compare les trames les plus fortes
(la parole) aux plus faibles (le bruit de fond, entre les mots).
Pas besoin de la version propre de l'audio : on peut l'utiliser sur un vrai appel.
Servira en S2 à décider : transcrire / faire répéter / transférer à un humain.
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
