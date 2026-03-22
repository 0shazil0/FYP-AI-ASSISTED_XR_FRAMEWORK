using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using NeuroGuideXR.AR;
using NeuroGuideXR.Networking;
using UnityEngine;
using UnityEngine.UI;

namespace NeuroGuideXR.UI
{
    public sealed class SnapDemoUI : MonoBehaviour
    {
        [SerializeField] private Canvas targetCanvas;
        [SerializeField] private ARCameraCapture cameraCapture;
        [SerializeField] private WebSocketManager webSocketManager;
        [SerializeField] private bool disableAttentionGateForDemo = true;

        private GameObject _panelRoot;
        private Text _statusText;
        private Text _responseText;
        private InputField _promptInput;
        private Button _snapButton;
        private Button _askButton;
        private Button _prevStepButton;
        private Button _nextStepButton;
        private Font _font;
        private JObject _lastStepGuidance;

        private void Awake()
        {
            if (targetCanvas == null)
            {
                targetCanvas = GetComponent<Canvas>();
                if (targetCanvas == null)
                {
                    targetCanvas = FindFirstObjectByType<Canvas>();
                }
            }

            if (cameraCapture == null)
            {
                cameraCapture = FindFirstObjectByType<ARCameraCapture>();
            }

            if (FindFirstObjectByType<IMUSensorStreamer>() == null)
            {
                GameObject imuHost = cameraCapture != null ? cameraCapture.gameObject : gameObject;
                imuHost.AddComponent<IMUSensorStreamer>();
            }

            if (disableAttentionGateForDemo)
            {
                var attentionGate = FindFirstObjectByType<AttentionGate>();
                if (attentionGate != null)
                {
                    attentionGate.enabled = false;
                }
            }

            if (webSocketManager == null)
            {
                webSocketManager = WebSocketManager.Instance != null ? WebSocketManager.Instance : FindFirstObjectByType<WebSocketManager>();
            }

            _font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            BuildUI();
        }

        private void OnEnable()
        {
            Subscribe();
        }

        private void Start()
        {
            Subscribe();
            SetStatus("Tap Snap to analyze the current scene.");
            SetPromptInteraction(false);
        }

        private void OnDisable()
        {
            if (webSocketManager != null)
            {
                webSocketManager.MessageReceived -= OnMessageReceived;
                webSocketManager.ConnectionStateChanged -= OnConnectionStateChanged;
            }
        }

        private void Subscribe()
        {
            if (webSocketManager == null)
            {
                webSocketManager = WebSocketManager.Instance != null ? WebSocketManager.Instance : FindFirstObjectByType<WebSocketManager>();
            }

            if (webSocketManager == null)
            {
                return;
            }

            webSocketManager.MessageReceived -= OnMessageReceived;
            webSocketManager.MessageReceived += OnMessageReceived;
            webSocketManager.ConnectionStateChanged -= OnConnectionStateChanged;
            webSocketManager.ConnectionStateChanged += OnConnectionStateChanged;
        }

        private void BuildUI()
        {
            if (targetCanvas == null || _panelRoot != null)
            {
                return;
            }

            _panelRoot = CreatePanel("Snap Demo Panel", targetCanvas.transform, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), new Vector2(0f, 18f), new Vector2(720f, 330f), new Color(0.05f, 0.07f, 0.1f, 0.78f));

            _statusText = CreateText("Status Text", _panelRoot.transform, new Vector2(20f, -18f), new Vector2(680f, 34f), 24, TextAnchor.UpperLeft, Color.white);
            _statusText.text = "Connecting...";

            _responseText = CreateText("Response Text", _panelRoot.transform, new Vector2(20f, -58f), new Vector2(680f, 150f), 20, TextAnchor.UpperLeft, new Color(0.92f, 0.96f, 1f, 1f));
            _responseText.horizontalOverflow = HorizontalWrapMode.Wrap;
            _responseText.verticalOverflow = VerticalWrapMode.Overflow;
            _responseText.text = "Scene insights will appear here.";

            _promptInput = CreateInputField("Prompt Input", _panelRoot.transform, new Vector2(20f, -226f), new Vector2(500f, 44f), "Ask anything about the scene...");
            _promptInput.lineType = InputField.LineType.MultiLineNewline;

            _snapButton = CreateButton("Snap Button", _panelRoot.transform, new Vector2(536f, -226f), new Vector2(164f, 44f), "Snap", new Color(0.12f, 0.49f, 0.98f, 0.95f));
            _snapButton.onClick.AddListener(OnSnapClicked);

