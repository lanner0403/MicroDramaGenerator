# MicroDramaGenerator

本機短劇。選 Danbooru 女／男角色，用 Diffusers 出參考圖，再用 ComfyUI 的 MiniMax H3 合成影片。劇本可以選內建短劇，或讓本機 Ollama 現寫。網頁在 **8620**，可與 AnimGenerator（8610）同時開。

```
瀏覽器 :8620
    │
    ▼
server.py
    ├─ Diffusers          character.png / partner.png / scene.png
    ├─ ComfyUI :8188      animation.mp4（MiniMax H3 R2V 或 I2V）
    └─ Ollama :11434      可選，寫短劇
```

本專案可生成成人內容。請自行遵守所在地法律與模型條款。

## 一鍵安裝（Windows）

需要 Windows 10/11、Python 3.10 以上（安裝程式沒看到時會用 winget 裝 3.12）、NVIDIA GPU。ComfyUI 與 Diffusers 模型要自己準備，安裝程式不下載它們。

```text
git clone https://github.com/lanner0403/MicroDramaGenerator.git
cd MicroDramaGenerator
install.bat
```

`install.bat` 會：

1. 確認 Python 3.10+
2. 建立 `.venv`
3. 先裝 CUDA 版 PyTorch（cu128）。失敗就改裝 PyPI 預設版
4. 安裝 `requirements.txt` 與 `requirements-diffusers.txt`
5. 建立 `output`、`data\stories`、`data\drafts`、`data\video`
6. 執行 `scripts\build_preset_stories.py`，重寫 `data\preset_stories.json`

裝完後改 [`config.yaml`](config.yaml) 裡的模型路徑，確認 ComfyUI 已在 8188，再雙擊 `start.bat`。瀏覽器開 <http://127.0.0.1:8620>。

`start.bat` 依序找 `.venv`、上一層 `AnimGenerator\.venv`、系統的 `py -3`。ComfyUI 沒開只會警告。Ollama 沒在聽 11434、而且本機有安裝時，會試著拉起來。

手動安裝：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-diffusers.txt
.\.venv\Scripts\python.exe scripts\build_preset_stories.py
```

確認 GPU：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

## 要先準備的服務

| 服務 | 位址 | 必備 |
|------|------|------|
| ComfyUI | <http://127.0.0.1:8188> | 產影片要開 |
| 本程式 | <http://127.0.0.1:8620> | `start.bat` |
| Ollama | <http://127.0.0.1:11434> | 只有 AI 寫劇本才需要 |

Diffusers 出完參考圖會卸載模型，再把顯存讓給 H3。兩個不要同時占著 GPU。

### Diffusers 首幀

`config.yaml` 的 `image.diffusers.models` 指向本機 SDXL 權重。預設是 `oneobsession`。路徑對不上就改成你機器上的檔案，例如：

```yaml
image:
  backend: "diffusers"
  diffusers:
    default: oneobsession
    models:
      oneobsession:
        path: "C:/SD/sd.webui/sd.webui/webui/models/Stable-diffusion/oneObsession_v24.safetensors"
