# MicroDramaGenerator — Claude Code 指南

短劇固定 Diffusers 參考圖 + ComfyUI MiniMax H3 R2V。角色讀 `data/characters.json`（Danbooru Top 500，分女／男）。

## 快速調用

```bash
python -m anim_creator invent --character "hatsune_miku" --male "link" --premise "雨夜旅館"
python -m anim_creator stills --story alley_follow --character "hatsune_miku"
python server.py   # 0.0.0.0:8620
```

- 尺寸見 `config.yaml` 的 `image.width/height` 與 `video.width/height`
- 女角色必選；男角色可空（雙人段用 `data/default_male.png`）
- Ollama 寫短劇走 `/api/story/invent`，存 `data/stories/`
- 產圖走 `/api/story/stills`（`story_mode=r2v`）；產動畫走 `/api/stories/{pack}/animate`

## 前置

- ComfyUI 在 `comfyui.url`（預設 8188），H3 R2V 工作流 `workflows/video_minimax_h3_r2v.json`
- 首幀：`image.backend` = `diffusers`
- 角色：`characters.file` = `data/characters.json`

## 修改要點

- 內建短劇 → `anim_creator/stories.py`
- Ollama 短劇格式 → `anim_creator/ollama_gen.py` 的 `ai_story`
- R2V：solo 為 `<Picture 1>` 女＋`<Picture 2>` 場景；雙人再加男角色圖
- 衣著或地點變了才重出參考圖
- Diffusers 出完必須 `free_pipe()`，否則 H3 會被擠到共享記憶體
