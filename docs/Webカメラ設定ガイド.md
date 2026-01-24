# Webカメラ設定ガイド

TeachArm のカメラ入力を内蔵カメラではなく Webカメラに切り替える手順です。

## 1. 接続確認

macOS で接続されているカメラ名を確認:

```bash
system_profiler SPCameraDataType
```

## 2. OpenCV で index を確認

OpenCV から開けるカメラの index を列挙します。

```bash
python scripts/check_camera_indices.py
```

どれがどのカメラか確認したい場合はプレビューを表示します。

```bash
python scripts/check_camera_indices.py --preview
```

`q` で途中終了できます。

上限を変えたい場合（例: 10 まで検索）:

```bash
python scripts/check_camera_indices.py 10
```

出力例:

```
index 0: OK 1280x720
index 1: OK 1920x1080
index 2: NG 0x0
```

## 3. config/camera.yaml を更新

`config/camera.yaml` の `device.index` を Webカメラの index に変更します。

```yaml
device:
  index: 1
```

## 4. 動作確認

```bash
python demo_vision.py
```

映像が出ない場合は別の index を試してください。
