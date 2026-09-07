// Assets/Scripts/UI/CopilotUI.cs
// Programmatic UI panel for the CopilotAR scene.
// Compact bottom-anchored UI: mic button, query input, app selector,
// Ask button, step counter, nav buttons, status bar.
// Wires into CopilotStateMachine for reactive visual state changes.

using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using NeuroGuideXR.Copilot;

namespace NeuroGuideXR.UI
{
    public sealed class CopilotUI : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("References")]
        [SerializeField] private CopilotStepController stepController;
        [SerializeField] private CopilotStateMachine   stateMachine;

        // ----------------------------------------------------------------
        // UI elements (built at runtime)
        // ----------------------------------------------------------------
        private Text       _statusText;
        private Text       _instructionText;
        private InputField _queryInput;
        private Button     _askButton;
        private Button     _micButton;
        private Text       _micLabel;
        private Button     _nextBtn;
        private Button     _prevBtn;
        private Button     _doneBtn;
        private Text       _appText;
        private GameObject _spinner;       // "Thinking..." animated dots
        private Text       _stepCounter;   // "2 / 5" shown in header

        private int    _currentAppIndex = 0;
        private bool   _micActive       = false;

        private static readonly string[] AppNames =
            { "Word", "Excel", "Notepad", "PowerPoint", "Chrome", "Power BI", "Custom App" };

        // Colour palette
        private static readonly Color ColDark   = new Color(0.04f, 0.06f, 0.12f, 0.93f);
        private static readonly Color ColMid    = new Color(0.12f, 0.15f, 0.25f);
        private static readonly Color ColBlue   = new Color(0.12f, 0.52f, 0.96f);
        private static readonly Color ColGreen  = new Color(0.10f, 0.60f, 0.30f);
        private static readonly Color ColGrey   = new Color(0.20f, 0.20f, 0.30f);
        private static readonly Color ColRed    = new Color(0.70f, 0.10f, 0.10f);
        private static readonly Color ColOrange = new Color(0.85f, 0.45f, 0.05f);
        private static readonly Color ColGold   = new Color(0.80f, 0.65f, 0.05f);

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------
        private void Start()
        {
            BuildPanel();
        }

        private void OnEnable()
        {
            if (stateMachine != null)
            {
                stateMachine.OnStateChanged -= OnStateChanged;
                stateMachine.OnStateChanged += OnStateChanged;
            }
        }

        private void OnDisable()
        {
            if (stateMachine != null)
                stateMachine.OnStateChanged -= OnStateChanged;
        }

        // ----------------------------------------------------------------
        // Public API (called by CopilotStepController)
        // ----------------------------------------------------------------

        public void SetStatus(string msg)
        {
            if (_statusText) _statusText.text = msg;
        }

        public void SetQueryText(string text)
        {
            if (_queryInput) _queryInput.text = text;
        }

        public void SetInstruction(string msg)
        {
            if (_instructionText) _instructionText.text = msg;
        }

        public void SetStepControls(bool active)
        {
            if (_nextBtn) _nextBtn.interactable = active;
            if (_prevBtn) _prevBtn.interactable = active;
            if (_doneBtn) _doneBtn.interactable = active;
        }

        public void UpdateNavButtons(bool hasPrev, bool hasNext)
        {
            if (_prevBtn) _prevBtn.interactable = hasPrev;
            if (_nextBtn) _nextBtn.interactable = hasNext;
        }

        public void UpdateStepCounter(int current, int total)
        {
            if (_stepCounter) _stepCounter.text = total > 0 ? $"{current + 1} / {total}" : "";
        }

        /// <summary>Show/hide the mic button pulsing "listening" indicator.</summary>
        public void SetMicActive(bool active)
        {
            _micActive = active;
            if (_micButton)
            {
                var img = _micButton.GetComponent<Image>();
                if (img) img.color = active ? ColOrange : ColMid;
            }
            if (_micLabel) _micLabel.text = active ? "🎙 Stop" : "🎙 Mic";
        }

        // ----------------------------------------------------------------
        // State machine → UI reactions
        // ----------------------------------------------------------------
        private void OnStateChanged(CopilotState prev, CopilotState next)
        {
            // Spinner visibility
            bool spinning = next == CopilotState.Querying || next == CopilotState.Verifying;
            if (_spinner) _spinner.SetActive(spinning);

            // Mic button colour
            SetMicActive(next == CopilotState.Listening);

            // Ask button
            if (_askButton) _askButton.interactable = (next == CopilotState.Idle || next == CopilotState.Error);

            // Nav + Done buttons
            bool guiding = next == CopilotState.Guiding;
            if (_doneBtn) _doneBtn.interactable = guiding;

            // Status text colour
            if (_statusText)
            {
                _statusText.color = next switch
                {
                    CopilotState.Error     => ColRed,
                    CopilotState.Done      => ColGreen,
                    CopilotState.Listening => ColOrange,
                    CopilotState.Verifying => ColGold,
                    _                      => Color.white,
                };
            }
        }

        // ----------------------------------------------------------------
        // Button callbacks
        // ----------------------------------------------------------------
        private void OnCycleApp()
        {
            _currentAppIndex = (_currentAppIndex + 1) % AppNames.Length;
            if (_appText) _appText.text = "App: " + AppNames[_currentAppIndex];
        }

        private void OnAsk()
        {
            string query = _queryInput?.text?.Trim() ?? "";
            if (string.IsNullOrEmpty(query)) { SetStatus("Please type a question first."); return; }
            string appName = AppNames[_currentAppIndex];
            stepController?.SendQuery(query, appName);
        }

        private void OnMicTap()
        {
            if (_micActive)
                stepController?.ResetSession(); // tap again to cancel
            else
                stepController?.StartVoiceInput();
        }

        private void OnNext()  => stepController?.NextStep();
        private void OnPrev()  => stepController?.PrevStep();
        private void OnDone()  => stepController?.NextStep();   // "Done" is alias for step_done
        private void OnReset() => stepController?.ResetSession();
        private void OnBack()  => SceneManager.LoadScene(0);
        private void OnRefreshScreen() => stepController?.RequestScreenFrame();

        private void ReEnableAsk() { if (_askButton) _askButton.interactable = true; }

        // ----------------------------------------------------------------
        // UI Construction
        // ----------------------------------------------------------------
        private void BuildPanel()
        {
            // ── Canvas ──────────────────────────────────────────────────
            var canvasGo = new GameObject("CopilotCanvas", typeof(Canvas),
                                          typeof(CanvasScaler), typeof(GraphicRaycaster));
            var canvas = canvasGo.GetComponent<Canvas>();
            canvas.renderMode   = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 99;

            var scaler = canvasGo.GetComponent<CanvasScaler>();
            scaler.uiScaleMode         = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080, 1920);
            scaler.screenMatchMode     = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight  = 0.5f;

            var font = Resources.GetBuiltinResource<Font>("Arial.ttf");

            // ── Top Header bar (0.94 – 1.00) ────────────────────────────
            var backBtn = MakeButton("BackBtn", canvas.transform, "← Back", ColGrey, font, 28);
            SetAnchors(backBtn, new Vector2(0.02f, 0.94f), new Vector2(0.18f, 0.99f));
            backBtn.GetComponent<Button>().onClick.AddListener(OnBack);

            // Step counter (centre of header)
            var counterGo = MakeTextGo("StepCounter", canvas.transform, font, 32, ColGold);
            SetAnchors(counterGo, new Vector2(0.30f, 0.94f), new Vector2(0.70f, 0.99f));
            _stepCounter = counterGo.GetComponent<Text>();
            _stepCounter.alignment = TextAnchor.MiddleCenter;
            _stepCounter.text = "";

            // Status text (right of header)
            var statusGo = MakeTextGo("StatusText", canvas.transform, font, 26, Color.white);
            SetAnchors(statusGo, new Vector2(0.20f, 0.94f), new Vector2(0.80f, 0.99f));
            _statusText = statusGo.GetComponent<Text>();
            _statusText.alignment = TextAnchor.MiddleCenter;
            _statusText.text = "Initializing…";

            var resetBtn = MakeButton("ResetBtn", canvas.transform, "↺ Reset", ColGrey, font, 26);
            SetAnchors(resetBtn, new Vector2(0.82f, 0.94f), new Vector2(0.98f, 0.99f));
            resetBtn.GetComponent<Button>().onClick.AddListener(OnReset);

            // ── Instruction card (hovers above bottom panel) ────────────
            var instrCard = MakePanel("InstrCard", canvas.transform, new Color(0.05f, 0.08f, 0.15f, 0.88f));
            SetAnchors(instrCard, new Vector2(0.02f, 0.29f), new Vector2(0.98f, 0.40f));

            _instructionText = MakeTextGo("InstrText", instrCard.transform, font, 34,
                new Color(0.9f, 0.95f, 1f)).GetComponent<Text>();
            SetAnchors(_instructionText.gameObject, Vector2.zero, Vector2.one,
                new Vector2(16, 8), new Vector2(-16, -8));
            _instructionText.alignment = TextAnchor.MiddleLeft;
            _instructionText.text = "Ask a question to get started.";

            // ── Bottom action panel (0.00 – 0.28) ──────────────────────
            var bottomPanel = MakePanel("BottomPanel", canvas.transform, ColDark);
            SetAnchors(bottomPanel, Vector2.zero, new Vector2(1f, 0.28f));

            // Row 1: App selector
            var appGo = MakeButton("AppCycleBtn", bottomPanel.transform,
                "App: " + AppNames[0], ColMid, font, 28);
            SetAnchors(appGo, new Vector2(0.03f, 0.80f), new Vector2(0.97f, 0.94f));
            _appText = appGo.transform.Find("Label").GetComponent<Text>();
            _appText.alignment = TextAnchor.MiddleLeft;
            appGo.GetComponent<Button>().onClick.AddListener(OnCycleApp);

            // Row 2: Query input (left 80%) + Mic button (right 18%)
            var inputGo = new GameObject("QueryInput",
                typeof(RectTransform), typeof(Image), typeof(InputField));
            inputGo.transform.SetParent(bottomPanel.transform, false);
            SetAnchors(inputGo, new Vector2(0.03f, 0.60f), new Vector2(0.78f, 0.76f));
            inputGo.GetComponent<Image>().color = ColMid;
            _queryInput = inputGo.GetComponent<InputField>();
            _queryInput.textComponent = MakeSimpleText(inputGo.transform, font, 28, Color.white, "");
            _queryInput.placeholder   = MakeSimpleText(inputGo.transform, font, 28,
                new Color(0.5f, 0.5f, 0.6f), "How do I…?");
            // Auto-submit on end-edit
            _queryInput.onEndEdit.AddListener(text =>
            {
                if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
                    OnAsk();
            });

            // Mic button
            var micGo = MakeButton("MicBtn", bottomPanel.transform, "🎙 Mic", ColMid, font, 28);
            SetAnchors(micGo, new Vector2(0.80f, 0.60f), new Vector2(0.97f, 0.76f));
            _micButton = micGo.GetComponent<Button>();
            _micButton.onClick.AddListener(OnMicTap);
            _micLabel = micGo.transform.Find("Label").GetComponent<Text>();

            // Row 3: Ask button (left 78%) + spinner dots (right 20%)
            var askGo = MakeButton("AskBtn", bottomPanel.transform, "Ask AI 🎯", ColBlue, font, 34);
            SetAnchors(askGo, new Vector2(0.03f, 0.40f), new Vector2(0.78f, 0.56f));
            _askButton = askGo.GetComponent<Button>();
            _askButton.onClick.AddListener(OnAsk);

            // Spinner label ("…" shown when querying/verifying)
            var spinnerGo = MakeTextGo("Spinner", bottomPanel.transform, font, 36, ColGold);
            SetAnchors(spinnerGo, new Vector2(0.80f, 0.40f), new Vector2(0.97f, 0.56f));
            _spinner = spinnerGo;
            _spinner.GetComponent<Text>().text = "…";
            _spinner.SetActive(false);

            // Row 4: Prev / Done / Next
            var prevGo = MakeButton("PrevBtn", bottomPanel.transform, "◀ Prev", ColGrey, font, 30);
            SetAnchors(prevGo, new Vector2(0.03f, 0.05f), new Vector2(0.33f, 0.34f));
            _prevBtn = prevGo.GetComponent<Button>();
            _prevBtn.interactable = false;
            _prevBtn.onClick.AddListener(OnPrev);

            var doneGo = MakeButton("DoneBtn", bottomPanel.transform, "✔ Done", ColGreen, font, 30);
            SetAnchors(doneGo, new Vector2(0.36f, 0.05f), new Vector2(0.64f, 0.34f));
            _doneBtn = doneGo.GetComponent<Button>();
            _doneBtn.interactable = false;
            _doneBtn.onClick.AddListener(OnDone);

            var nextGo = MakeButton("NextBtn", bottomPanel.transform, "Next ▶", ColGreen, font, 30);
            SetAnchors(nextGo, new Vector2(0.67f, 0.05f), new Vector2(0.97f, 0.34f));
            _nextBtn = nextGo.GetComponent<Button>();
            _nextBtn.interactable = false;
            _nextBtn.onClick.AddListener(OnNext);
        }

        // ----------------------------------------------------------------
        // UI Factory helpers
        // ----------------------------------------------------------------
        private static GameObject MakePanel(string name, Transform parent, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.color = color;
            img.raycastTarget = true;
            return go;
        }

        private static GameObject MakeTextGo(string name, Transform parent, Font font, int size, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var t = go.GetComponent<Text>();
            t.font = font; t.fontSize = size; t.color = color;
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.verticalOverflow   = VerticalWrapMode.Overflow;
            t.raycastTarget      = false;
            return go;
        }

        private static Text MakeSimpleText(Transform parent, Font font, int size, Color color, string text)
        {
            var go = new GameObject("Text", typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var r = go.GetComponent<RectTransform>();
            r.anchorMin = Vector2.zero; r.anchorMax = Vector2.one;
            r.offsetMin = r.offsetMax = Vector2.zero;
            var t = go.GetComponent<Text>();
            t.font = font; t.fontSize = size; t.color = color; t.text = text;
            t.alignment          = TextAnchor.MiddleLeft;
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.raycastTarget      = false;
            return t;
        }

        private static GameObject MakeButton(string name, Transform parent, string label,
                                             Color bg, Font font, int fontSize)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image), typeof(Button));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.color = bg;
            img.raycastTarget = true;
            var btn = go.GetComponent<Button>();
            btn.targetGraphic = img;
            var cb = btn.colors;
            cb.highlightedColor = new Color(bg.r + 0.12f, bg.g + 0.12f, bg.b + 0.12f);
            cb.pressedColor     = new Color(bg.r - 0.12f, bg.g - 0.12f, bg.b - 0.12f);
            cb.disabledColor    = new Color(bg.r * 0.5f, bg.g * 0.5f, bg.b * 0.5f, 0.6f);
            btn.colors = cb;
            var textGo = new GameObject("Label", typeof(RectTransform), typeof(Text));
            textGo.transform.SetParent(go.transform, false);
            var r = textGo.GetComponent<RectTransform>();
            r.anchorMin = Vector2.zero; r.anchorMax = Vector2.one;
            r.offsetMin = r.offsetMax = Vector2.zero;
            var t = textGo.GetComponent<Text>();
            t.font = font; t.fontSize = fontSize; t.color = Color.white;
            t.text = label; t.alignment = TextAnchor.MiddleCenter;
            t.raycastTarget = false;
            return go;
        }

        private static void SetAnchors(GameObject go, Vector2 min, Vector2 max,
            Vector2 offsetMin = default, Vector2 offsetMax = default)
        {
            var r = go.GetComponent<RectTransform>();
            r.anchorMin = min; r.anchorMax = max;
            r.offsetMin = offsetMin; r.offsetMax = offsetMax;
        }
    }
}
