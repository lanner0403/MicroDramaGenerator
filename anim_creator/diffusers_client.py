"""本機 Diffusers：WAI-NSFW-illustrious SDXL 出首幀。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
import textwrap

_PIPE: Any = None
_PIPE_KEY: tuple | None = None
_SDXL_VAE_CONFIG = "madebyollin/sdxl-vae-fp16-fix"


class DiffusersError(RuntimeError):
    pass


def _setup_ssl() -> None:
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass


def _detect_device(requested: str) -> str:
    if requested != "auto":
        return requested
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _is_single_file(path: str) -> bool:
    return bool(path) and path.lower().endswith((".safetensors", ".ckpt"))


def _flush_cuda() -> None:
    import gc
    import torch
    gc.collect()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def free_pipe() -> bool:
    """Unload the cached SDXL pipe so ComfyUI H3 can take VRAM.

    Do not pipe.to("cpu"): SDXL fp16 would copy ~6GB into RAM before GPU
    memory is released. Drop module refs and let the CUDA allocator reclaim.
    """
    global _PIPE, _PIPE_KEY
    if _PIPE is None:
        return False
    pipe = _PIPE
    _PIPE = _PIPE_KEY = None
    try:
        if hasattr(pipe, "maybe_free_model_hooks"):
            try:
                pipe.maybe_free_model_hooks()
            except Exception:
                pass
        if hasattr(pipe, "unfuse_lora"):
            try:
                pipe.unfuse_lora()
            except Exception:
                pass
        if hasattr(pipe, "unload_lora_weights"):
            try:
                pipe.unload_lora_weights()
            except Exception:
                pass
        names = []
        if hasattr(pipe, "components"):
            try:
                names = list(pipe.components.keys())
            except Exception:
                names = []
        for name in names:
            try:
                setattr(pipe, name, None)
            except Exception:
                pass
        del names
        del pipe
        _flush_cuda()
    except Exception:
        try:
            del pipe
        except Exception:
            pass
        try:
            _flush_cuda()
        except Exception:
            pass
    return True


def _normalize_sampler(name: str | None) -> str:
    return (name or "Euler a").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _install_scheduler(pipe, sampler: str | None) -> None:
    """Use Euler a (config default). Force begin_index=0 after set_timesteps.

    from_single_file checkpoints often ship EulerDiscrete + steps_offset that
    make index_for_timestep start at 1. Last step then reads sigmas[N] of size N.
    """
    from diffusers import EulerAncestralDiscreteScheduler, EulerDiscreteScheduler

    want = _normalize_sampler(sampler)
    current = getattr(pipe, "_anim_sampler", None)
    if current == want and getattr(pipe.scheduler, "_anim_begin_patched", False):
        return

    cfg = dict(pipe.scheduler.config)
    cfg["steps_offset"] = 1
    cfg["timestep_spacing"] = "linspace"
    if want in {"euler", "eulerdiscrete"}:
        sched = EulerDiscreteScheduler.from_config(cfg)
    else:
        sched = EulerAncestralDiscreteScheduler.from_config(cfg)

    orig_set = sched.set_timesteps

    def set_timesteps(*args, **kwargs):
        out = orig_set(*args, **kwargs)
        if hasattr(sched, "set_begin_index"):
            sched.set_begin_index(0)
        sched._step_index = None
        return out

    sched.set_timesteps = set_timesteps
    sched._anim_begin_patched = True
    pipe.scheduler = sched
    pipe._anim_sampler = want


def _reset_scheduler(pipe) -> None:
    sched = pipe.scheduler
    if hasattr(sched, "_step_index"):
        sched._step_index = None
    if hasattr(sched, "set_begin_index"):
        sched.set_begin_index(0)


def _lora_spec(dcfg: dict) -> tuple[str, float]:
    raw = (dcfg.get("lora") or "").strip()
    if not raw:
        return "", 1.0
    try:
        scale = float(dcfg.get("lora_scale") if dcfg.get("lora_scale") is not None else 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    return raw, scale


def _apply_lora(pipe, lora_path: str, scale: float) -> None:
    path = Path(lora_path)
    if not path.is_file():
        raise DiffusersError(f"找不到產圖 LoRA: {path}")
    try:
        import peft  # noqa: F401
    except ImportError as e:
        raise DiffusersError(
            "載入產圖 LoRA 需要 peft。請 pip install peft"
        ) from e
    try:
        pipe.load_lora_weights(str(path), adapter_name="image_lora")
    except TypeError:
        try:
            pipe.load_lora_weights(str(path))
        except Exception:
            pipe.load_lora_weights(str(path.parent), weight_name=path.name)
    except Exception:
        pipe.load_lora_weights(str(path.parent), weight_name=path.name)
    scale = float(scale)
    if hasattr(pipe, "set_adapters"):
        try:
            pipe.set_adapters(["image_lora"], adapter_weights=[scale])
            return
        except Exception:
            pass
    if hasattr(pipe, "fuse_lora"):
        pipe.fuse_lora(lora_scale=scale)


def _prepare_vae(pipe, dtype, vae_id: str) -> None:
    """Avoid deprecated pipe.upcast_vae(). fp16-fix stays fp16; others stay fp32."""
    import torch
    vae = getattr(pipe, "vae", None)
    if vae is None or dtype != torch.float16:
        return
    if hasattr(vae.config, "force_upcast"):
        vae.config.force_upcast = False
    if vae_id == _SDXL_VAE_CONFIG:
        return
    vae.to(dtype=torch.float32)


def _get_pipe(dcfg: dict):
    global _PIPE, _PIPE_KEY
    import torch
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline

    device = _detect_device(dcfg.get("device", "auto"))
    dtype = torch.float32 if device in ("cpu", "mps") else torch.float16
    model = dcfg["model"]
    vae_id = dcfg.get("vae") or ""
    if not vae_id and dtype == torch.float16:
        vae_id = _SDXL_VAE_CONFIG
    sampler = dcfg.get("sampler") or "Euler a"
    lora_path, lora_scale = _lora_spec(dcfg)
    key = (model, device, vae_id, bool(dcfg.get("cpu_offload")), lora_path, lora_scale)
    if _PIPE is not None and _PIPE_KEY == key:
        _install_scheduler(_PIPE, sampler)
        return _PIPE, device
    if _PIPE is not None:
        free_pipe()

    if not model:
        raise DiffusersError("config.yaml 未設定 image.diffusers.model")

    _setup_ssl()
    kwargs: dict = {"torch_dtype": dtype}
    if vae_id:
        if _is_single_file(vae_id):
            kwargs["vae"] = AutoencoderKL.from_single_file(
                vae_id, config=_SDXL_VAE_CONFIG, torch_dtype=dtype)
        else:
            kwargs["vae"] = AutoencoderKL.from_pretrained(vae_id, torch_dtype=dtype)

    if _is_single_file(model):
        pipe = StableDiffusionXLPipeline.from_single_file(model, **kwargs)
    else:
        pipe = StableDiffusionXLPipeline.from_pretrained(model, **kwargs)

    _install_scheduler(pipe, sampler)
    if lora_path:
        _apply_lora(pipe, lora_path, lora_scale)

    if dcfg.get("cpu_offload") and device == "cuda":
        pipe.enable_model_cpu_offload()
    else:
        pipe = pipe.to(device)
    _prepare_vae(pipe, dtype, vae_id)
    pipe.enable_attention_slicing()
    if device == "cuda":
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass
    _PIPE, _PIPE_KEY = pipe, key
    return pipe, device


class DiffusersClient:
    def __init__(self, dcfg: dict):
        self.dcfg = dcfg

    def txt2img(self, prompt: str, negative: str, out_path: Path,
                width: int, height: int, steps: int, cfg: float,
                seed: int | None = None, on_progress=None) -> Path:
        import torch
        pipe, device = _get_pipe(self.dcfg)
        _reset_scheduler(pipe)
        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator(device=device).manual_seed(int(seed))

        def cb_old(step, timestep, latents):
            if on_progress:
                on_progress(int((step + 1) / max(steps, 1) * 100), step + 1, steps)

        def cb_new(pipe_, step, timestep, callback_kwargs):
            if on_progress:
                on_progress(int((step + 1) / max(steps, 1) * 100), step + 1, steps)
            return callback_kwargs

        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative or None,
            width=width,
            height=height,
            num_inference_steps=max(1, int(steps)),
            guidance_scale=cfg,
            generator=generator,
        )
        with torch.no_grad():
            try:
                result = pipe(
                    **kwargs,
                    callback_on_step_end=cb_new,
                    callback_on_step_end_tensor_inputs=["latents"],
                )
            except IndexError:
                _reset_scheduler(pipe)
                result = pipe(**kwargs)
            except TypeError:
                try:
                    result = pipe(**kwargs, callback=cb_old, callback_steps=1)
                except TypeError:
                    result = pipe(**kwargs)
        img = result.images[0]
        del result
        if img.mode != "RGB":
            img = img.convert("RGB")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path

    def img2img(self, prompt: str, negative: str, init_image: Path,
                out_path: Path, width: int, height: int, steps: int, cfg: float,
                strength: float = 0.58, seed: int | None = None,
                on_progress=None) -> Path:
        import torch
        from diffusers import StableDiffusionXLImg2ImgPipeline
        from PIL import Image as PILImage

        pipe, device = _get_pipe(self.dcfg)
        _reset_scheduler(pipe)
        # from_pipe shares weights with the cached txt2img pipe. Do not
        # null i2i.unet etc. — those modules belong to _PIPE.
        try:
            i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe)
        except Exception:
            i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components)
        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator(device=device).manual_seed(int(seed))
        src = PILImage.open(init_image).convert("RGB")
        if src.size != (width, height):
            src = src.resize((width, height), PILImage.LANCZOS)
        strength = max(0.15, min(0.95, float(strength)))

        def cb_new(pipe_, step, timestep, callback_kwargs):
            if on_progress:
                on_progress(int((step + 1) / max(steps, 1) * 100), step + 1, steps)
            return callback_kwargs

        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative or None,
            image=src,
            strength=strength,
            num_inference_steps=max(1, int(steps)),
            guidance_scale=cfg,
            generator=generator,
        )
        try:
            with torch.no_grad():
                try:
                    result = i2i(
                        **kwargs,
                        callback_on_step_end=cb_new,
                        callback_on_step_end_tensor_inputs=["latents"],
                    )
                except IndexError:
                    _reset_scheduler(pipe)
                    result = i2i(**kwargs)
                except TypeError:
                    result = i2i(**kwargs)
            img = result.images[0]
            del result
        finally:
            del i2i
        if img.mode != "RGB":
            img = img.convert("RGB")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path


def mock_image(prompt: str, out_path: Path, width: int, height: int) -> Path:
    seed = sum(ord(c) for c in prompt)
    bg = ((seed * 37) % 90 + 30, (seed * 17) % 90 + 30, (seed * 53) % 90 + 40)
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, width - 20, height - 20], outline=(255, 255, 255), width=3)
    d.text((40, 40), "[MOCK 首幀]", fill=(255, 210, 90))
    y = 90
    for line in textwrap.wrap(prompt[:400], width=48):
        d.text((40, y), line, fill=(230, 230, 230))
        y += 22
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
