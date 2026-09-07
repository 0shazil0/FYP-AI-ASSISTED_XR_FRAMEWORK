// Assets/Scripts/Copilot/CopilotWebSocketClient.cs
// Dedicated WebSocket client for the /copilot endpoint (Half 2).
// Completely separate from WebSocketManager — does NOT conflict with Half 1.
using System;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using UnityEngine;
using NeuroGuideXR.Networking;   // reuse MainThreadDispatcher

namespace NeuroGuideXR.Copilot
{
    public sealed class CopilotWebSocketClient : MonoBehaviour
    {
        [Header("Connection")]
        [SerializeField] public string serverUrl = "ws://192.168.100.19:8000/copilot";
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectDelaySecs = 3f;
        [SerializeField] private bool tryLocalhostInEditor = true;

        // Events
        public event Action<string> OnMessageReceived;
        public event Action<byte[]> OnBinaryMessageReceived;
        public event Action<bool>   OnConnectionStateChanged;

        public bool IsConnected => _socket?.State == WebSocketState.Open;

        private ClientWebSocket       _socket;
        private CancellationTokenSource _cts;
        private readonly SemaphoreSlim _sendLock = new(1, 1);
        private bool _isQuitting;
        private bool _isConnecting;

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------

        private async void Start()
        {
            await ConnectAsync();
        }

        private async void OnApplicationQuit()
        {
            _isQuitting = true;
            await DisconnectAsync();
        }

        // ----------------------------------------------------------------
        // Connection
        // ----------------------------------------------------------------

        public async Task ConnectAsync()
        {
            if (_isConnecting || _isQuitting) return;
            _isConnecting = true;
            try
            {
                await DisconnectAsync();

                Exception lastError = null;
                foreach (var candidate in BuildConnectionCandidates())
                {
                    _socket = new ClientWebSocket();
                    _cts = new CancellationTokenSource();
                    try
                    {
                        string cleanCandidate = candidate?.Trim() ?? string.Empty;
                        Debug.Log($"[CopilotWS] Connecting to [{cleanCandidate}]...");
                        if (string.IsNullOrEmpty(cleanCandidate) || !cleanCandidate.StartsWith("ws"))
                        {
                            Debug.LogError($"[CopilotWS] URL invalid (raw='{candidate}'). Check Inspector serverUrl field.");
                            continue;
                        }
                        await _socket.ConnectAsync(new Uri(cleanCandidate), _cts.Token);
                        serverUrl = cleanCandidate;
                        MainThreadDispatcher.Enqueue(() => OnConnectionStateChanged?.Invoke(true));
                        Debug.Log("[CopilotWS] Connected!");
                        _ = ReceiveLoopAsync(_cts.Token);
                        return;
                    }
                    catch (Exception e)
                    {
                        lastError = e;
                        try
                        {
                            _socket.Dispose();
                            _cts.Dispose();
                        }
                        catch { }
                        _socket = null;
                        _cts = null;
                    }
                }

                if (lastError != null)
                    throw lastError;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[CopilotWS] Connect failed: {e.Message}");
                MainThreadDispatcher.Enqueue(() => OnConnectionStateChanged?.Invoke(false));
                if (autoReconnect && !_isQuitting)
                    _ = ScheduleReconnect();
            }
            finally { _isConnecting = false; }
        }

        public async Task DisconnectAsync()
        {
            if (_socket == null) return;
            try
            {
                _cts?.Cancel();
                if (_socket.State == WebSocketState.Open)
                    await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Closing", CancellationToken.None);
            }
            catch { /* ignore */ }
            finally
            {
                _socket.Dispose();
                _socket = null;
                _cts?.Dispose();
                _cts = null;
            }
        }

        // ----------------------------------------------------------------
        // Sending
        // ----------------------------------------------------------------

        public async void SendJson(object payload)
        {
            if (!IsConnected)
            {
                Debug.LogWarning("[CopilotWS] Send skipped — not connected.");
                return;
            }
            await _sendLock.WaitAsync();
            try
            {
                string json  = JsonConvert.SerializeObject(payload);
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                await _socket.SendAsync(
                    new ArraySegment<byte>(bytes),
                    WebSocketMessageType.Text,
                    true,
                    _cts?.Token ?? CancellationToken.None
                );
            }
            catch (Exception e) { Debug.LogError($"[CopilotWS] Send error: {e.Message}"); }
            finally { if (_sendLock.CurrentCount == 0) _sendLock.Release(); }
        }

        // ----------------------------------------------------------------
        // Receiving
        // ----------------------------------------------------------------

        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            var buffer = new byte[1024 * 128];
            try
            {
                while (!token.IsCancellationRequested && IsConnected)
                {
                    using (var ms = new System.IO.MemoryStream())
                    {
                        WebSocketReceiveResult result;
                        do
                        {
                            result = await _socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                            if (result.MessageType == WebSocketMessageType.Close) goto disconnect;
                            ms.Write(buffer, 0, result.Count);
                        }
                        while (!result.EndOfMessage);

                        byte[] msgBytes = ms.ToArray();
                        if (result.MessageType == WebSocketMessageType.Binary)
                        {
                            MainThreadDispatcher.Enqueue(() => OnBinaryMessageReceived?.Invoke(msgBytes));
                        }
                        else if (result.MessageType == WebSocketMessageType.Text)
                        {
                            string msg = Encoding.UTF8.GetString(msgBytes);
                            MainThreadDispatcher.Enqueue(() => OnMessageReceived?.Invoke(msg));
                        }
                    }
                }
            }
            catch (OperationCanceledException) { /* shutdown */ }
            catch (Exception e) { Debug.LogWarning($"[CopilotWS] Receive loop ended: {e.Message}"); }

            disconnect:
            MainThreadDispatcher.Enqueue(() => OnConnectionStateChanged?.Invoke(false));
            if (autoReconnect && !_isQuitting) _ = ScheduleReconnect();
        }

        private async Task ScheduleReconnect()
        {
            await Task.Delay(TimeSpan.FromSeconds(reconnectDelaySecs));
            if (!_isQuitting) await ConnectAsync();
        }

        private IEnumerable<string> BuildConnectionCandidates()
        {
            yield return serverUrl;

            if (!tryLocalhostInEditor || !Application.isEditor)
                yield break;

            if (!string.Equals(serverUrl, "ws://127.0.0.1:8000/copilot", StringComparison.OrdinalIgnoreCase))
                yield return "ws://127.0.0.1:8000/copilot";
            if (!string.Equals(serverUrl, "ws://localhost:8000/copilot", StringComparison.OrdinalIgnoreCase))
                yield return "ws://localhost:8000/copilot";
        }
    }
}
