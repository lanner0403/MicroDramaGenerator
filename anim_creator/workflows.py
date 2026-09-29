"""ComfyUI workflow 模板參數化。"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

from .config import h3_turbo_spec, pick_h3_effect_loras, resolve_video_model, workflows_dir


def _load(cfg: dict, name: str) -> dict:
    path = workflows_dir(cfg) / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find(workflow: dict, class_type: str, title: str | None = None) -> list[str]:
    ids = []
    for nid, node in workflow.items():
        if node.get("class_type") != class_type:
            continue
        if title is not None and node.get("_meta", {}).get("title") != title:
            continue
        ids.append(nid)
    return ids


def _find_one(workflow: dict, class_type: str, title: str | None = None) -> str:
    ids = _find(workflow, class_type, title)
    if not ids:
        raise KeyError(f"workflow 中找不到節點 class_type={class_type} title={title}")
    return ids[0]


def _rand_seed() -> int:
    return random.randint(0, 2**48)


def _rewire(workflow: dict, old_id: str, new_ref: list) -> None:
    for node in workflow.values():
        for key, val in node.get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2 and val[0] == old_id:
                node["inputs"][key] = list(new_ref)


def _drop(workflow: dict, *node_ids: str) -> None:
    for nid in node_ids:
        workflow.pop(nid, None)


def build_image_workflow(cfg: dict, prompt: str, width: int, height: int,
                         seed: int | None = None,
                         filename_prefix: str = "AnimGenerator") -> dict:
    wf = copy.deepcopy(_load(cfg, "generate_image.json"))
    img = cfg["image"]["comfy"]
    wf[_find_one(wf, "UNETLoader")]["inputs"]["unet_name"] = img["unet"]
    wf[_find_one(wf, "CLIPLoader")]["inputs"]["clip_name"] = img["clip"]
    wf[_find_one(wf, "VAELoader")]["inputs"]["vae_name"] = img["vae"]
    latent = wf[_find_one(wf, "EmptyLatentImage")]["inputs"]
    latent["width"], latent["height"] = width, height
    ks = wf[_find_one(wf, "KSampler")]["inputs"]
    ks["seed"] = seed if seed is not None else _rand_seed()
    ks["steps"] = cfg["image"]["steps"]
    ks["cfg"] = cfg["image"]["cfg"]
    ks["sampler_name"] = img["sampler"]
    ks["scheduler"] = img["scheduler"]
    pos_id = _find_one(wf, "CLIPTextEncode", "CLIP Text Encode (Positive Prompt)")
    neg_id = _find_one(wf, "CLIPTextEncode", "CLIP Text Encode (Negative Prompt)")
    wf[pos_id]["inputs"]["text"] = f"{cfg['image']['quality_prefix']},\n{prompt}"
    wf[neg_id]["inputs"]["text"] = cfg["image"]["negative"]
    wf[_find_one(wf, "SaveImage")]["inputs"]["filename_prefix"] = filename_prefix
    return wf


def build_i2v_workflow(cfg: dict, image_name: str, prompt: str,
                       width: int, height: int, duration: int,
                       seed: int | None = None,
                       filename_prefix: str = "video/AnimGenerator",
                       video_model: str | None = None,
                       turbo_steps: int | None = None,
                       nsfw: bool = False,
                       climax: bool = False,
                       action: str = "",
                       tags: str = "",
                       extra: str = "",
                       effect_loras: list | None = None) -> dict:
    """圖生影（佔位字串模板 + class_type 微調）。"""
    model = resolve_video_model(cfg, video_model)
    name = model.get("workflow") or "video_ltx2_3_i2v.json"
    raw = json.dumps(_load(cfg, name), ensure_ascii=False)
    seed = seed if seed is not None else _rand_seed()
    esc = json.dumps(prompt, ensure_ascii=False)[1:-1]
    raw = raw.replace("%IMAGE%", image_name)
    raw = raw.replace("%PROMPT%", esc)
    raw = raw.replace('"%DURATION%"', str(int(duration)))
    raw = raw.replace('"%WIDTH%"', str(int(width)))
    raw = raw.replace('"%HEIGHT%"', str(int(height)))
    raw = raw.replace('"%SEED%"', str(int(seed)))
    wf = json.loads(raw)

    for nid in _find(wf, "PrimitiveInt", "Frame Rate"):
        wf[nid]["inputs"]["value"] = model["fps"]
    for nid in _find(wf, "CreateVideo"):
        if "fps" in wf[nid]["inputs"]:
            wf[nid]["inputs"]["fps"] = model["fps"]
    for nid in _find(wf, "RandomNoise"):
        wf[nid]["inputs"]["noise_seed"] = seed
    if model.get("checkpoint"):
        for nid in _find(wf, "CheckpointLoaderSimple"):
            wf[nid]["inputs"]["ckpt_name"] = model["checkpoint"]
        for nid in _find(wf, "LTXVAudioVAELoader"):
            wf[nid]["inputs"]["ckpt_name"] = model["checkpoint"]
    if model.get("lora"):
        for nid in _find(wf, "LoraLoaderModelOnly"):
            wf[nid]["inputs"]["lora_name"] = model["lora"]
    if model.get("upscaler"):
        for nid in _find(wf, "LatentUpscaleModelLoader"):
            wf[nid]["inputs"]["model_name"] = model["upscaler"]
    if model.get("unet"):
        for nid in _find(wf, "UNETLoader"):
            wf[nid]["inputs"]["unet_name"] = model["unet"]
    if model.get("clip"):
        for nid in _find(wf, "CLIPLoader"):
            wf[nid]["inputs"]["clip_name"] = model["clip"]
    if model.get("video_vae") or model.get("audio_vae"):
        for nid in _find(wf, "VAELoader"):
            vae = (wf[nid]["inputs"].get("vae_name") or "").lower()
            if "audio" in vae and model.get("audio_vae"):
                wf[nid]["inputs"]["vae_name"] = model["audio_vae"]
            elif model.get("video_vae"):
                wf[nid]["inputs"]["vae_name"] = model["video_vae"]
    for nid in _find(wf, "ResolutionSelector"):
        if model.get("aspect_ratio"):
            wf[nid]["inputs"]["aspect_ratio"] = model["aspect_ratio"]
        if model.get("megapixels") is not None:
            wf[nid]["inputs"]["megapixels"] = float(model["megapixels"])
    for nid in _find(wf, "CLIPTextEncode"):
        if isinstance(wf[nid]["inputs"].get("text"), str):
            wf[nid]["inputs"]["text"] = model["negative"]
    for nid in _find(wf, "SaveVideo"):
        wf[nid]["inputs"]["filename_prefix"] = filename_prefix

    _apply_prompt_enhance(wf, model)
    fx = effect_loras if effect_loras is not None else pick_h3_effect_loras(
        model, nsfw=nsfw, climax=climax, action=action, tags=tags,
        motion=prompt, extra=extra)
    _apply_h3_turbo(wf, model, "fl2v", turbo_steps, nsfw_effects=_nsfw_effects(fx))
    _apply_h3_effect_loras(wf, fx)
    return wf


def build_r2v_workflow(cfg: dict, images: list[str], prompt: str,
                       width: int, height: int, duration: int,
                       seed: int | None = None,
                       filename_prefix: str = "video/AnimGenerator",
                       video_model: str | None = None,
                       ref_video: str | None = None,
                       ref_videos: list[str] | None = None,
                       turbo_steps: int | None = None,
                       ref_image_size: str = "match",
                       nsfw: bool = False,
                       climax: bool = False,
                       action: str = "",
                       tags: str = "",
                       extra: str = "",
                       effect_loras: list | None = None) -> dict:
    """MiniMax H3 Reference-to-Video。images：女、（男）、場景；ref_videos 為 <Video 1>…。"""
    if len(images) < 2:
        raise ValueError("R2V 至少要兩張參考圖")
    model = resolve_video_model(cfg, video_model)
    name = model.get("r2v_workflow") or "video_minimax_h3_r2v.json"
    raw = json.dumps(_load(cfg, name), ensure_ascii=False)
    seed = seed if seed is not None else _rand_seed()
    esc = json.dumps(prompt, ensure_ascii=False)[1:-1]
    raw = raw.replace("%IMAGE0%", images[0])
    raw = raw.replace("%IMAGE1%", images[1])
    raw = raw.replace("%PROMPT%", esc)
    raw = raw.replace('"%DURATION%"', str(int(duration)))
    raw = raw.replace('"%WIDTH%"', str(int(width)))
    raw = raw.replace('"%HEIGHT%"', str(int(height)))
    raw = raw.replace('"%SEED%"', str(int(seed)))
    wf = json.loads(raw)
    r2v_id = next(
        nid for nid, n in wf.items()
        if n.get("class_type") == "MiniMaxH3ReferenceToVideo")
    size = (ref_image_size or "match").strip().lower()
    if size not in {"match", "max"}:
        size = "match"
    wf[r2v_id]["inputs"]["ref_image_size"] = size
    for i, name in enumerate(images[2:], start=2):
        nid = str(160 + i - 2)
        wf[nid] = {
            "inputs": {"image": name},
            "class_type": "LoadImage",
            "_meta": {"title": "載入圖片"},
        }
        wf[r2v_id]["inputs"][f"ref_images.ref_image_{i}"] = [nid, 0]

    clips = [x for x in (ref_videos or []) if x]
    if not clips and ref_video:
        clips = [ref_video]
    for i, fname in enumerate(clips[:3]):
        load_id = str(150 + i * 2)
        get_id = str(151 + i * 2)
        wf[load_id] = {
            "inputs": {"file": fname},
            "class_type": "LoadVideo",
            "_meta": {"title": "載入影片"},
        }
        wf[get_id] = {
            "inputs": {"video": [load_id, 0]},
            "class_type": "GetVideoComponents",
            "_meta": {"title": "Get Video Components"},
        }
        wf[r2v_id]["inputs"][f"ref_videos.ref_video_{i}"] = [get_id, 0]

    for nid in _find(wf, "CreateVideo"):
        if "fps" in wf[nid]["inputs"]:
            wf[nid]["inputs"]["fps"] = model["fps"]
    for nid in _find(wf, "RandomNoise"):
        wf[nid]["inputs"]["noise_seed"] = seed
    if model.get("unet"):
        for nid in _find(wf, "UNETLoader"):
            wf[nid]["inputs"]["unet_name"] = model["unet"]
    if model.get("clip"):
        for nid in _find(wf, "CLIPLoader"):
            wf[nid]["inputs"]["clip_name"] = model["clip"]
    if model.get("video_vae") or model.get("audio_vae"):
        for nid in _find(wf, "VAELoader"):
            vae = (wf[nid]["inputs"].get("vae_name") or "").lower()
            if "audio" in vae and model.get("audio_vae"):
                wf[nid]["inputs"]["vae_name"] = model["audio_vae"]
            elif model.get("video_vae"):
                wf[nid]["inputs"]["vae_name"] = model["video_vae"]
    for nid in _find(wf, "ResolutionSelector"):
        if model.get("aspect_ratio"):
            wf[nid]["inputs"]["aspect_ratio"] = model["aspect_ratio"]
        if model.get("megapixels") is not None:
            wf[nid]["inputs"]["megapixels"] = float(model["megapixels"])
    for nid in _find(wf, "SaveVideo"):
        wf[nid]["inputs"]["filename_prefix"] = filename_prefix
    fx = effect_loras if effect_loras is not None else pick_h3_effect_loras(
        model, nsfw=nsfw, climax=climax, action=action, tags=tags,
        motion=prompt, extra=extra)
    _apply_h3_turbo(wf, model, "r2v", turbo_steps, nsfw_effects=_nsfw_effects(fx))
    _apply_h3_effect_loras(wf, fx)
    return wf


def _nsfw_effects(loras: list | None) -> bool:
    return any(
        (x.get("when") or "") not in {"", "always"}
        for x in (loras or [])
    )


def _apply_h3_turbo(wf: dict, model: dict, kind: str, turbo_steps: int | None,
                    nsfw_effects: bool = False) -> None:
    spec = h3_turbo_spec(model, kind, turbo_steps)
    if not spec:
        return
    if spec.get("off"):
        unet = _find_one(wf, "UNETLoader")
        for sid in _find(wf, "MiniMaxH3SigmaShift"):
            _rewire(wf, sid, [unet, 0])
        _drop(wf, *_find(wf, "LoraLoaderModelOnly"), *_find(wf, "MiniMaxH3SigmaShift"))
        for nid in _find(wf, "BasicScheduler"):
            wf[nid]["inputs"]["steps"] = spec["steps"]
        for nid in _find(wf, "KSamplerSelect"):
            wf[nid]["inputs"]["sampler_name"] = spec.get("sampler") or "res_multistep"
        return
    strength = spec["strength_nsfw"] if nsfw_effects else spec["strength"]
    for nid in _find(wf, "LoraLoaderModelOnly"):
        wf[nid]["inputs"]["lora_name"] = spec["lora"]
        wf[nid]["inputs"]["strength_model"] = strength
    for nid in _find(wf, "MiniMaxH3SigmaShift"):
        wf[nid]["inputs"]["shift_video"] = spec["shift_video"]
        wf[nid]["inputs"]["shift_audio"] = spec["shift_audio"]
    for nid in _find(wf, "BasicScheduler"):
        wf[nid]["inputs"]["steps"] = spec["steps"]
    if spec.get("sampler"):
        for nid in _find(wf, "KSamplerSelect"):
            wf[nid]["inputs"]["sampler_name"] = spec["sampler"]


def _apply_h3_effect_loras(wf: dict, loras: list[dict]) -> None:
    """Turbo LoRA 之後、SigmaShift 之前串效果 LoRA。關閉 Turbo 時改接 UNET。"""
    if not loras:
        return
    shifts = _find(wf, "MiniMaxH3SigmaShift")
    if shifts:
        src = wf[shifts[0]]["inputs"].get("model")
        if not isinstance(src, list) or len(src) != 2:
            return
        prev = list(src)
        sink = shifts[0]
    else:
        prev = [_find_one(wf, "UNETLoader"), 0]
        sink = None
    for i, spec in enumerate(loras, 1):
        nid = f"h3fx{i}"
        wf[nid] = {
            "inputs": {
                "lora_name": spec["lora"],
                "strength_model": float(spec.get("strength") or 1),
                "model": prev,
            },
            "class_type": "LoraLoaderModelOnly",
            "_meta": {"title": f"H3 LoRA ({spec.get('id') or spec['lora']})"},
        }
        prev = [nid, 0]
    if sink:
        wf[sink]["inputs"]["model"] = prev
        return
    for nid in _find(wf, "BasicGuider") + _find(wf, "BasicScheduler"):
        if "model" in wf[nid].get("inputs", {}):
            wf[nid]["inputs"]["model"] = prev


def _apply_prompt_enhance(wf: dict, vid: dict) -> None:
    gen_ids = _find(wf, "TextGenerateLTX2Prompt")
    if not gen_ids:
        return
    prompt_ids = _find(wf, "PrimitiveStringMultiline", "Prompt")
    switch_ids = _find(wf, "ComfySwitchNode")
    bool_ids = _find(wf, "PrimitiveBoolean", "Boolean (Enable Prompt Enhance)")
    if vid.get("prompt_enhance"):
        for nid in bool_ids:
            wf[nid]["inputs"]["value"] = True
        for nid in _find(wf, "LoraLoader"):
            if vid.get("prompt_enhance_lora"):
                wf[nid]["inputs"]["lora_name"] = vid["prompt_enhance_lora"]
        return
    if prompt_ids:
        for nid in switch_ids:
            _rewire(wf, nid, [prompt_ids[0], 0])
    _drop(wf, *gen_ids, *switch_ids, *bool_ids,
          *_find(wf, "LoraLoader"), *_find(wf, "PreviewAny"))