```

### ComfyUI MiniMax H3

工作流在 `workflows/video_minimax_h3_r2v.json` 與 `workflows/video_minimax_h3_i2v.json`。權重檔名要與 `config.yaml` 的 `video.models.minimax_h3` 一致，放在 ComfyUI 的模型目錄：

| 用途 | 檔名 |
|------|------|
| UNet | `10Eros_Max_h3_TURBO-hybrid_beta5_int8.safetensors` |
| CLIP | `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| R2V Turbo 8 step | `minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors` |
| I2V Turbo 8 step | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` |

`effect_loras` 裡的 LoRA 也要放在 ComfyUI。沒有對應檔時，那個效果不會掛上。

## 版控裡有什麼

`data` 只提交這些：

| 路徑 | 說明 |
|------|------|
| `data/sounds/female/f1_sweet.mp3` | 甜美軟糯 |
| `data/sounds/female/f2_young.mp3` | 年輕元氣 |
| `data/sounds/female/f3_cold.mp3` | 高冷淡然 |
| `data/sounds/female/f4_mature.mp3` | 成熟低沉 |
| `data/sounds/female/f5_husky.mp3` | 沙啞性感 |
| `data/sounds/male/m1_young.mp3` | 年輕清爽 |
| `data/sounds/male/m2_warm.mp3` | 溫和低音 |
| `data/sounds/male/m3_deep.mp3` | 低沉磁性 |
| `data/sounds/male/m4_cold.mp3` | 冷淡平穩 |
| `data/sounds/male/m5_husky.mp3` | 沙啞粗獷 |
| `data/sounds/voices.json` | 上面 10 段的名稱與台詞 |
| `data/characters.json` | 角色清單。沒有這個檔，`server.py` 啟動會失敗 |

不進 Git，留在本機：

- `data\drafts\`、`data\stories\`、`data\video\`、`data\*.mp4`
- `data\sounds` 裡基本 5 段以外的角色參考音
- `data\catalog_cache.json`、`data\default_male.png`
- `data\preset_stories.json`（`install.bat` 依 `scripts\build_preset_stories.py` 重寫）
- `output\`、`.venv\`、`__pycache__\`、`*.bak*`

男角色留空、而且沒有 `data\default_male.png` 時，雙人段會改為現場生男角參考圖。

要重做那 10 段參考音：

```powershell
.\.venv\Scripts\python.exe -m pip install edge-tts
.\.venv\Scripts\python.exe scripts\gen_voice_refs.py
```

## 可選元件

聲線克隆（I2V 的 `i2v_clone`）預設走 VoxCPM，不在一鍵安裝裡：

```powershell
.\.venv\Scripts\python.exe -m pip install voxcpm soundfile
```

模型名在 `config.yaml` 的 `voice.voxcpm_model`（`openbmb/VoxCPM2`）。不要克隆時把 `voice.clone` 改成 `none`。

Ollama 只用在「AI 寫短劇」與看圖寫動作稿。沒裝時，內建短劇一樣能產。

## 網頁怎麼用

1. 雙擊 `start.bat`
2. 開啟 <http://127.0.0.1:8620>
3. 選女角色，男角色可空
4. 選內建短劇，或讓 Ollama 依前提寫一篇
5. 產參考圖，再依段落選 R2V、尾幀 I2V，或 I2V 加聲線克隆

女角必選。衣著或地點沒變就沿用上一張參考圖。

## 命令列

```powershell
.\.venv\Scripts\python.exe -m anim_creator options
.\.venv\Scripts\python.exe -m anim_creator invent --character "hatsune_miku" --male "link" --premise "雨夜旅館"
.\.venv\Scripts\python.exe -m anim_creator stills --story flash_ceo --character "hatsune_miku" --male "link"
.\.venv\Scripts\python.exe -m anim_creator animate --pack <output 資料夾名> --clip-mode r2v
```

`--clip-mode` 可以是 `r2v`、`i2v`、`i2v_clone`。女衣著 `--theme`，男衣著 `--male-theme`。

## 輸出

```text
output/story_<時間>_<角色>_<劇本>/
  story.json
  <段落>/
    character.png
    partner.png
    scene.png
    animation.mp4
    meta.json
```

Ollama 寫出的劇本在 `data/stories/<id>.json`（本機，不進 Git）。

## 設定對照

| 要改的東西 | 位置 |
|------------|------|
| ComfyUI 位址、Diffusers 路徑、H3、Ollama、聲線 | [`config.yaml`](config.yaml) |
| 角色清單 | `data/characters.json` |
| 內建短劇內容 | `scripts/build_preset_stories.py`，改完再跑 `install.bat` 或該腳本 |
| H3 工作流 | `workflows/video_minimax_h3_r2v.json`、`workflows/video_minimax_h3_i2v.json` |
