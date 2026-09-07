using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using NeuroGuideXR.AR;
using NeuroGuideXR.Networking;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace NeuroGuideXR.UI
{
    public sealed class SnapDemoUI : MonoBehaviour
    {
        [SerializeField] private Canvas targetCanvas;
        [SerializeField] private ARCameraCapture cameraCapture;
        [SerializeField] private WebSocketManager webSocketManager;
        [SerializeField] private IMUSensorStreamer imuSensorStreamer;
        [SerializeField] private bool disableAttentionGateForDemo = true;

        private GameObject _panelRoot;
        private Text _statusText;
        private Text _responseText;
        private ScrollRect _responseScroll;
        private InputField _promptInput;
        private Button _snapButton;
        private Button _askButton;
        private Button _prevStepButton;
        private Button _nextStepButton;
        private Button _completeStepButton;
        private Font _font;
        private JObject _lastStepGuidance;

        // ── Persona picker ────────────────────────────────────────────
        private string _activePersona = "gym_trainer";
        private Button _personaGymBtn;
        private Button _personaChefBtn;
        private Button _personaPhysioBtn;
        private static readonly Color ColPersonaActive   = new Color(0.12f, 0.49f, 0.98f, 1f);
        private static readonly Color ColPersonaInactive = new Color(0.22f, 0.26f, 0.34f, 0.9f);

        // ── Machine detection popup ───────────────────────────────────
        private GameObject _machinePopup;
        private Text _machinePopupText;
        private Coroutine _popupDismissCoroutine;
        private string _lastMachineLabel = string.Empty;

        // ── YOLO suggestion chips ──────────────────────────────────
        private GameObject _suggestionChipRow;
        private readonly Button[] _chipButtons = new Button[3];
        private readonly Text[]   _chipTexts   = new Text[3];
        private Coroutine _chipDismissCoroutine;

        // ── Exercise GIF panel reference ────────────────────────────
        private ExerciseGifPanel _exercisePanel;

        // ── YOLO last-detection cache (for AR placement) ──────────────
        private float[] _lastDetectedBbox;
        private float   _lastDetectedCxNorm;
        private float   _lastDetectedCyNorm;
        private string  _lastDetectedLabel = string.Empty;

        // ── Status colours ────────────────────────────────────────────
        private static readonly Color ColStatusOk   = new Color(0.35f, 0.95f, 0.55f, 1f);
        private static readonly Color ColStatusWarn  = new Color(1f,    0.82f, 0.22f, 1f);
        private static readonly Color ColStatusError = new Color(0.98f, 0.32f, 0.32f, 1f);
        private static readonly Color ColStatusInfo  = new Color(0.85f, 0.9f,  1f,    1f);
        private Coroutine _dotsCoroutine;

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

            if (imuSensorStreamer == null)
            {
                imuSensorStreamer = FindFirstObjectByType<IMUSensorStreamer>();
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
            EnsureEventSystem();
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
            UpdateStepButtonState(false);
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

            // Main panel — taller to fit scroll + persona row
            _panelRoot = CreatePanel("Snap Demo Panel", targetCanvas.transform,
                new Vector2(0.5f, 0f), new Vector2(0.5f, 0f),
                new Vector2(0f, 18f), new Vector2(720f, 470f),
                new Color(0.03f, 0.05f, 0.08f, 0.88f));

            // Status bar
            _statusText = CreateText("Status Text", _panelRoot.transform,
                new Vector2(20f, -16f), new Vector2(690f, 30f),
                20, TextAnchor.MiddleLeft, ColStatusInfo);
            _statusText.text = "Connecting...";

            // Scrollable response area — taller, large readable AR font
            _responseScroll = CreateScrollView("Response Scroll", _panelRoot.transform,
                new Vector2(20f, -54f), new Vector2(690f, 286f));
            _responseText = _responseScroll.content.GetComponentInChildren<Text>();
            if (_responseText != null)
            {
                _responseText.fontSize           = 26;
                _responseText.color              = new Color(0.92f, 0.96f, 1f, 1f);
                _responseText.lineSpacing        = 1.2f;
                _responseText.horizontalOverflow = HorizontalWrapMode.Wrap;
            }

            // ── Persona picker row ─────────────────────────────────────────────
            CreateText("Persona Label", _panelRoot.transform,
                new Vector2(20f, -268f), new Vector2(100f, 26f),
                17, TextAnchor.MiddleLeft, new Color(0.6f, 0.7f, 0.85f, 1f)).text = "Persona:";

            _personaGymBtn  = CreateButton("Persona Gym",   _panelRoot.transform, new Vector2(120f,  -268f), new Vector2(158f, 30f), "\U0001F3CB Gym Trainer",  ColPersonaActive);
            _personaChefBtn = CreateButton("Persona Chef",  _panelRoot.transform, new Vector2(286f,  -268f), new Vector2(140f, 30f), "\U0001F468\u200D\U0001F373 Chef",          ColPersonaInactive);
            _personaPhysioBtn= CreateButton("Persona Physio",_panelRoot.transform, new Vector2(434f,  -268f), new Vector2(140f, 30f), "\U0001F9B4 Physio",       ColPersonaInactive);

            _personaGymBtn.onClick.AddListener(()  => OnPersonaClicked("gym_trainer"));
            _personaChefBtn.onClick.AddListener(() => OnPersonaClicked("chef"));
            _personaPhysioBtn.onClick.AddListener(()=> OnPersonaClicked("physiotherapist"));

            // ── Prompt row ─────────────────────────────────────────────────────
            _promptInput = CreateInputField("Prompt Input", _panelRoot.transform,
                new Vector2(20f, -308f), new Vector2(500f, 44f), "Ask anything about the scene...");
            _promptInput.lineType = InputField.LineType.MultiLineNewline;

            _snapButton = CreateButton("Snap Button", _panelRoot.transform,
                new Vector2(524f, -308f), new Vector2(176f, 42f), "Snap",
                new Color(0.12f, 0.45f, 0.92f, 0.95f));
            _snapButton.onClick.AddListener(OnSnapClicked);

            _askButton = CreateButton("Ask Button", _panelRoot.transform,
                new Vector2(524f, -360f), new Vector2(176f, 36f), "Ask",
                new Color(0.16f, 0.62f, 0.32f, 0.95f));
            _askButton.onClick.AddListener(OnAskClicked);

            _prevStepButton = CreateButton("Prev Step Button", _panelRoot.transform,
                new Vector2(524f, -404f), new Vector2(84f, 32f), "Prev",
                new Color(0.38f, 0.44f, 0.56f, 0.95f));
            _prevStepButton.onClick.AddListener(OnPrevStepClicked);

            _nextStepButton = CreateButton("Next Step Button", _panelRoot.transform,
                new Vector2(616f, -404f), new Vector2(84f, 32f), "Next",
                new Color(0.90f, 0.55f, 0.20f, 0.95f));
            _nextStepButton.onClick.AddListener(OnNextStepClicked);

            _completeStepButton = CreateButton("Complete Step Button", _panelRoot.transform,
                new Vector2(524f, -442f), new Vector2(176f, 30f), "Complete",
                new Color(0.28f, 0.70f, 0.40f, 0.95f));
            _completeStepButton.onClick.AddListener(OnCompleteStepClicked);

            Text helperText = CreateText("Helper Text", _panelRoot.transform,
                new Vector2(20f, -360f), new Vector2(500f, 36f),
                16, TextAnchor.UpperLeft, new Color(0.60f, 0.70f, 0.85f, 1f));
            helperText.text = "Tip: Select a persona then tap Snap to analyse.";

            // ── Machine detection popup (hidden by default) ────────────────────
            BuildMachinePopup();
            // ── Suggestion chip row (hidden by default) ──────────────────────
            BuildSuggestionChipRow();
            // ── Exercise panel (world-space, separate canvas) ───────────────
            BuildExercisePanel();
        }

        private void BuildMachinePopup()
        {
            _machinePopup = CreatePanel("Machine Popup", targetCanvas.transform,
                new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                new Vector2(0f, 120f), new Vector2(500f, 90f),
                new Color(0.08f, 0.22f, 0.12f, 0.94f));
            _machinePopup.SetActive(false);

            _machinePopupText = CreateText("Machine Label", _machinePopup.transform,
                new Vector2(16f, -10f), new Vector2(360f, 70f),
                22, TextAnchor.MiddleLeft, new Color(0.5f, 1f, 0.6f, 1f));
            _machinePopupText.text = "Machine detected!";

            Button guideBtn = CreateButton("Guide Me Btn", _machinePopup.transform,
                new Vector2(386f, -10f), new Vector2(100f, 70f), "Guide Me →",
                new Color(0.14f, 0.72f, 0.38f, 1f));
            guideBtn.onClick.AddListener(OnGuideMeClicked);
        }

        private void BuildSuggestionChipRow()
        {
            // Use a HorizontalLayoutGroup so chips are always centred and never clip
            _suggestionChipRow = new GameObject("Suggestion Chips",
                typeof(RectTransform), typeof(Image), typeof(HorizontalLayoutGroup));
            _suggestionChipRow.transform.SetParent(targetCanvas.transform, false);

            var rowRt = _suggestionChipRow.GetComponent<RectTransform>();
            rowRt.anchorMin = new Vector2(0.5f, 0.5f);
            rowRt.anchorMax = new Vector2(0.5f, 0.5f);
            rowRt.pivot     = new Vector2(0.5f, 0.5f);
            rowRt.anchoredPosition = new Vector2(0f, 200f);
            rowRt.sizeDelta = new Vector2(0f, 54f);   // width controlled by layout

            _suggestionChipRow.GetComponent<Image>().color = new Color(0.05f, 0.12f, 0.20f, 0.93f);

            var hlg = _suggestionChipRow.GetComponent<HorizontalLayoutGroup>();
            hlg.childControlWidth    = false;
            hlg.childControlHeight   = false;
            hlg.childForceExpandWidth  = false;
            hlg.childForceExpandHeight = false;
            hlg.spacing              = 10f;
            hlg.padding              = new RectOffset(12, 12, 8, 8);
            hlg.childAlignment       = TextAnchor.MiddleCenter;

            // Add a ContentSizeFitter so the row auto-resizes to its children
            var csf = _suggestionChipRow.AddComponent<ContentSizeFitter>();
            csf.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
            csf.verticalFit   = ContentSizeFitter.FitMode.Unconstrained;

            string[] placeholders = { "Chip 1", "Chip 2", "Chip 3" };
            for (int i = 0; i < 3; i++)
            {
                int idx = i;

                var chipGo  = new GameObject($"Chip{idx}",
                    typeof(RectTransform), typeof(Image), typeof(Button));
                chipGo.transform.SetParent(_suggestionChipRow.transform, false);

                var chipRt = chipGo.GetComponent<RectTransform>();
                chipRt.sizeDelta = new Vector2(220f, 38f);

                var chipImg = chipGo.GetComponent<Image>();
                chipImg.color = new Color(0.14f, 0.38f, 0.72f, 0.95f);

                _chipButtons[idx] = chipGo.GetComponent<Button>();
                _chipButtons[idx].targetGraphic = chipImg;
                _chipButtons[idx].onClick.AddListener(() => OnChipClicked(idx));

                // Label
                var lblGo = new GameObject("Label",
                    typeof(RectTransform), typeof(Text));
                lblGo.transform.SetParent(chipGo.transform, false);
                var lblRt = lblGo.GetComponent<RectTransform>();
                lblRt.anchorMin = Vector2.zero;
                lblRt.anchorMax = Vector2.one;
                lblRt.sizeDelta = new Vector2(-8f, -4f);
                lblRt.anchoredPosition = Vector2.zero;

                _chipTexts[idx] = lblGo.GetComponent<Text>();
                _chipTexts[idx].font               = _font;
                _chipTexts[idx].text               = placeholders[idx];
                _chipTexts[idx].fontSize           = 17;
                _chipTexts[idx].alignment          = TextAnchor.MiddleCenter;
                _chipTexts[idx].color              = Color.white;
                _chipTexts[idx].horizontalOverflow = HorizontalWrapMode.Wrap;
                _chipTexts[idx].verticalOverflow   = VerticalWrapMode.Truncate;

                chipGo.SetActive(false);
            }

            _suggestionChipRow.SetActive(false);
        }

        private void BuildExercisePanel()
        {
            // World-space canvas for the exercise card (follows camera)
            var wsGo = new GameObject("ExercisePanelCanvas");
            var wsCanvas = wsGo.AddComponent<Canvas>();
            wsCanvas.renderMode = RenderMode.WorldSpace;
            wsGo.AddComponent<UnityEngine.UI.CanvasScaler>();
            wsGo.AddComponent<UnityEngine.UI.GraphicRaycaster>();
            wsCanvas.worldCamera = Camera.main;

            // Scale so 1 Unity unit = ~1m; panel is 580x340 px
            wsGo.transform.localScale = new Vector3(0.001f, 0.001f, 0.001f);

            _exercisePanel = wsGo.AddComponent<ExerciseGifPanel>();
            wsGo.AddComponent<WorldSpaceFollow>();
        }

        private void OnSnapClicked()
        {
            // Dismiss suggestion chips when user takes action
            if (_chipDismissCoroutine != null) { StopCoroutine(_chipDismissCoroutine); _chipDismissCoroutine = null; }
            if (_suggestionChipRow != null) _suggestionChipRow.SetActive(false);

            if (webSocketManager == null)
            {
                webSocketManager = WebSocketManager.Instance != null ? WebSocketManager.Instance : FindFirstObjectByType<WebSocketManager>();
            }

            if (webSocketManager == null)
            {
                SetStatus("WebSocketManager not found.");
                _responseText.text = "Add NeuroGuideManager/WebSocketManager to the scene.";
                return;
            }

            if (!webSocketManager.IsConnected)
            {
                SetStatus("Backend disconnected.");
                _responseText.text = $"Cannot send snapshot. Check backend and URL: {webSocketManager.ServerUrl}";
                return;
            }

            if (cameraCapture == null)
            {
                SetStatus("ARCameraCapture not found in scene.");
                return;
            }

            SetStatusProcessing("Analyzing scene");
            SetImuStreamingPaused(true, "snapshot request");
            SetPromptInteraction(false);
            _responseText.text = "Sending snapshot to vision model...";
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
            SetImuStreamingPaused(false, "snapshot send failed");
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

            // Dismiss suggestion chips when user sends a message
            if (_chipDismissCoroutine != null) { StopCoroutine(_chipDismissCoroutine); _chipDismissCoroutine = null; }
            if (_suggestionChipRow != null) _suggestionChipRow.SetActive(false);

            SetStatusProcessing("Processing prompt");
            SetImuStreamingPaused(true, "prompt request");
            _responseText.text = "Waiting for AI response...";
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

        private void OnCompleteStepClicked()
        {
            SendStepControl("complete");
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
            if (!isConnected)
            {
                SetImuStreamingPaused(false, "websocket disconnected");
            }

            if (isConnected)
                SetStatus("Connected. Tap Snap to analyze the scene.", ColStatusOk);
            else
                SetStatus("Disconnected from backend.", ColStatusError);
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
                    HandleSnapshotResult(payload);
                    break;
                case "prompt_response":
                    HandlePromptResponse(payload);
                    break;
                case "step_update":
                    HandleStepUpdate(payload);
                    break;
                case "guidance":
                    HandleGuidanceMessage(payload);
                    break;
                case "yolo_machine_suggestion":
                    HandleMachineSuggestion(payload);
                    break;
                case "exercise_data":
                    HandleExerciseData(payload);
                    break;
                case "persona_ack":
                    string pName = payload.Value<string>("persona") ?? string.Empty;
                    SetStatus($"Persona: {pName.Replace('_', ' ')} active", ColStatusOk);
                    break;
                case "error":
                    Debug.LogError($"[DEBUG] OnMessageReceived: Backend error: {payload.Value<string>("message")}");
                    SetImuStreamingPaused(false, "backend error");
                    SetStatus(payload.Value<string>("message") ?? "Backend error.", ColStatusError);
                    StopDotsAnimation();
                    SetPromptInteraction(true);
                    break;
                case "imu_ack":
                    break;
            }
        }

        private void HandleSnapshotResult(JObject payload)
        {
            string sceneSummary  = payload.Value<string>("scene_summary")  ?? "Scene analyzed.";
            string responseText  = payload.Value<string>("response_text")  ?? string.Empty;
            string userMessage   = payload.Value<string>("user_message")   ?? "Scene analyzed.";
            string instruction   = payload.Value<string>("instruction_text") ?? string.Empty;
            string coachNote     = payload.Value<string>("coach_note")     ?? string.Empty;
            JArray suggested     = payload.Value<JArray>("suggested_queries");
            JObject stepGuidance = payload.Value<JObject>("step_guidance");
            _lastStepGuidance    = stepGuidance;
            string stepBlock     = BuildStepSummary(stepGuidance);

            // Build display text — clean, coach-voice order
            var sb = new System.Text.StringBuilder();
            // Prefer response_text (coach reply) over the generic user_message
            string mainText = !string.IsNullOrWhiteSpace(responseText) ? responseText : userMessage;
            sb.Append(mainText);
            if (!string.IsNullOrWhiteSpace(instruction) && instruction != mainText)
            {
                sb.Append("\n\n➤ ").Append(instruction);
            }
            if (!string.IsNullOrWhiteSpace(coachNote))
            {
                sb.Append("\n\n💧 ").Append(coachNote);
            }
            if (!string.IsNullOrWhiteSpace(stepBlock))
            {
                sb.Append(stepBlock);
            }

            StopDotsAnimation();
            SetStatus("Coach ready.", ColStatusOk);
            _responseText.text = sb.ToString();

            // Update suggestion chips from AI-provided queries
            if (suggested != null && suggested.Count > 0)
            {
                string[] chips = suggested.ToObject<string[]>();
                ShowSuggestionChips(chips);
            }

            Canvas.ForceUpdateCanvases();
            if (_responseScroll != null) _responseScroll.verticalNormalizedPosition = 1f;
            SetImuStreamingPaused(false, "snapshot response received");
            SetPromptInteraction(true);
            UpdateStepButtonState(true);
        }

        private void HandlePromptResponse(JObject payload)
        {
            string responseText  = payload.Value<string>("response_text")
                                ?? payload.Value<string>("instruction_text")
                                ?? "Response ready.";
            string coachNote     = payload.Value<string>("coach_note") ?? string.Empty;
            JArray suggested     = payload.Value<JArray>("suggested_queries");
            JObject stepGuidance = payload.Value<JObject>("step_guidance");
            _lastStepGuidance    = stepGuidance;
            string stepBlock     = BuildStepSummary(stepGuidance);
            string task          = payload.Value<string>("task") ?? "assistant";

            var sb = new System.Text.StringBuilder(responseText);
            if (!string.IsNullOrWhiteSpace(coachNote))
                sb.Append("\n\n💧 ").Append(coachNote);
            if (!string.IsNullOrWhiteSpace(stepBlock))
                sb.Append(stepBlock);

            StopDotsAnimation();
            SetStatus("Coach ready.", ColStatusOk);
            _responseText.text = sb.ToString();

            // Show AI-suggested follow-up chips
            if (suggested != null && suggested.Count > 0)
                ShowSuggestionChips(suggested.ToObject<string[]>());

            Canvas.ForceUpdateCanvases();
            if (_responseScroll != null) _responseScroll.verticalNormalizedPosition = 1f;
            SetImuStreamingPaused(false, "prompt response received");
            SetPromptInteraction(true);
            UpdateStepButtonState(true);
        }

        private void HandleMachineSuggestion(JObject payload)
        {
            string label       = payload.Value<string>("display_name") ?? "Machine";
            JArray suggestions = payload.Value<JArray>("suggestions");
            if (suggestions == null || suggestions.Count == 0) return;

            // Show popup label
            if (_machinePopupText != null) _machinePopupText.text = $"🏋️ {label} detected";
            if (_machinePopup != null)     _machinePopup.SetActive(true);

            // Show suggestion chips
            ShowSuggestionChips(suggestions.ToObject<string[]>());

            // Auto-dismiss popup after 10s
            if (_popupDismissCoroutine != null) StopCoroutine(_popupDismissCoroutine);
            _popupDismissCoroutine = StartCoroutine(DismissPopupAfterDelay(10f));
        }

        private void HandleExerciseData(JObject payload)
        {
            JArray exercisesArr = payload.Value<JArray>("exercises");
            if (exercisesArr == null || _exercisePanel == null) return;

            var list = new List<Dictionary<string, object>>();
            foreach (var token in exercisesArr)
            {
                if (token is Newtonsoft.Json.Linq.JObject exObj)
                {
                    var dict = new Dictionary<string, object>();
                    foreach (var prop in exObj.Properties())
                    {
                        if (prop.Value is Newtonsoft.Json.Linq.JArray arr)
                            dict[prop.Name] = arr.ToObject<List<object>>();
                        else
                            dict[prop.Name] = prop.Value?.ToString() ?? "";
                    }
                    list.Add(dict);
                }
            }
            if (list.Count > 0)
                _exercisePanel.Show(list);
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
            UpdateStepButtonState(true);
        }

        private void SetImuStreamingPaused(bool paused, string reason)
        {
            if (imuSensorStreamer == null)
            {
                imuSensorStreamer = FindFirstObjectByType<IMUSensorStreamer>();
            }

            if (imuSensorStreamer == null)
            {
                return;
            }

            if (imuSensorStreamer.StreamingPaused == paused)
            {
                return;
            }

            imuSensorStreamer.SetStreamingPaused(paused);
            Debug.Log($"[DEBUG] IMU streaming {(paused ? "paused" : "resumed")}: {reason}");
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
            bool isComplete = stepGuidance.Value<bool?>("is_complete") ?? false;

            int completedCount = 0;
            JArray completedArray = stepGuidance.Value<JArray>("completed_steps");
            if (completedArray != null)
            {
                completedCount = completedArray
                    .Values<int>()
                    .Distinct()
                    .Count(value => value >= 1 && value <= totalSteps);
            }

            string currentInstruction = string.Empty;
            JArray steps = stepGuidance.Value<JArray>("steps");
            if (steps != null && steps.Count >= currentStep)
            {
                JObject step = steps[currentStep - 1] as JObject;
                currentInstruction = step?.Value<string>("instruction") ?? string.Empty;
            }

            if (string.IsNullOrWhiteSpace(currentInstruction))
            {
                return isComplete
                    ? $"\n\nGuide: {title} | Completed {completedCount}/{totalSteps}"
                    : $"\n\nGuide: {title} | Step {currentStep}/{totalSteps} | Done {completedCount}/{totalSteps}";
            }

            return isComplete
                ? $"\n\nGuide: {title} | Completed {completedCount}/{totalSteps}\nAll steps completed."
                : $"\n\nGuide: {title} | Step {currentStep}/{totalSteps} | Done {completedCount}/{totalSteps}\nCurrent step: {currentInstruction}";
        }

        private void SetStatus(string message, Color? color = null)
        {
            if (_statusText == null) return;
            _statusText.text = message;
            _statusText.color = color ?? ColStatusInfo;
        }

        private void SetStatusProcessing(string message)
        {
            SetStatus(message, ColStatusWarn);
            if (_dotsCoroutine != null) StopCoroutine(_dotsCoroutine);
            _dotsCoroutine = StartCoroutine(AnimateDots(message));
        }

        private IEnumerator AnimateDots(string baseText)
        {
            string[] dots = { ".", "..", "..." };
            int i = 0;
            while (true)
            {
                if (_statusText != null) _statusText.text = baseText + dots[i % 3];
                i++;
                yield return new WaitForSeconds(0.5f);
            }
        }

        private void StopDotsAnimation()
        {
            if (_dotsCoroutine != null) { StopCoroutine(_dotsCoroutine); _dotsCoroutine = null; }
        }

        private void SetPromptInteraction(bool isEnabled)
        {
            if (_promptInput != null)
            {
                _promptInput.interactable = isEnabled;
                _promptInput.readOnly = !isEnabled;
                // Guard: EventSystem.current is null for the first frame on Android cold start.
                // Without this check, Select() / ActivateInputField() throw NullReferenceException
                // internally, which silently crashes the UI build coroutine.
                if (isEnabled && EventSystem.current != null)
                {
                    EventSystem.current.SetSelectedGameObject(null);
                    EventSystem.current.SetSelectedGameObject(_promptInput.gameObject);
                    _promptInput.Select();
                    _promptInput.ActivateInputField();
                }
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

            if (_completeStepButton != null)
            {
                _completeStepButton.interactable = isEnabled;
            }

            UpdateStepButtonState(isEnabled);
        }

        private void UpdateStepButtonState(bool isEnabled)
        {
            if (_lastStepGuidance == null)
            {
                if (_prevStepButton != null)
                {
                    _prevStepButton.interactable = false;
                }

                if (_nextStepButton != null)
                {
                    _nextStepButton.interactable = false;
                }

                if (_completeStepButton != null)
                {
                    _completeStepButton.interactable = false;
                }

                return;
            }

            int currentStep = Mathf.Max(1, _lastStepGuidance.Value<int?>("current_step") ?? 1);
            int totalSteps = Mathf.Max(1, _lastStepGuidance.Value<int?>("total_steps") ?? 1);
            bool isComplete = _lastStepGuidance.Value<bool?>("is_complete") ?? false;

            if (_prevStepButton != null)
            {
                _prevStepButton.interactable = isEnabled && currentStep > 1;
            }

            if (_nextStepButton != null)
            {
                _nextStepButton.interactable = isEnabled && !isComplete && currentStep < totalSteps;
            }

            if (_completeStepButton != null)
            {
                _completeStepButton.interactable = isEnabled && !isComplete;
            }
        }

        private void EnsureEventSystem()
        {
            if (EventSystem.current != null) return;
            var go = new GameObject("EventSystem", typeof(EventSystem), typeof(StandaloneInputModule));
            DontDestroyOnLoad(go);
        }

        // ── Persona ─────────────────────────────────────────────────────────
        private void OnPersonaClicked(string personaId)
        {
            if (webSocketManager == null || !webSocketManager.IsConnected) return;
            _activePersona = personaId;
            Color active = ColPersonaActive, inactive = ColPersonaInactive;
            if (_personaGymBtn   != null) _personaGymBtn.GetComponent<Image>().color   = personaId == "gym_trainer"      ? active : inactive;
            if (_personaChefBtn  != null) _personaChefBtn.GetComponent<Image>().color  = personaId == "chef"              ? active : inactive;
            if (_personaPhysioBtn!= null) _personaPhysioBtn.GetComponent<Image>().color= personaId == "physiotherapist"  ? active : inactive;
            _ = webSocketManager.SendJsonAsync(new Dictionary<string, object>
            {
                ["type"]    = "set_persona",
                ["persona"] = personaId,
            });
            Debug.Log($"[Persona] Switched to: {personaId}");
        }

        // ── YOLO machine popup ──────────────────────────────────────────────
        private void HandleGuidanceMessage(JObject payload)
        {
            JObject alert = payload.Value<JObject>("yolo_machine_alert");
            if (alert == null) return;

            string label       = alert.Value<string>("label")        ?? string.Empty;
            string displayName = alert.Value<string>("display_name") ?? label;
            float  cx          = alert.Value<float?>("cx_norm")      ?? 0.5f;
            float  cy          = alert.Value<float?>("cy_norm")      ?? 0.5f;
            JArray bboxArr     = alert.Value<JArray>("bbox_norm");

            // Save YOLO coords for AR placement
            _lastDetectedLabel  = label;
            _lastDetectedCxNorm = cx;
            _lastDetectedCyNorm = cy;
            if (bboxArr != null && bboxArr.Count == 4)
            {
                _lastDetectedBbox = new float[4];
                for (int i = 0; i < 4; i++) _lastDetectedBbox[i] = bboxArr[i].Value<float>();
            }
            Debug.Log($"[YOLO] Saved: {label} cx={cx:F3} cy={cy:F3} bbox=[{(_lastDetectedBbox != null ? string.Join(",", _lastDetectedBbox) : "none")}]");

            ShowMachinePopup(displayName);
        }

        private void ShowMachinePopup(string machineName)
        {
            if (_machinePopup == null || machineName == _lastMachineLabel) return;
            _lastMachineLabel = machineName;
            if (_machinePopupText != null)
                _machinePopupText.text = $"\u26A1 {machineName} detected!\nTap \"Guide Me\" for step-by-step instructions.";
            _machinePopup.SetActive(true);
            if (_popupDismissCoroutine != null) StopCoroutine(_popupDismissCoroutine);
            _popupDismissCoroutine = StartCoroutine(DismissPopupAfter(7f));

            // Notify the persistent Coach HUD so it pulses the top banner
            NeuroGuideXR.UI.CoachHUD.Instance?.ShowMachineDetected(machineName, 7f);
        }

        private IEnumerator DismissPopupAfter(float seconds)
        {
            yield return new WaitForSeconds(seconds);
            if (_machinePopup != null) _machinePopup.SetActive(false);
            _lastMachineLabel = string.Empty;
        }

        // Alias used by HandleMachineSuggestion
        private IEnumerator DismissPopupAfterDelay(float seconds) => DismissPopupAfter(seconds);

        // ── Suggestion chips ──────────────────────────────────────────────────

        private void ShowSuggestionChips(string[] labels)
        {
            if (_suggestionChipRow == null) return;
            int count = Mathf.Min(labels?.Length ?? 0, 3);
            if (count == 0) { _suggestionChipRow.SetActive(false); return; }

            _suggestionChipRow.SetActive(true);
            for (int i = 0; i < 3; i++)
            {
                if (i < count)
                {
                    _chipButtons[i].gameObject.SetActive(true);
                    if (_chipTexts[i] != null) _chipTexts[i].text = labels[i];
                }
                else
                {
                    _chipButtons[i].gameObject.SetActive(false);
                }
            }

            // Auto-dismiss chips after 12 seconds
            if (_chipDismissCoroutine != null) StopCoroutine(_chipDismissCoroutine);
            _chipDismissCoroutine = StartCoroutine(DismissChipsAfterDelay(12f));
        }

        private IEnumerator DismissChipsAfterDelay(float seconds)
        {
            yield return new WaitForSeconds(seconds);
            if (_suggestionChipRow != null) _suggestionChipRow.SetActive(false);
            _chipDismissCoroutine = null;
        }

        private void OnChipClicked(int idx)
        {
            if (_chipTexts[idx] == null) return;
            string text = _chipTexts[idx].text;
            if (string.IsNullOrWhiteSpace(text)) return;

            // Inject chip text as prompt and send
            if (_promptInput != null) _promptInput.text = text;
            // Hide chips immediately
            if (_suggestionChipRow != null) _suggestionChipRow.SetActive(false);
            OnAskClicked();
        }

        private void OnGuideMeClicked()
        {
            if (_machinePopup != null) _machinePopup.SetActive(false);
            if (_popupDismissCoroutine != null) { StopCoroutine(_popupDismissCoroutine); _popupDismissCoroutine = null; }
            if (!string.IsNullOrEmpty(_lastMachineLabel) && _promptInput != null)
                _promptInput.text = $"Can you guide me with the correct steps for using the {_lastMachineLabel}?";
            _lastMachineLabel = string.Empty;
            OnAskClicked();
        }

        // ── ScrollRect factory ────────────────────────────────────────────────
        private ScrollRect CreateScrollView(string name, Transform parent, Vector2 anchoredPosition, Vector2 sizeDelta)
        {
            // Viewport
            var root = new GameObject(name, typeof(RectTransform), typeof(Image), typeof(ScrollRect));
            root.transform.SetParent(parent, false);
            var rootRect = root.GetComponent<RectTransform>();
            rootRect.anchorMin = new Vector2(0f, 1f);
            rootRect.anchorMax = new Vector2(0f, 1f);
            rootRect.pivot     = new Vector2(0f, 1f);
            rootRect.anchoredPosition = anchoredPosition;
            rootRect.sizeDelta = sizeDelta;
            root.GetComponent<Image>().color = new Color(1f, 1f, 1f, 0.04f);

            // Content
            var contentGo = new GameObject("Content", typeof(RectTransform));
            contentGo.transform.SetParent(root.transform, false);
            var contentRect = contentGo.GetComponent<RectTransform>();
            contentRect.anchorMin = new Vector2(0f, 1f);
            contentRect.anchorMax = new Vector2(1f, 1f);
            contentRect.pivot     = new Vector2(0f, 1f);
            contentRect.offsetMin = Vector2.zero;
            contentRect.offsetMax = Vector2.zero;

            // Text inside content
            var textGo = new GameObject("Text", typeof(RectTransform), typeof(Text));
            textGo.transform.SetParent(contentGo.transform, false);
            var textRect = textGo.GetComponent<RectTransform>();
            textRect.anchorMin = new Vector2(0f, 1f);
            textRect.anchorMax = new Vector2(1f, 1f);
            textRect.pivot     = new Vector2(0f, 1f);
            textRect.offsetMin = new Vector2(8f, 0f);
            textRect.offsetMax = new Vector2(-8f, 0f);
            textRect.sizeDelta = new Vector2(-16f, 600f);

            var t = textGo.GetComponent<Text>();
            t.font                = _font;
            t.fontSize            = 20;
            t.color               = new Color(0.92f, 0.96f, 1f, 1f);
            t.alignment           = TextAnchor.UpperLeft;
            t.horizontalOverflow  = HorizontalWrapMode.Wrap;
            t.verticalOverflow    = VerticalWrapMode.Overflow;
            t.supportRichText     = true;
            t.text                = "Scene insights will appear here.";

            var scroll = root.GetComponent<ScrollRect>();
            scroll.content          = contentRect;
            scroll.horizontal       = false;
            scroll.vertical         = true;
            scroll.scrollSensitivity = 30f;
            scroll.movementType     = ScrollRect.MovementType.Clamped;
            return scroll;
        }

        // ── Original UI helpers (unchanged) ──────────────────────────────────

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
            text.raycastTarget = false;
            placeholder.raycastTarget = false;
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
