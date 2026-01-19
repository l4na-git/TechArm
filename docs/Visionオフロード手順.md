# Visionオフロード手順

## 目的
カメラ接続側（Pi/PC）の負荷を下げるため、Vision処理（マーカー検出/手検知/座標変換）を別サーバで実行します。

## 事前準備
- オフロード先サーバ（音声生成と同じマシン）で TeachArm を起動できる状態にする
- Tailscale などで Pi/PC からオフロード先に到達できる状態にする

## 設定
### 1) オフロード先サーバ（解析側）
1. `.env` を `.env.example` から作成
2. `CONTROL_PANEL_URL` は任意でOK
3. `config/camera.yaml` の `resolution` と `parameters.fps` を **送信側と一致**させる

例:
```yaml
resolution:
  width: 960
  height: 540

parameters:
  fps: 15
```

### 2) Pi/PC（送信側）
1. `.env` に以下を追加（`.env.example` に準拠）
```env
VISION_OFFLOAD_URL=http://100.xxx.xxx.xxx:8000
```
2. `config/camera.yaml` は撮影側の設定として維持する

## 起動手順
1. オフロード先サーバで TeachArm API を起動  
   例: `uvicorn teacharm.server:create_app --host 0.0.0.0 --port 8000`
2. Pi/PC 側で TeachArm API を起動  
3. コントロールパネルから「Start Camera」を押す

## 動作確認
- プレビュー映像が表示される
- `markers_detected` と `hand_detected` が更新される
- `current_region_id` が指し示しに応じて変化する

## 参考
- オフロード先URLは `.env.example` の形式に合わせてください
- 画質/負荷は `config/camera.yaml` と `VISION_OFFLOAD_URL` の設定で調整します
