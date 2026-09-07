using System;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using UnityEngine;

namespace NeuroGuideXR.Networking
{
    public sealed class WebSocketManager : MonoBehaviour
    {
        [SerializeField] private string serverUrl = "ws://192.168.100.19:8000/stream";
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectDelaySeconds = 2f;

        private ClientWebSocket _socket;
        private CancellationTokenSource _cts;
        private readonly SemaphoreSlim _sendLock = new(1, 1);
        private bool _isQuitting;
        private bool _isConnecting;

        public static WebSocketManager Instance { get; private set; }
        public bool IsConnected => _socket != null && _socket.State == WebSocketState.Open;
        public string ServerUrl => serverUrl;

        public event Action<string> MessageReceived;
        public event Action<bool> ConnectionStateChanged;

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);
            MainThreadDispatcher.EnsureExists();
        }

        private async void Start()
        {
            await ConnectAsync();
        }

        public async Task ConnectAsync()
        {
            if (_isConnecting || _isQuitting)
            {
                return;
            }

            _isConnecting = true;

            try
            {
                await DisconnectAsync();
                _socket = new ClientWebSocket();
                _cts = new CancellationTokenSource();

                // Trim any accidental whitespace from serialized Inspector values
                string cleanUrl = serverUrl?.Trim() ?? string.Empty;
                Debug.Log($"WebSocket connecting to [{cleanUrl}]");
                
                if (string.IsNullOrEmpty(cleanUrl) || !cleanUrl.StartsWith("ws"))
                {
                    Debug.LogError($"WebSocket URL is invalid (raw='{serverUrl}'). Check the serverUrl field in the Inspector.");
                    return;
                }
                
                await _socket.ConnectAsync(new Uri(cleanUrl), _cts.Token);

                ConnectionStateChanged?.Invoke(true);
                _ = ReceiveLoopAsync(_cts.Token);
                Debug.Log("WebSocket connected");
            }
            catch (Exception exception)
            {
                Debug.LogError($"WebSocket connect failed: {exception.Message}");
                ConnectionStateChanged?.Invoke(false);

                if (autoReconnect && !_isQuitting)
                {
                    await ScheduleReconnectAsync();
                }
            }
            finally
            {
                _isConnecting = false;
            }
        }

        public async Task SendJsonAsync(object payload)
        {
            if (!IsConnected)
            {
                Debug.LogWarning("WebSocket send skipped because client is not connected.");
                return;
            }

            ClientWebSocket socket = _socket;
            CancellationToken token = _cts?.Token ?? CancellationToken.None;

            if (socket == null)
            {
                Debug.LogWarning("WebSocket send skipped because socket is null.");
                return;
            }

            await _sendLock.WaitAsync(token);
            try
            {
                string json = JsonConvert.SerializeObject(payload);
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                if (socket.State != WebSocketState.Open)
                {
                    Debug.LogWarning($"WebSocket send skipped because socket state is {socket.State}.");
                    return;
                }

                await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, token);
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception exception)
            {
                Debug.LogError($"WebSocket send failed: {exception.Message}");
                ConnectionStateChanged?.Invoke(false);
            }
            finally
            {
                if (_sendLock.CurrentCount == 0)
                {
                    _sendLock.Release();
                }
            }
        }

        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            var buffer = new byte[1024 * 64];
            var builder = new StringBuilder(1024 * 2);

            try
            {
                while (!token.IsCancellationRequested && IsConnected)
                {
                    builder.Clear();

                    WebSocketReceiveResult result;
                    do
                    {
                        result = await _socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);

                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            break;
                        }

                        builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                    }
                    while (!result.EndOfMessage);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        break;
                    }

                    string message = builder.ToString();
                    MainThreadDispatcher.Enqueue(() =>
                    {
                        NotifyMessageHandlers(message);
                        Debug.Log($"WebSocket received message ({message.Length} chars)");
                    });
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"WebSocket receive loop ended: {exception.Message}");
            }

            ConnectionStateChanged?.Invoke(false);

            if (autoReconnect && !_isQuitting)
            {
                await ScheduleReconnectAsync();
            }
        }

        private async Task ScheduleReconnectAsync()
        {
            await Task.Delay(TimeSpan.FromSeconds(reconnectDelaySeconds));
            if (!_isQuitting)
            {
                await ConnectAsync();
            }
        }

        private void NotifyMessageHandlers(string message)
        {
            Action<string> handlers = MessageReceived;
            if (handlers == null)
            {
                return;
            }

            foreach (Delegate subscriber in handlers.GetInvocationList())
            {
                if (subscriber is not Action<string> handler)
                {
                    continue;
                }

                try
                {
                    handler.Invoke(message);
                }
                catch (Exception exception)
                {
                    string owner = handler.Method.DeclaringType != null
                        ? handler.Method.DeclaringType.Name
                        : "Unknown";
                    Debug.LogError($"WebSocket MessageReceived handler failed ({owner}.{handler.Method.Name}): {exception.Message}");
                }
            }
        }

        public async Task DisconnectAsync()
        {
            if (_socket == null)
            {
                return;
            }

            try
            {
                _cts?.Cancel();
                if (_socket.State == WebSocketState.Open)
                {
                    await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Client closing", CancellationToken.None);
                }
            }
            catch
            {
            }
            finally
            {
                _socket.Dispose();
                _socket = null;
                _cts?.Dispose();
                _cts = null;
            }
        }

        private async void OnApplicationQuit()
        {
            _isQuitting = true;
            await DisconnectAsync();
        }
    }
}
