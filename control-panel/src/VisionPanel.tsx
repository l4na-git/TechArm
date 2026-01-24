import { useEffect, useRef, useState } from "react";

type VisionFrame = {
  timestamp: number;
  markers_detected: number[];
  markers_corners: Record<string, number[][]>;
  is_calibrated: boolean;
  hand_detected: boolean;
  fingertip_u: number | null;
  fingertip_v: number | null;
  current_region_id: string | null;
  current_material_id: string | null;
  dwell_frames?: number;
  image?: string | null; // Base64-encoded JPEG
};

type VisionPanelProps = {
  apiUrl: string;
};

export function VisionPanel({ apiUrl }: VisionPanelProps) {
  const [isActive, setIsActive] = useState(false);
  const [isCalibrated, setIsCalibrated] = useState(false);
  const [visionFrame, setVisionFrame] = useState<VisionFrame | null>(null);
  const [lastImage, setLastImage] = useState<string | null>(null);
  const [fps, setFps] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef(0);
  const fpsIntervalRef = useRef<number | null>(null);

  const getOrderedMarkerIds = (frame: VisionFrame | null) => {
    if (!frame) {
      return null;
    }
    const entries = Object.entries(frame.markers_corners || {}).map(
      ([id, corners]) => {
        const center = corners.reduce(
          (acc, point) => [acc[0] + point[0], acc[1] + point[1]],
          [0, 0],
        );
        return {
          id,
          center: [center[0] / corners.length, center[1] / corners.length],
        };
      },
    );
    if (entries.length < 4) {
      return null;
    }
    const sums = entries.map((entry) => entry.center[0] + entry.center[1]);
    const diffs = entries.map((entry) => entry.center[0] - entry.center[1]);
    const tl = entries[sums.indexOf(Math.min(...sums))];
    const br = entries[sums.indexOf(Math.max(...sums))];
    const tr = entries[diffs.indexOf(Math.max(...diffs))];
    const bl = entries[diffs.indexOf(Math.min(...diffs))];
    return [tl.id, tr.id, br.id, bl.id];
  };

  const orderedMarkerIds = getOrderedMarkerIds(visionFrame);

  useEffect(() => {
    // Calculate FPS every second
    fpsIntervalRef.current = window.setInterval(() => {
      setFps(frameCountRef.current);
      frameCountRef.current = 0;
    }, 1000);

    return () => {
      if (fpsIntervalRef.current) {
        clearInterval(fpsIntervalRef.current);
      }
    };
  }, []);

  const startVision = async () => {
    console.log("[Vision] Start Camera button clicked");
    console.log("[Vision] API URL:", apiUrl);
    
    try {
      console.log("[Vision] Sending POST to /api/vision/start");
      const response = await fetch(`${apiUrl}/api/vision/start`, {
        method: "POST",
      });
      
      console.log("[Vision] Response status:", response.status);
      const data = await response.json();
      console.log("[Vision] Response data:", data);
      
      if (data.status === 'started' || data.success) {
        console.log("[Vision] Camera started successfully, connecting WebSocket...");
        setIsActive(true);
        connectWebSocket();
      } else {
        console.error("[Vision] Camera start failed:", data);
      }
    } catch (error) {
      console.error("[Vision] Failed to start vision:", error);
    }
  };

  const stopVision = async () => {
    try {
      await fetch(`${apiUrl}/api/vision/stop`, { method: "POST" });
      setIsActive(false);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    } catch (error) {
      console.error("Failed to stop vision:", error);
    }
  };

  const calibrate = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/vision/calibrate`, {
        method: "POST",
      });
      const data = await response.json();
      console.log("[Vision] Calibrate response:", data);
      if (data.status === 'calibrated' || data.success) {
        setIsCalibrated(true);
      }
    } catch (error) {
      console.error("[Vision] Failed to calibrate:", error);
    }
  };

  const resetCalibration = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/vision/reset`, {
        method: "POST",
      });
      const data = await response.json();
      console.log("[Vision] Reset calibration response:", data);
      setIsCalibrated(false);
    } catch (error) {
      console.error("[Vision] Failed to reset calibration:", error);
    }
  };

  const connectWebSocket = () => {
    const wsUrl = apiUrl.replace("http://", "ws://").replace("https://", "wss://");
    const ws = new WebSocket(`${wsUrl}/ws/vision`);

    console.log("[Vision] Connecting to WebSocket:", `${wsUrl}/ws/vision`);

    ws.onopen = () => {
      console.log("[Vision] WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const frame: VisionFrame = JSON.parse(event.data);
        
        // Log region changes
        if (frame.current_region_id !== visionFrame?.current_region_id) {
          if (frame.current_region_id) {
            console.log("[Vision] Entering region:", frame.current_region_id, 
                       `(material: ${frame.current_material_id})`);
          } else if (visionFrame?.current_region_id) {
            console.log("[Vision] Left region:", visionFrame.current_region_id);
          }
        }
        
        // Log dwell progress
        if (frame.dwell_frames && frame.dwell_frames > 0 && frame.dwell_frames % 2 === 0) {
          console.log("[Vision] Dwelling in region:", frame.current_region_id,
                     `(${frame.dwell_frames}/5 frames)`);
        }
        
        setVisionFrame(frame);
        setIsCalibrated(frame.is_calibrated);
        if (frame.image) {
          setLastImage(frame.image);
        }
        frameCountRef.current++;
      } catch (error) {
        console.error("[Vision] Failed to parse vision frame:", error);
      }
    };

    ws.onerror = (error) => {
      console.error("[Vision] WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("[Vision] WebSocket closed");
      wsRef.current = null;
    };

    wsRef.current = ws;
  };

  return (
    <div className="vision-panel">
      <div className="vision-header">
        <h2>Vision System</h2>
        <div className="vision-controls">
          {!isActive ? (
            <button onClick={startVision} className="btn-primary">
              Start Camera
            </button>
          ) : (
            <button onClick={stopVision} className="btn-secondary">
              Stop Camera
            </button>
          )}
          {isActive && (
            <button
              onClick={calibrate}
              className="btn-primary"
              disabled={!visionFrame || visionFrame.markers_detected.length < 4}
            >
              Calibrate
            </button>
          )}
          {isActive && (
            <button
              onClick={resetCalibration}
              className="btn-secondary"
              disabled={!visionFrame}
            >
              Reset Calibration
            </button>
          )}
        </div>
      </div>

      {isActive && (
        <div className="vision-status">
          <div className="vision-preview">
            {lastImage ? (
              <img
                src={`data:image/jpeg;base64,${lastImage}`}
                alt="Camera preview"
                className="preview-image"
              />
            ) : (
              <div className="preview-placeholder">Waiting for camera frames...</div>
            )}
          </div>

          <div className="status-grid">
            <div className="status-item">
              <span className="status-label">Status:</span>
              <span className={`status-value ${isCalibrated ? "success" : "warning"}`}>
                {isCalibrated ? "Calibrated" : "Not Calibrated"}
              </span>
            </div>

            <div className="status-item">
              <span className="status-label">FPS:</span>
              <span className="status-value">{fps}</span>
            </div>

            <div className="status-item">
              <span className="status-label">Markers:</span>
              <span className="status-value">
                {visionFrame?.markers_detected.length || 0} detected
                {visionFrame && visionFrame.markers_detected.length > 0 && (
                  <span className="marker-ids">
                    {" "}
                    [{visionFrame.markers_detected.join(", ")}]
                  </span>
                )}
              </span>
            </div>
            <div className="status-item">
              <span className="status-label">Line order:</span>
              <span className="status-value">
                {orderedMarkerIds ? `[${orderedMarkerIds.join(", ")}]` : "N/A"}
              </span>
            </div>

            <div className="status-item">
              <span className="status-label">Hand:</span>
              <span
                className={`status-value ${visionFrame?.hand_detected ? "success" : "inactive"}`}
              >
                {visionFrame?.hand_detected ? "Detected" : "Not detected"}
              </span>
            </div>

            {visionFrame?.hand_detected &&
              visionFrame.fingertip_u !== null &&
              visionFrame.fingertip_v !== null && (
                <div className="status-item coordinates">
                  <span className="status-label">Position:</span>
                  <span className="status-value">
                    ({visionFrame.fingertip_u.toFixed(3)},{" "}
                    {visionFrame.fingertip_v.toFixed(3)})
                  </span>
                </div>
              )}

            {visionFrame?.current_region_id && (
              <div className="status-item region-info">
                <span className="status-label">Region:</span>
                <span className="status-value success">
                  {visionFrame.current_region_id}
                  {visionFrame.dwell_frames && visionFrame.dwell_frames > 0 && (
                    <span className="dwell-indicator">
                      {" "}({visionFrame.dwell_frames}/5)
                    </span>
                  )}
                </span>
              </div>
            )}
          </div>

          {!isCalibrated && visionFrame && visionFrame.markers_detected.length < 4 && (
            <div className="vision-hint warning">
              Place 4 ArUco markers (ID 0-3) at the corners, then click Calibrate
            </div>
          )}

          {!isCalibrated && visionFrame && visionFrame.markers_detected.length >= 4 && (
            <div className="vision-hint success">
              All 4 markers detected! Click Calibrate to proceed.
            </div>
          )}

          {isCalibrated && !visionFrame?.hand_detected && (
            <div className="vision-hint info">
              Point your index finger at the camera to start tracking
            </div>
          )}
        </div>
      )}

      <style>{`
        .vision-panel {
          padding: 1.5rem;
          background: #f8f9fa;
          border-radius: 8px;
          margin-bottom: 1rem;
        }

        .vision-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1rem;
        }

        .vision-header h2 {
          margin: 0;
          font-size: 1.25rem;
          color: #2c3e50;
        }

        .vision-controls {
          display: flex;
          gap: 0.5rem;
        }

        .vision-status {
          background: white;
          padding: 1rem;
          border-radius: 6px;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .status-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1rem;
        }

        .status-item {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }

        .status-item.coordinates {
          grid-column: 1 / -1;
        }

        .status-label {
          font-size: 0.875rem;
          color: #6c757d;
          font-weight: 500;
        }

        .status-value {
          font-size: 1rem;
          font-weight: 600;
          color: #2c3e50;
        }

        .status-value.success {
          color: #28a745;
        }

        .status-value.warning {
          color: #ffc107;
        }

        .status-value.inactive {
          color: #6c757d;
        }

        .marker-ids {
          font-size: 0.875rem;
          color: #6c757d;
          font-weight: normal;
        }

        .region-info {
          grid-column: span 2;
          padding: 0.5rem;
          background: #e8f5e9;
          border-radius: 4px;
        }

        .region-info .status-value {
          font-weight: 600;
        }

        .dwell-indicator {
          font-size: 0.75rem;
          color: #666;
          font-weight: normal;
          margin-left: 0.5rem;
        }

        .vision-hint {
          margin-top: 1rem;
          padding: 0.75rem;
          border-radius: 4px;
          font-size: 0.875rem;
        }

        .vision-hint.warning {
          background: #fff3cd;
          border-left: 4px solid #ffc107;
          color: #856404;
        }

        .vision-hint.success {
          background: #d4edda;
          color: #155724;
          border-left: 4px solid #28a745;
        }

        .vision-hint.info {
          background: #d1ecf1;
          border-left: 4px solid #17a2b8;
          color: #0c5460;
        }

        .vision-preview {
          margin-bottom: 1rem;
          border-radius: 6px;
          overflow: hidden;
          background: #000;
        }

        .preview-image {
          width: 100%;
          height: auto;
          display: block;
        }

        .preview-placeholder {
          padding: 1.5rem;
          text-align: center;
          color: #f8f9fa;
          background: #1f1f1f;
          font-size: 0.95rem;
        }

        .btn-primary,
        .btn-secondary {
          padding: 0.5rem 1rem;
          border: none;
          border-radius: 4px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-primary {
          background: #007bff;
          color: white;
        }

        .btn-primary:hover:not(:disabled) {
          background: #0056b3;
        }

        .btn-primary:disabled {
          background: #6c757d;
          cursor: not-allowed;
          opacity: 0.6;
        }

        .btn-secondary {
          background: #6c757d;
          color: white;
        }

        .btn-secondary:hover {
          background: #5a6268;
        }
      `}</style>
    </div>
  );
}
