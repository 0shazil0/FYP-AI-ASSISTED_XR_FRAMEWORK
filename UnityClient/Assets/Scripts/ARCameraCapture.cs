using System;
using System.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using Unity.Collections;

public class ARCameraCapture : MonoBehaviour
{
    public ARCameraManager cameraManager;
    [Tooltip("Quality of JPEG encoding (0-100)")]
    public int jpegQuality = 50;

    private bool _isCapturing = false;

    private void OnEnable()
    {
        if (cameraManager != null)
        {
            cameraManager.frameReceived += OnCameraFrameReceived;
        }
    }

    private void OnDisable()
    {
        if (cameraManager != null)
            cameraManager.frameReceived -= OnCameraFrameReceived;
    }

    private void OnCameraFrameReceived(ARCameraFrameEventArgs eventArgs)
    {
        // We handle capture conditionally based on Attention Gate
    }

    /// <summary>
    /// Gets a single frame and sends it over WebSocket as Base64 string.
    /// Triggered by the AttentionGate when the user focuses on an object.
    /// </summary>
    public IEnumerator CaptureAndSendFrame()
    {
        if (_isCapturing || cameraManager == null || WebSocketManager.Instance == null)
            yield break;

        _isCapturing = true;

        if (cameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
        {
            var conversionParams = new XRCpuImage.ConversionParams
            {
                inputRect = new RectInt(0, 0, image.width, image.height),
                outputDimensions = new Vector2Int(image.width / 2, image.height / 2),
                outputFormat = TextureFormat.RGB24,
                transformation = XRCpuImage.Transformation.None
            };

            int size = image.GetConvertedDataSize(conversionParams);
            var buffer = new NativeArray<byte>(size, Allocator.Temp);

            image.Convert(conversionParams, buffer);
            image.Dispose();

            // Create texture
            Texture2D texture = new Texture2D(
                conversionParams.outputDimensions.x,
                conversionParams.outputDimensions.y,
                conversionParams.outputFormat,
                false);

            texture.LoadRawTextureData(buffer);
            texture.Apply();
            buffer.Dispose();

            // Encode to JPG
            byte[] jpgBytes = texture.EncodeToJPG(jpegQuality);
            Destroy(texture); // Clean up memory

            string base64Image = Convert.ToBase64String(jpgBytes);

            // Create JSON payload
            string payload = $"{{\"type\": \"frame\", \"image_data\": \"{base64Image}\"}}";
            
            // Send payload to backend asynchronously
            _ = WebSocketManager.Instance.SendMessageAsync(payload);
        }

        _isCapturing = false;
        yield return null;
    }
}
