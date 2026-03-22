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
        [SerializeField] private string serverUrl = "ws://192.168.0.102:8000/stream";
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectDelaySeconds = 2f;

        private ClientWebSocket _socket;
        private CancellationTokenSource _cts;
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

                Debug.Log($"WebSocket connecting to {serverUrl}");
                await _socket.ConnectAsync(new Uri(serverUrl), _cts.Token);

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

            try
            {
                string json = JsonConvert.SerializeObject(payload);
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                await _socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cts.Token);
            }
            catch (Exception exception)
            {
                Debug.LogError($"WebSocket send failed: {exception.Message}");
                ConnectionStateChanged?.Invoke(false);
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
                        MessageReceived?.Invoke(message);
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