            _askButton = CreateButton("Ask Button", _panelRoot.transform, new Vector2(536f, -280f), new Vector2(164f, 36f), "Ask", new Color(0.18f, 0.72f, 0.33f, 0.95f));
            _askButton.onClick.AddListener(OnAskClicked);

            _prevStepButton = CreateButton("Prev Step Button", _panelRoot.transform, new Vector2(536f, -322f), new Vector2(78f, 32f), "Prev", new Color(0.52f, 0.58f, 0.69f, 0.95f));
            _prevStepButton.onClick.AddListener(OnPrevStepClicked);

            _nextStepButton = CreateButton("Next Step Button", _panelRoot.transform, new Vector2(622f, -322f), new Vector2(78f, 32f), "Next", new Color(0.95f, 0.59f, 0.18f, 0.95f));
            _nextStepButton.onClick.AddListener(OnNextStepClicked);

            Text helperText = CreateText("Helper Text", _panelRoot.transform, new Vector2(20f, -278f), new Vector2(500f, 36f), 18, TextAnchor.UpperLeft, new Color(0.72f, 0.8f, 0.9f, 1f));
            helperText.text = "Example: From the available ingredients, suggest a quick recipe.";
        }

        private void OnSnapClicked()
        {
            Debug.Log("[DEBUG] OnSnapClicked: Snap button pressed");
            
            if (webSocketManager == null)
            {
                webSocketManager = WebSocketManager.Instance != null ? WebSocketManager.Instance : FindFirstObjectByType<WebSocketManager>();
            }

            if (webSocketManager == null)
            {
                SetStatus("WebSocketManager not found.");
                _responseText.text = "Add NeuroGuideManager/WebSocketManager to the scene.";
                Debug.LogError("[DEBUG] OnSnapClicked: WebSocketManager is null");
                return;
            }

            if (!webSocketManager.IsConnected)
            {
                SetStatus("Backend disconnected.");
                _responseText.text = $"Cannot send snapshot. Check backend and URL: {webSocketManager.ServerUrl}";
                Debug.LogWarning($"[DEBUG] OnSnapClicked: WebSocket not connected, URL={webSocketManager.ServerUrl}");
                return;
            }

            if (cameraCapture == null)
            {
                SetStatus("ARCameraCapture not found in scene.");
                Debug.LogError("[DEBUG] OnSnapClicked: ARCameraCapture is null");
                return;
            }

            Debug.Log("[DEBUG] OnSnapClicked: Starting capture coroutine...");
            SetStatus("Analyzing current scene...");
            SetPromptInteraction(false);
            _responseText.text = "Sending snapshot to Ollama...";
            StartCoroutine(cameraCapture.CaptureAndSendFrame("snapshot", null, "snapshot_demo", OnSnapshotSendCompleted));
        }

        private void OnSnapshotSendCompleted(bool success, string message)
        {
            Debug.Log($"[DEBUG] OnSnapshotSendCompleted: success={success}, message={message}");
            
            if (success)
            {
                SetStatus("Snapshot sent. Waiting for analysis...");
                return;
            }

            SetStatus("Snapshot failed.");
            _responseText.text = message;
            SetPromptInteraction(false);
        }

        private void OnAskClicked()
        {
            if (webSocketManager == null || !webSocketManager.IsConnected)
            {
                SetStatus("Backend not connected.");
                return;
            }

            string prompt = _promptInput != null ? _promptInput.text.Trim() : string.Empty;
            if (string.IsNullOrWhiteSpace(prompt))
            {
                SetStatus("Enter a prompt first.");
                return;
            }

            SetStatus("Processing your prompt...");
            _responseText.text = "Waiting for Ollama response...";
            _ = webSocketManager.SendJsonAsync(new Dictionary<string, object>
            {
                ["type"] = "prompt",
                ["prompt"] = prompt,
                ["request_mode"] = "demo_followup"
            });
        }

        private void OnPrevStepClicked()
        {
            SendStepControl("previous");
        }

        private void OnNextStepClicked()
        {
            SendStepControl("next");
        }

        private void SendStepControl(string action)
        {
            if (webSocketManager == null || !webSocketManager.IsConnected)
            {
                SetStatus("Backend not connected.");
                return;
            }

            if (_lastStepGuidance == null)
            {
                SetStatus("No step guidance loaded yet. Tap Snap first.");
                return;
            }

            SetStatus($"Updating step: {action}...");
            _ = webSocketManager.SendJsonAsync(new Dictionary<string, object>
            {
                ["type"] = "step_control",
                ["action"] = action,
            });
        }

