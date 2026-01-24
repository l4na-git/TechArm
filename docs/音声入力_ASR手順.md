# 音声入力（ASR）手順

## 概要
日本語精度を優先しつつ軽量に動かすため、faster-whisper（base, int8, CPU）を推奨構成として採用します。

## 推奨構成（軽量・日本語優先）
- モデル: `base`
- デバイス: `cpu`
- 精度/速度: `compute_type=int8`, `beam_size=1`

`.env` 例:
```env
ASR_MODEL=base
ASR_LANGUAGE=ja
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_BEAM_SIZE=1
```

## 依存
- `faster-whisper` は `requirements/asr.txt` で管理
- 音声デコードに `ffmpeg` が必要です

## 起動前準備
1) `pip install -r requirements/asr.txt`  
2) `ffmpeg` をインストール（OS標準手順）  
3) 初回実行時にモデルが未取得の場合は自動取得されます  
   - オフライン運用なら事前にモデルを配置し、`ASR_MODEL` にパスを指定してください

## 動作確認
### 文字起こしのみ
```bash
curl -X POST http://localhost:8000/api/asr/transcribe \
  -F "audio=@sample.wav"
```

### 音声入力→対話→音声生成
```bash
curl -X POST http://localhost:8000/api/dialogue/audio \
  -F "audio=@sample.wav"
```

### マイク録音→送信（簡易ツール）
```bash
python tools/mic_record_send.py --duration 4
```

### 押している間だけ録音（キーボード）
```bash
python tools/mic_record_send_keyboard.py --key space
```

### 押している間だけ録音→送信→TTS再生
```bash
python tools/mic_record_send_keyboard.py --key space --play-response
```

### 押している間だけ録音（GPIOボタン）
```bash
python tools/mic_record_send_gpio.py --pin 17 --pull-up
```

### 押すたびに録音開始/停止（Macメディアキー）
```bash
python tools/mic_record_send_media_key_mac.py --media-key play --mode toggle
```

## 速度調整の目安
重い場合は以下を下げてください:
- `ASR_MODEL=tiny`（最軽量）
- `ASR_BEAM_SIZE=1`（固定）

## 備考
- `ASR_MODEL` はモデル名またはローカルパスのどちらでも指定できます
