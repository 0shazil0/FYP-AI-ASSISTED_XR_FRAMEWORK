// Assets/Scripts/Copilot/CopilotStepController.cs
// Drives the step-by-step guided flow for the Software UI Assistance mode.
// Receives copilot_steps, screen_frame, and step_verification from the backend.
// Coordinates: VirtualScreenManager + CopilotOverlayManager + CopilotUI
//              + CopilotStateMachine + VoiceInputManager + TTSOutputManager

using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using NeuroGuideXR.UI;
using NeuroGuideXR.Core;

namespace NeuroGuideXR.Copilot
{
    [Serializable]
    public sealed class CopilotStep
    {
        public string action;    // "click", "type", etc.
        public string label;     // UI element label
        public float  x;         // pixel X center on source screen
        public float  y;         // pixel Y center on source screen
        public float  width;
        public float  height;
        public bool   resolved;  // false = element not found
        public string error;     // optional error string
        public string value;     // text to type (for "type" action)
        public string tts_text;  // coaching sentence to speak aloud
    }

    public sealed class CopilotStepController : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("Backend")]
        [SerializeField] private CopilotWebSocketClient wsClient;

        [Header("AR Components")]
        [SerializeField] private VirtualScreenManager  screenManager;
        [SerializeField] private CopilotOverlayManager overlayManager;

        [Header("UI")]
        [SerializeField] private CopilotUI copilotUI;

        [Header("Voice & TTS")]
        [Tooltip("VoiceInputManager on the scene. Voice result auto-submits as query.")]
        [SerializeField] private VoiceInputManager  voiceInput;
        [Tooltip("TTSOutputManager to speak coaching sentences.")]
        [SerializeField] private TTSOutputManager   ttsOutput;

        [Header("State Machine")]
        [SerializeField] private CopilotStateMachine stateMachine;

        [Header("Reference Resolution")]
        [Tooltip("Source screen width (default 1920 — set in backend .env).")]
        [SerializeField] private float referenceW = 1920f;
        [Tooltip("Source screen height (default 1080).")]
        [SerializeField] private float referenceH = 1080f;

        // ----------------------------------------------------------------
        // State
        // ----------------------------------------------------------------
        private readonly List<CopilotStep> _steps = new();
        private int    _currentStep  = 0;
        private bool   _hasSteps     = false;
        private string _currentQuery = "";
        private string _currentApp   = "Word";

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------
        private void OnEnable()
        {
            if (wsClient != null)
            {
                wsClient.OnMessageReceived       -= HandleMessage;
                wsClient.OnMessageReceived       += HandleMessage;
                wsClient.OnBinaryMessageReceived -= OnScreenFrame;
                wsClient.OnBinaryMessageReceived += OnScreenFrame;
                wsClient.OnConnectionStateChanged -= HandleConnState;
                wsClient.OnConnectionStateChanged += HandleConnState;
            }

            // Voice auto-submit: recognized speech goes straight to query
            if (voiceInput != null)
            {
                voiceInput.OnResultReceived   -= OnVoiceResult;
                voiceInput.OnResultReceived   += OnVoiceResult;
                voiceInput.OnListeningStarted -= OnVoiceStart;
                voiceInput.OnListeningStarted += OnVoiceStart;
                voiceInput.OnListeningStopped -= OnVoiceStop;
                voiceInput.OnListeningStopped += OnVoiceStop;
                voiceInput.OnPartialResult    -= OnVoicePartial;
                voiceInput.OnPartialResult    += OnVoicePartial;
            }

            // State machine events → drive UI
            if (stateMachine != null)
            {
                stateMachine.OnStateChanged -= OnStateChanged;
                stateMachine.OnStateChanged += OnStateChanged;
                stateMachine.OnErrorEntered -= OnError;
                stateMachine.OnErrorEntered += OnError;
            }
        }

        private void OnDisable()
        {
            if (wsClient != null)
            {
                wsClient.OnMessageReceived        -= HandleMessage;
                wsClient.OnBinaryMessageReceived  -= OnScreenFrame;
                wsClient.OnConnectionStateChanged -= HandleConnState;
            }
            if (voiceInput != null)
            {
                voiceInput.OnResultReceived   -= OnVoiceResult;
                voiceInput.OnListeningStarted -= OnVoiceStart;
                voiceInput.OnListeningStopped -= OnVoiceStop;
                voiceInput.OnPartialResult    -= OnVoicePartial;
            }
            if (stateMachine != null)
            {
                stateMachine.OnStateChanged -= OnStateChanged;
                stateMachine.OnErrorEntered -= OnError;
            }
        }

        // ----------------------------------------------------------------
        // Public API — called by CopilotUI buttons
        // ----------------------------------------------------------------

        /// <summary>
        /// Send a text query to the backend (called by input field submit or voice auto-submit).
        /// </summary>
        public void SendQuery(string query, string appName = "")
        {
            if (string.IsNullOrWhiteSpace(query)) return;

            if (wsClient == null || !wsClient.IsConnected)
            {
                copilotUI?.SetStatus("Not connected to backend.");
                return;
            }

            if (!string.IsNullOrEmpty(appName)) _currentApp = appName;
            _currentQuery = query;
            _hasSteps     = false;
            overlayManager?.ClearAll();

            stateMachine?.SetState(CopilotState.Querying);

            wsClient.SendJson(new
            {
                type  = "query",
                query = query,
                app   = _currentApp,
            });
        }

        /// <summary>Start voice recognition. Result will auto-submit as a query.</summary>
        public void StartVoiceInput()
        {
            if (stateMachine != null && stateMachine.IsBusy) return;
            stateMachine?.SetState(CopilotState.Listening);
            voiceInput?.StartListening();
        }

        // Left empty — frame pushing is now handled by the backend push loop.
        public void RequestScreenFrame() { }

        /// <summary>User confirms the current step is done → send step_done to backend.</summary>
        public void NextStep()
        {
            if (!_hasSteps || _steps.Count == 0) return;

            stateMachine?.OnStepDoneTapped(_currentStep);
            wsClient?.SendJson(new { type = "step_done", step_index = _currentStep });
        }

        public void PrevStep()
        {
            if (!_hasSteps || _currentStep <= 0) return;
            _currentStep--;
            ShowStep(_currentStep);
        }

        public void ResetSession()
        {
            _steps.Clear();
            _currentStep = 0;
            _hasSteps    = false;
            _currentQuery = "";
            overlayManager?.ClearAll();
            ttsOutput?.Stop();
            stateMachine?.Reset();
        }

        // ----------------------------------------------------------------
        // Voice callbacks
        // ----------------------------------------------------------------
        private void OnVoiceResult(string text)
        {
            Debug.Log($"[CopilotStep] Voice result: '{text}' → populate textbox");
            if (copilotUI != null)
            {
                copilotUI.SetQueryText(text);
                copilotUI.SetStatus("Voice recognized. Tap Ask AI to send.");
            }
        }

        private void OnVoiceStart()
        {
            copilotUI?.SetStatus("Listening… speak your question.");
        }

        private void OnVoiceStop()
        {
            // Status will be updated by Querying state transition or voice result
        }

        private void OnVoicePartial(string partial)
        {
            copilotUI?.SetStatus($"…{partial}");
        }

        // ----------------------------------------------------------------
        // State machine callbacks
        // ----------------------------------------------------------------
        private void OnStateChanged(CopilotState prev, CopilotState next)
        {
            switch (next)
            {
                case CopilotState.Idle:
                    copilotUI?.SetStatus("Ready. Tap mic or type a question.");
                    copilotUI?.SetStepControls(false);
                    break;

                case CopilotState.Listening:
                    copilotUI?.SetStatus("Listening…");
                    break;

                case CopilotState.Querying:
                    copilotUI?.SetStatus("Asking AI…");
                    copilotUI?.SetStepControls(false);
                    break;

                case CopilotState.Guiding:
                    copilotUI?.SetStepControls(true);
                    break;

                case CopilotState.Verifying:
                    copilotUI?.SetStatus("Checking step…");
                    break;

                case CopilotState.Done:
                    copilotUI?.SetStatus("✅ All steps complete!");
                    copilotUI?.SetInstruction("Great work — task finished!");
                    copilotUI?.SetStepControls(false);
                    overlayManager?.ClearCurrentOverlay();
                    ttsOutput?.Speak("Excellent! You have completed all the steps.");
                    break;

                case CopilotState.Error:
                    copilotUI?.SetStepControls(false);
                    break;
            }
        }

        private void OnError(string message)
        {
            copilotUI?.SetStatus($"Error: {message}");
        }

        // ----------------------------------------------------------------
        // Backend message handling
        // ----------------------------------------------------------------
        private void HandleMessage(string json)
        {
            JObject data;
            try { data = JObject.Parse(json); }
            catch { Debug.LogWarning("[CopilotStep] Failed to parse JSON"); return; }

            string type = data["type"]?.ToString() ?? "";

            switch (type)
            {
                case "copilot_steps":
                    OnCopilotSteps(data);
                    break;

                case "screen_frame":
                    OnScreenFrameText(data);
                    break;

                case "step_verification":
                    OnStepVerification(data);
                    break;

                // Legacy: backend may still send step_ack if verification is bypassed
                case "step_ack":
                    int ackIdx = data["step_index"]?.ToObject<int>() ?? _currentStep;
                    AdvanceAfterVerification(ackIdx, passed: true);
                    break;

                case "error":
                    string msg = data["message"]?.ToString() ?? "Backend error.";
                    Debug.LogWarning($"[CopilotStep] Backend error: {msg}");
                    stateMachine?.SetError(msg);
                    break;

                case "pong":
                    break;
            }
        }

        private void OnCopilotSteps(JObject data)
        {
            _steps.Clear();
            _currentStep = 0;

            var arr = data["steps"] as JArray;
            if (arr == null || arr.Count == 0)
            {
                stateMachine?.SetError("AI returned no steps. Try rephrasing your question.");
                return;
            }

            foreach (var item in arr)
            {
                _steps.Add(new CopilotStep
                {
                    action   = item["action"]?.ToString()             ?? "click",
                    label    = item["label"]?.ToString()              ?? item["target"]?.ToString() ?? "",
                    x        = item["x"]?.ToObject<float>()           ?? -1f,
                    y        = item["y"]?.ToObject<float>()           ?? -1f,
                    width    = item["width"]?.ToObject<float>()       ?? 0f,
                    height   = item["height"]?.ToObject<float>()      ?? 0f,
                    resolved = item["resolved"]?.ToObject<bool>()     ?? (item["x"] != null),
                    error    = item["error"]?.ToString()              ?? "",
                    value    = item["value"]?.ToString()              ?? "",
                    tts_text = item["tts_text"]?.ToString()           ?? "",
                });
            }

            _hasSteps = true;
            stateMachine?.OnStepsReceived(_steps.Count);
            ShowStep(0);
        }

        private void OnStepVerification(JObject data)
        {
            int  stepIdx    = data["step_index"]?.ToObject<int>() ?? _currentStep;
            bool passed     = data["passed"]?.ToObject<bool>()    ?? true;
            string ttsTxt   = data["tts_text"]?.ToString()        ?? "";
            float diffScore = data["diff_score"]?.ToObject<float>()     ?? 0f;

            Debug.Log($"[CopilotStep] step_verification step={stepIdx} passed={passed} diff={diffScore:F3}");

            // Speak the coaching sentence (pass confirm or retry instruction)
            if (!string.IsNullOrEmpty(ttsTxt))
                ttsOutput?.Speak(ttsTxt);

            // Update next step coordinates if passed and returned by the backend
            if (passed && data["next_step"] != null && data["next_step"].Type != JTokenType.Null)
            {
                int nextIdx = stepIdx + 1;
                if (nextIdx < _steps.Count)
                {
                    var nextStepData = data["next_step"];
                    if (nextStepData != null && nextStepData.HasValues)
                    {
                        _steps[nextIdx].x = nextStepData["x"]?.ToObject<float>() ?? -1f;
                        _steps[nextIdx].y = nextStepData["y"]?.ToObject<float>() ?? -1f;
                        _steps[nextIdx].width = nextStepData["width"]?.ToObject<float>() ?? 0f;
                        _steps[nextIdx].height = nextStepData["height"]?.ToObject<float>() ?? 0f;
                        _steps[nextIdx].resolved = nextStepData["resolved"]?.ToObject<bool>() ?? true;
                        Debug.Log($"[CopilotStep] Dynamically resolved next step {nextIdx} coordinates: ({_steps[nextIdx].x:F1}, {_steps[nextIdx].y:F1})");
                    }
                }
            }

            stateMachine?.OnVerificationResult(stepIdx, passed);
            AdvanceAfterVerification(stepIdx, passed);
        }

        private void AdvanceAfterVerification(int stepIdx, bool passed)
        {
            if (passed)
            {
                if (stepIdx < _steps.Count - 1)
                {
                    _currentStep = stepIdx + 1;
                    ShowStep(_currentStep);
                }
                // else: Done state is set by stateMachine.OnVerificationResult
            }
            else
            {
                // Stay on same step — re-show it
                ShowStep(_currentStep);
            }
        }

        private void OnScreenFrame(byte[] bytes)
        {
            if (bytes != null && bytes.Length > 0)
                screenManager?.ApplyScreenFrame(bytes);
        }

        private void OnScreenFrameText(JObject data)
        {
            string imgB64 = data["image"]?.ToString() ?? "";
            if (string.IsNullOrEmpty(imgB64)) return;

            try
            {
                if (data["width"]  != null) referenceW = Mathf.Max(1f, data["width"]!.ToObject<float>());
                if (data["height"] != null) referenceH = Mathf.Max(1f, data["height"]!.ToObject<float>());
                byte[] bytes = Convert.FromBase64String(imgB64);
                OnScreenFrame(bytes);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[CopilotStep] screen_frame decode failed: {e.Message}");
            }
        }

        private void HandleConnState(bool connected)
        {
            if (connected)
                copilotUI?.SetStatus("Connected. Screen linked.");
            else
            {
                copilotUI?.SetStatus("Disconnected from backend.");
                stateMachine?.SetState(CopilotState.Idle);
            }
        }

        // ----------------------------------------------------------------
        // Step Display
        // ----------------------------------------------------------------
        private void ShowStep(int index)
        {
            if (index < 0 || index >= _steps.Count) return;
            CopilotStep step = _steps[index];

            // UI counters
            copilotUI?.SetStatus($"Step {index + 1} / {_steps.Count}");
            copilotUI?.UpdateStepCounter(index, _steps.Count);
            string instruction = step.resolved
                ? $"{step.action.ToUpper()} → {step.label}"
                : $"⚠ Not found: {step.label}";
            if (!string.IsNullOrEmpty(step.value))
                instruction += $"  (type: \"{step.value}\")";
            copilotUI?.SetInstruction(instruction);

            // AR overlay
            if (step.resolved && step.x >= 0)
                overlayManager?.PlaceOverlay(step.x, step.y, referenceW, referenceH, instruction, index, _steps.Count);
            else
            {
                overlayManager?.ClearCurrentOverlay();
                if (!string.IsNullOrEmpty(step.error))
                    copilotUI?.SetStatus($"Step {index + 1}: {step.error}");
            }

            // Nav buttons
            copilotUI?.UpdateNavButtons(index > 0, index < _steps.Count - 1);

            // ── Speak coaching TTS ────────────────────────────────────────
            // Use tts_text from backend if available; fallback to generated instruction
            string toSpeak = !string.IsNullOrEmpty(step.tts_text)
                ? step.tts_text
                : instruction;
            ttsOutput?.Speak(toSpeak);
        }
    }
}
