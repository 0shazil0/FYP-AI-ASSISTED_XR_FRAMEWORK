using System;
using System.Collections;
using System.Collections.Generic;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using NeuroGuideXR.Networking;

namespace NeuroGuideXR.AR
{
    public sealed class ARCameraCapture : MonoBehaviour
    {
        [SerializeField] private ARCameraManager cameraManager;
        [SerializeField, Range(20, 95)] private int jpegQuality = 60;
        [SerializeField, Range(0.25f, 2f)] private float captureScale = 0.5f;
        [SerializeField] private float minCaptureIntervalSeconds = 1.5f;

        private bool _isCapturing;
        private float _lastCaptureTime;

        public bool CanCapture => Time.time - _lastCaptureTime >= minCaptureIntervalSeconds && !_isCapturing;

        private void Awake()
        {
            if (cameraManager == null)
            {
                cameraManager = GetComponent<ARCameraManager>();
            }
        }

        public IEnumerator CaptureAndSendFrame()
        {
            yield return CaptureAndSendFrame("frame");
        }

        public IEnumerator CaptureAndSendFrame(string messageType, string promptText = null, string requestMode = null)
        {
            yield return CaptureAndSendFrame(messageType, promptText, requestMode, null);
        }

        public IEnumerator CaptureAndSendFrame(string messageType, string promptText, string requestMode, Action<bool, string> onCompleted)
        {
            Debug.Log($"[DEBUG] CaptureAndSendFrame: Starting capture, messageType={messageType}");
            
            if (!CanCapture)
            {
                Debug.LogWarning("[DEBUG] CaptureAndSendFrame: Cannot capture - cooldown active or already capturing");
                onCompleted?.Invoke(false, "Capture cooldown active. Try again in a moment.");
                yield break;
            }

            if (cameraManager == null)
            {
                Debug.LogError("[DEBUG] CaptureAndSendFrame: cameraManager is null");
                onCompleted?.Invoke(false, "ARCameraManager reference is missing.");
                yield break;
            }

            if (WebSocketManager.Instance == null)
            {
                Debug.LogError("[DEBUG] CaptureAndSendFrame: WebSocketManager.Instance is null");
                onCompleted?.Invoke(false, "WebSocketManager is missing in the scene.");
                yield break;
            }

            if (!WebSocketManager.Instance.IsConnected)
            {
                Debug.LogWarning($"[DEBUG] CaptureAndSendFrame: WebSocket not connected");
                onCompleted?.Invoke(false, "WebSocket is disconnected.");
                yield break;
            }

            _isCapturing = true;
            _lastCaptureTime = Time.time;

            if (!cameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
            {
                _isCapturing = false;
                Debug.LogError("[DEBUG] CaptureAndSendFrame: Failed to acquire CPU image");
                onCompleted?.Invoke(false, "Failed to acquire camera CPU image.");
                yield break;
            }

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Acquired CPU image, original size={image.width}x{image.height}");

            int outWidth = Mathf.Max(64, Mathf.RoundToInt(image.width * captureScale));
            int outHeight = Mathf.Max(64, Mathf.RoundToInt(image.height * captureScale));

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Scaled to {outWidth}x{outHeight}");

            var conversion = new XRCpuImage.ConversionParams
            {
                inputRect = new RectInt(0, 0, image.width, image.height),
                outputDimensions = new Vector2Int(outWidth, outHeight),
                outputFormat = TextureFormat.RGB24,
                transformation = XRCpuImage.Transformation.None
            };

            int size = image.GetConvertedDataSize(conversion);
            var buffer = new NativeArray<byte>(size, Allocator.Temp);

            image.Convert(conversion, buffer);
            image.Dispose();

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Converted to buffer, size={buffer.Length} bytes");

            var texture = new Texture2D(outWidth, outHeight, TextureFormat.RGB24, false);
            texture.LoadRawTextureData(buffer);
            texture.Apply();
            buffer.Dispose();

            byte[] jpg = texture.EncodeToJPG(jpegQuality);
            Destroy(texture);

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Encoded JPEG, size={jpg.Length} bytes");

            var payload = new Dictionary<string, object>
            {
                ["type"] = string.IsNullOrWhiteSpace(messageType) ? "frame" : messageType,
                ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["image_data"] = Convert.ToBase64String(jpg),
                ["imu_data"] = BuildImuPayload()
            };

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Created payload with base64 image data of length {((string)payload["image_data"]).Length}");

            if (!string.IsNullOrWhiteSpace(promptText))
            {
                payload["prompt"] = promptText;
            }

            if (!string.IsNullOrWhiteSpace(requestMode))
            {
                payload["request_mode"] = requestMode;
            }

            Debug.Log($"[DEBUG] CaptureAndSendFrame: Sending payload to WebSocket...");
            _ = WebSocketManager.Instance.SendJsonAsync(payload);

            _isCapturing = false;
            onCompleted?.Invoke(true, "Snapshot sent to backend.");
            yield return null;
        }

        private Dictionary<string, object> BuildImuPayload()
        {
            Input.gyro.enabled = true;

            Vector3 acceleration = Input.acceleration;
            Vector3 gyroRate = Input.gyro.rotationRateUnbiased;
            Quaternion attitude = Input.gyro.attitude;

            return new Dictionary<string, object>
            {
                ["accel"] = new[] { acceleration.x, acceleration.y, acceleration.z },
                ["gyro"] = new[] { gyroRate.x, gyroRate.y, gyroRate.z },
                ["attitude"] = new[] { attitude.x, attitude.y, attitude.z, attitude.w },
                ["device_orientation"] = Input.deviceOrientation.ToString(),
                ["sent_at_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
        }
    }
}
