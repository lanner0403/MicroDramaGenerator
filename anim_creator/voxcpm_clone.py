"""VoxCPM 聲線克隆：用角色參考音重做對白。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_MODEL: Any = None
_MODEL_ID: str | None = None


class VoxCPMError(RuntimeError):
    pass


def _flush_cuda() -> None:
    import gc
    try:
        import torch
    except ImportError:
        gc.collect()
        return
    gc.collect()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def free_voxcpm() -> bool:
    global _MODEL, _MODEL_ID
    if _MODEL is None:
        return False
    model = _MODEL
    _MODEL = _MODEL_ID = None
    try:
        del model
        _flush_cuda()
    except Exception:
        pass
    return True


def _get_model(model_id: str):
    global _MODEL, _MODEL_ID
    mid = (model_id or "openbmb/VoxCPM2").strip() or "openbmb/VoxCPM2"
    if _MODEL is not None and _MODEL_ID == mid:
        return _MODEL
    if _MODEL is not None:
        free_voxcpm()
    try:
        from voxcpm import VoxCPM
    except ImportError as e:
        raise VoxCPMError("未安裝 voxcpm。請 pip install voxcpm soundfile") from e
    _MODEL = VoxCPM.from_pretrained(mid, load_denoiser=False)
    _MODEL_ID = mid
    return _MODEL


def _ensure_wav(src: Path, dest: Path, ffmpeg: str | None) -> Path:
    if src.suffix.lower() == ".wav" and src.is_file():
        return src
    if not ffmpeg:
        raise VoxCPMError("參考音不是 wav，且找不到 ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    import subprocess
    r = subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-ac", "1", "-ar", "16000", str(dest),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        raise VoxCPMError(f"參考音轉 wav 失敗：{(r.stderr or '')[-300:]}")
    return dest


def clone_dialogue(
    text: str,
    ref_wav: Path,
    out_wav: Path,
    *,
    model_id: str = "openbmb/VoxCPM2",
    prompt_text: str = "",
    ffmpeg: str | None = None,
) -> Path:
    """用參考音克隆 text，寫成 out_wav。"""
    spoken = (text or "").strip().strip("「」『』\"'")
    if not spoken:
        raise VoxCPMError("沒有對白可克隆")
    if not ref_wav.is_file():
        raise VoxCPMError(f"找不到參考音：{ref_wav}")
    wav_ref = _ensure_wav(ref_wav, out_wav.parent / "_voice_ref.wav", ffmpeg)
    model = _get_model(model_id)
    kwargs: dict[str, Any] = {
        "text": spoken,
        "reference_wav_path": str(wav_ref),
        "cfg_value": 2.0,
        "inference_timesteps": 10,
    }
    prompt = (prompt_text or "").strip()
    if prompt:
        kwargs["prompt_wav_path"] = str(wav_ref)
        kwargs["prompt_text"] = prompt
    try:
        import soundfile as sf
    except ImportError as e:
        raise VoxCPMError("未安裝 soundfile。請 pip install soundfile") from e
    audio = model.generate(**kwargs)
    sr = getattr(getattr(model, "tts_model", None), "sample_rate", None) or 48000
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), audio, int(sr))
    if not out_wav.is_file() or out_wav.stat().st_size <= 0:
        raise VoxCPMError("VoxCPM 沒有寫出音檔")
    return out_wav
