"""產出 data/sounds 女／男各 5 段聲線參考音。

優先 edge-tts（免 GPU，語色差得開）；若本機有 VoxCPM 可改用 --engine voxcpm。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOUNDS = ROOT / "data" / "sounds"

FEMALE = [
    {
        "id": "f1_sweet",
        "label": "甜美軟糯",
        "file": "female/f1_sweet.mp3",
        "style": "sweet",
        "edge": "zh-CN-XiaoxiaoNeural",
        "text": "你好，我是這個角色的聲音。從今天起，我會陪你把故事說完。",
        "vox": "A young woman, gentle and sweet, slightly high adult female voice",
    },
    {
        "id": "f2_young",
        "label": "年輕元氣",
        "file": "female/f2_young.mp3",
        "style": "young",
        "edge": "zh-CN-XiaoyiNeural",
        "text": "嘿，別發呆啊。這次換我來帶節奏，跟緊一點。",
        "vox": "Youthful adult female, bright energetic slightly high voice",
    },
    {
        "id": "f3_cold",
        "label": "高冷淡然",
        "file": "female/f3_cold.mp3",
        "style": "cold",
        "edge": "zh-TW-HsiaoChenNeural",
        "text": "少廢話。該走的路，我自己知道。",
        "vox": "Cool low adult female voice, calm and restrained",
    },
    {
        "id": "f4_mature",
        "label": "成熟低沉",
        "file": "female/f4_mature.mp3",
        "style": "mature",
        "edge": "zh-TW-HsiaoYuNeural",
        "text": "別急。有些話，今晚我會慢慢告訴你。",
        "vox": "Mature low adult female voice, sultry and calm",
    },
    {
        "id": "f5_husky",
        "label": "沙啞性感",
        "file": "female/f5_husky.mp3",
        "style": "husky",
        "edge": "zh-CN-liaoning-XiaobeiNeural",
        "text": "過來一點。這段聲音，只講給你聽。",
        "vox": "Husky low adult female, raspy and sensual",
    },
]
MALE = [
    {
        "id": "m1_young",
        "label": "年輕清爽",
        "file": "male/m1_young.mp3",
        "style": "male_young",
        "edge": "zh-CN-YunxiNeural",
        "text": "別怕。從現在起，我走在你前面。",
        "vox": "Youthful adult male, clear slightly high voice",
    },
    {
        "id": "m2_warm",
        "label": "溫和低音",
        "file": "male/m2_warm.mp3",
        "style": "male_warm",
        "edge": "zh-TW-YunJheNeural",
        "text": "慢慢來。我在這裡，不會讓你一個人。",
        "vox": "Warm low adult male voice, gentle",
    },
    {
        "id": "m3_deep",
        "label": "低沉磁性",
        "file": "male/m3_deep.mp3",
        "style": "male_deep",
        "edge": "zh-CN-YunjianNeural",
        "text": "聽好。這門婚事，我娶。",
        "vox": "Deep resonant adult male voice",
    },
    {
        "id": "m4_cold",
        "label": "冷淡平穩",
        "file": "male/m4_cold.mp3",
        "style": "male_cold",
        "edge": "zh-CN-YunyangNeural",
        "text": "再問一次。她是我太太。",
        "vox": "Cool flat adult male voice, restrained",
    },
    {
        "id": "m5_husky",
        "label": "沙啞粗獷",
        "file": "male/m5_husky.mp3",
        "style": "male_husky",
        "edge": "zh-CN-YunxiaNeural",
        "text": "上車。回家再說。",
        "vox": "Husky raspy adult male voice",
    },
]


def _write_catalog() -> None:
    blob = {
        "engine": "edge-tts",
        "female": [{k: x[k] for k in ("id", "label", "file", "style", "text")} for x in FEMALE],
        "male": [{k: x[k] for k in ("id", "label", "file", "style", "text")} for x in MALE],
    }
    (SOUNDS / "voices.json").write_text(
        json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")


async def _edge_one(item: dict) -> None:
    import edge_tts
    dest = SOUNDS / item["file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    comm = edge_tts.Communicate(item["text"], item["edge"])
    await comm.save(str(dest))
    print("ok", dest.relative_to(ROOT), dest.stat().st_size)


async def run_edge() -> None:
    for item in FEMALE + MALE:
        await _edge_one(item)


def run_voxcpm() -> None:
    from voxcpm import VoxCPM
    import soundfile as sf
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    sr = model.tts_model.sample_rate
    for item in FEMALE + MALE:
        dest = SOUNDS / item["file"]
        dest = dest.with_suffix(".wav")
        dest.parent.mkdir(parents=True, exist_ok=True)
        wav = model.generate(
            text=f"({item['vox']}){item['text']}",
            cfg_value=2.0,
            inference_timesteps=10,
        )
        sf.write(str(dest), wav, sr)
        item["file"] = str(Path(item["file"]).with_suffix(".wav")).replace("\\", "/")
        print("ok", dest.relative_to(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["edge", "voxcpm"], default="edge")
    args = p.parse_args()
    SOUNDS.mkdir(parents=True, exist_ok=True)
    (SOUNDS / "female").mkdir(exist_ok=True)
    (SOUNDS / "male").mkdir(exist_ok=True)
    if args.engine == "voxcpm":
        run_voxcpm()
        _write_catalog()
        path = SOUNDS / "voices.json"
        blob = json.loads(path.read_text(encoding="utf-8"))
        blob["engine"] = "voxcpm"
        path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("pip install edge-tts", file=sys.stderr)
        return 1
    asyncio.run(run_edge())
    _write_catalog()
    print("wrote", SOUNDS / "voices.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