        private void OnConnectionStateChanged(bool isConnected)
        {
            SetStatus(isConnected
                ? "Connected. Tap Snap to analyze the current scene."
                : "Disconnected from backend.");
        }

        private void OnMessageReceived(string json)
        {
            Debug.Log($"[DEBUG] OnMessageReceived: Received JSON of length {json.Length}");
            
            JObject payload;
            try
            {
                payload = JObject.Parse(json);
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"SnapDemoUI failed to parse JSON: {exception.Message}");
                return;
            }

            string messageType = payload.Value<string>("type") ?? string.Empty;
            Debug.Log($"[DEBUG] OnMessageReceived: Message type = {messageType}");
            
            switch (messageType)
            {
                case "snapshot_result":
                    Debug.Log("[DEBUG] OnMessageReceived: Handling snapshot_result");
                    HandleSnapshotResult(payload);
                    break;
                case "prompt_response":
                    Debug.Log("[DEBUG] OnMessageReceived: Handling prompt_response");
                    HandlePromptResponse(payload);
                    break;
                case "step_update":
                    Debug.Log("[DEBUG] OnMessageReceived: Handling step_update");
                    HandleStepUpdate(payload);
                    break;
                case "error":
                    Debug.LogError($"[DEBUG] OnMessageReceived: Backend error: {payload.Value<string>("message")}");
                    SetStatus(payload.Value<string>("message") ?? "Backend error.");
                    break;
            }
        }

        private void HandleSnapshotResult(JObject payload)
        {
            Debug.Log($"[DEBUG] HandleSnapshotResult: Processing snapshot result, payload keys = {string.Join(", ", payload.Properties().Select(p => p.Name))}");
            
            string sceneSummary = payload.Value<string>("scene_summary") ?? "Scene analyzed.";
            string userMessage = payload.Value<string>("user_message") ?? "Scene has been analyzed. What do you want to do?";
            string instruction = payload.Value<string>("instruction_text") ?? string.Empty;
            JArray suggested = payload.Value<JArray>("suggested_queries");
            JObject stepGuidance = payload.Value<JObject>("step_guidance");
            _lastStepGuidance = stepGuidance;
            string stepBlock = BuildStepSummary(stepGuidance);

            Debug.Log($"[DEBUG] HandleSnapshotResult: sceneSummary={sceneSummary}, instruction={instruction}");

            string suggestionBlock = string.Empty;
            if (suggested != null && suggested.Count > 0)
            {
                suggestionBlock = "\n\nTry asking:\n- " + string.Join("\n- ", suggested.ToObject<string[]>());
                if (_promptInput != null && string.IsNullOrWhiteSpace(_promptInput.text))
                {
                    _promptInput.text = suggested[0]?.ToString() ?? string.Empty;
                }
            }

            SetStatus(userMessage);
            _responseText.text = $"Scene summary: {sceneSummary}\n\nInstruction: {instruction}{stepBlock}{suggestionBlock}";
            SetPromptInteraction(true);
        }

        private void HandlePromptResponse(JObject payload)
        {
            string responseText = payload.Value<string>("response_text")
                                  ?? payload.Value<string>("instruction_text")
                                  ?? "Response ready.";
            JObject stepGuidance = payload.Value<JObject>("step_guidance");
            _lastStepGuidance = stepGuidance;
            string stepBlock = BuildStepSummary(stepGuidance);
            string task = payload.Value<string>("task") ?? "assistant";
            SetStatus($"Response ready for {task}.");
            _responseText.text = string.IsNullOrWhiteSpace(stepBlock)
                ? responseText
                : $"{responseText}\n\n{stepBlock}";
            SetPromptInteraction(true);
        }

        private void HandleStepUpdate(JObject payload)
        {
            string message = payload.Value<string>("user_message") ?? "Step updated.";
            string instructionText = payload.Value<string>("instruction_text") ?? "Follow the highlighted step.";
            JObject stepGuidance = payload.Value<JObject>("step_guidance");
            _lastStepGuidance = stepGuidance;
            string stepBlock = BuildStepSummary(stepGuidance);

            SetStatus(message);
            _responseText.text = string.IsNullOrWhiteSpace(stepBlock)
                ? instructionText
                : $"{instructionText}\n\n{stepBlock}";
            SetPromptInteraction(true);
        }

        private string BuildStepSummary(JObject stepGuidance)
        {
            if (stepGuidance == null)
            {
                return string.Empty;
            }

            string title = stepGuidance.Value<string>("recipe_title") ?? "Live guidance";
            int currentStep = Mathf.Max(1, stepGuidance.Value<int?>("current_step") ?? 1);
            int totalSteps = Mathf.Max(currentStep, stepGuidance.Value<int?>("total_steps") ?? currentStep);

            string currentInstruction = string.Empty;
            JArray steps = stepGuidance.Value<JArray>("steps");
            if (steps != null && steps.Count >= currentStep)
            {
                JObject step = steps[currentStep - 1] as JObject;
                currentInstruction = step?.Value<string>("instruction") ?? string.Empty;
            }

            if (string.IsNullOrWhiteSpace(currentInstruction))
            {
                return $"\n\nGuide: {title} | Step {currentStep}/{totalSteps}";
            }

            return $"\n\nGuide: {title} | Step {currentStep}/{totalSteps}\nCurrent step: {currentInstruction}";
        }

        private void SetStatus(string message)
        {
            if (_statusText != null)
            {
                _statusText.text = message;
            }
        }

        private void SetPromptInteraction(bool isEnabled)
        {
            if (_promptInput != null)
            {
                _promptInput.interactable = isEnabled;
            }

            if (_askButton != null)
            {
                _askButton.interactable = isEnabled;
            }

            if (_prevStepButton != null)
            {
                _prevStepButton.interactable = isEnabled;
            }

            if (_nextStepButton != null)
            {
                _nextStepButton.interactable = isEnabled;
            }
        }

        private GameObject CreatePanel(string name, Transform parent, Vector2 anchorMin, Vector2 anchorMax, Vector2 anchoredPosition, Vector2 sizeDelta, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = new Vector2(0.5f, 0f);
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = sizeDelta;
            go.GetComponent<Image>().color = color;
            return go;
        }

        private Text CreateText(string name, Transform parent, Vector2 anchoredPosition, Vector2 sizeDelta, int fontSize, TextAnchor alignment, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = sizeDelta;

            var text = go.GetComponent<Text>();
            text.font = _font;
            text.fontSize = fontSize;
            text.alignment = alignment;
            text.color = color;
            text.supportRichText = true;
            return text;
        }

        private InputField CreateInputField(string name, Transform parent, Vector2 anchoredPosition, Vector2 sizeDelta, string placeholderText)
        {
            var root = new GameObject(name, typeof(RectTransform), typeof(Image), typeof(InputField));
            root.transform.SetParent(parent, false);
            var rect = root.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = sizeDelta;
            root.GetComponent<Image>().color = new Color(1f, 1f, 1f, 0.12f);

            var text = CreateText("Text", root.transform, new Vector2(12f, -8f), new Vector2(sizeDelta.x - 24f, sizeDelta.y - 16f), 20, TextAnchor.UpperLeft, Color.white);
            var placeholder = CreateText("Placeholder", root.transform, new Vector2(12f, -8f), new Vector2(sizeDelta.x - 24f, sizeDelta.y - 16f), 20, TextAnchor.UpperLeft, new Color(0.8f, 0.85f, 0.9f, 0.6f));
            placeholder.text = placeholderText;

            var input = root.GetComponent<InputField>();
            input.textComponent = text;
            input.placeholder = placeholder;
            input.targetGraphic = root.GetComponent<Image>();
            input.characterLimit = 300;
            return input;
        }

        private Button CreateButton(string name, Transform parent, Vector2 anchoredPosition, Vector2 sizeDelta, string label, Color color)
        {
            var root = new GameObject(name, typeof(RectTransform), typeof(Image), typeof(Button));
            root.transform.SetParent(parent, false);
            var rect = root.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = sizeDelta;

            var image = root.GetComponent<Image>();
            image.color = color;
            var button = root.GetComponent<Button>();
            button.targetGraphic = image;

            var labelText = CreateText("Label", root.transform, new Vector2(0f, 0f), sizeDelta, 22, TextAnchor.MiddleCenter, Color.white);
            labelText.rectTransform.anchorMin = Vector2.zero;
            labelText.rectTransform.anchorMax = Vector2.one;
            labelText.rectTransform.pivot = new Vector2(0.5f, 0.5f);
            labelText.rectTransform.offsetMin = Vector2.zero;
            labelText.rectTransform.offsetMax = Vector2.zero;
            labelText.text = label;
            return button;
        }
    }
}
