using System;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using Newtonsoft.Json;

public class WebSocketManager : MonoBehaviour
{
    private ClientWebSocket _webSocket;
    private Uri _serverUri = new Uri("ws://192.168.100.19:8000/stream"); // Replace with actual IP when on mobile device
    private CancellationTokenSource _cancellationTokenSource;

    public static WebSocketManager Instance { get; private set; }

    public event Action<string> OnMessageReceived;

    private void Awake()
    {
        if (Instance == null)
            Instance = this;
        else
            Destroy(gameObject);
    }

    private async void Start()
    {
        await ConnectToServer();
    }

    private async Task ConnectToServer()
    {
        _webSocket = new ClientWebSocket();
        _cancellationTokenSource = new CancellationTokenSource();

        try
        {
            Debug.Log($"Connecting to {_serverUri}...");
            await _webSocket.ConnectAsync(_serverUri, _cancellationTokenSource.Token);
            Debug.Log("Connected to WebSocket Server");
            
            _ = ReceiveLoop();
        }
        catch (Exception e)
        {
            Debug.LogError($"WebSocket Connection Error: {e.Message}");
        }
    }

    private async Task ReceiveLoop()
    {
        var buffer = new byte[1024 * 64]; // 64 KB buffer
        
        while (_webSocket.State == WebSocketState.Open)
        {
            var result = await _webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), _cancellationTokenSource.Token);
            
            if (result.MessageType == WebSocketMessageType.Close)
            {
                await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, string.Empty, _cancellationTokenSource.Token);
                Debug.Log("WebSocket connection closed by server.");
                break;
            }
            
            string message = Encoding.UTF8.GetString(buffer, 0, result.Count);
            MainThreadDispatcher.Enqueue(() =>
            {
                OnMessageReceived?.Invoke(message);
            });
        }
    }

    public async Task SendMessageAsync(string message)
    {
        if (_webSocket != null && _webSocket.State == WebSocketState.Open)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(message);
            await _webSocket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cancellationTokenSource.Token);
        }
        else
        {
            Debug.LogWarning("Cannot send message. WebSocket is not open.");
        }
    }

    private void OnDestroy()
    {
        if (_webSocket != null)
        {
            _cancellationTokenSource?.Cancel();
            _webSocket.Dispose();
        }
    }
}

// Simple MainThreadDispatcher to invoke Unity actions from async threads
public class MainThreadDispatcher : MonoBehaviour
{
    private static readonly System.Collections.Concurrent.ConcurrentQueue<Action> _executionQueue = new System.Collections.Concurrent.ConcurrentQueue<Action>();

    public static void Enqueue(Action action)
    {
        _executionQueue.Enqueue(action);
    }

    private void Update()
    {
        while (_executionQueue.TryDequeue(out var action))
        {
            action.Invoke();
        }
    }
}
