// Assets/Scripts/UI/ModeSelectUI.cs
// App launch screen — two large buttons to choose between the two modes.
// Builds itself entirely at runtime (no prefab). Very first scene the user sees.
//
// FIX: (1) Creates EventSystem if missing — buttons need it for click routing.
//      (2) All decorative child elements have raycastTarget=false so they don't
//          consume touch events before the Button component receives them.

using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using UnityEngine.EventSystems;

namespace NeuroGuideXR.UI
{
    public sealed class ModeSelectUI : MonoBehaviour
    {
        [Header("Scene Names")]
        [SerializeField] private string liveSceneName    = "SampleScene";
        [SerializeField] private string copilotSceneName = "CopilotAR";

        private const string ProjectTitle    = "NeuroGuide XR";
        private const string ProjectSubtitle = "AI-Powered Spatial Assistance";

        private void Start() => BuildUI();

        private void BuildUI()
        {
            // ── EventSystem (REQUIRED) ────────────────────────────────────
            // GraphicRaycaster cannot route clicks to Buttons without this.
            if (EventSystem.current == null)
            {
                var esGo = new GameObject("EventSystem");
                esGo.AddComponent<EventSystem>();
#if ENABLE_INPUT_SYSTEM
                // Use the new Input System module if the project is configured for it (common in XR)
                esGo.AddComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>();
#else
                esGo.AddComponent<StandaloneInputModule>();
#endif
            }

            // ── Canvas ────────────────────────────────────────────────────
            var canvasGo = new GameObject("ModeCanvas",
                typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            var canvas = canvasGo.GetComponent<Canvas>();
            canvas.renderMode   = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 100;

            var scaler = canvasGo.GetComponent<CanvasScaler>();
            scaler.uiScaleMode        = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080, 1920);
            scaler.screenMatchMode     = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight  = 0.5f;

            var font = Resources.GetBuiltinResource<Font>("Arial.ttf");

            // ── Background ────────────────────────────────────────────────
            var bg = CreatePanel("Background", canvas.transform, new Color(0.04f, 0.05f, 0.09f), false);
            FillParent(bg);

            // Top decorative band
            var topBand = CreatePanel("TopBand", bg.transform, new Color(0.08f, 0.15f, 0.32f, 0.6f), false);
            var topRect = topBand.GetComponent<RectTransform>();
            topRect.anchorMin = new Vector2(0, 0.72f);
            topRect.anchorMax = new Vector2(1, 1);
            topRect.offsetMin = topRect.offsetMax = Vector2.zero;

            // Logo circle
            var logoGo   = CreatePanel("LogoRing", bg.transform, new Color(0.12f, 0.42f, 0.92f), false);
            var logoRect = logoGo.GetComponent<RectTransform>();
            logoRect.anchorMin = new Vector2(0.35f, 0.825f);
            logoRect.anchorMax = new Vector2(0.65f, 0.935f);
            logoRect.offsetMin = logoRect.offsetMax = Vector2.zero;

            var logoLbl = CreateText("N", bg.transform, font, 100, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter, false);
            var llRect  = logoLbl.GetComponent<RectTransform>();
            llRect.anchorMin = new Vector2(0.35f, 0.825f);
            llRect.anchorMax = new Vector2(0.65f, 0.935f);
            llRect.offsetMin = llRect.offsetMax = Vector2.zero;

            // Title
            var titleLbl = CreateText(ProjectTitle, bg.transform, font, 82, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter, false);
            var titRect  = titleLbl.GetComponent<RectTransform>();
            titRect.anchorMin = new Vector2(0.05f, 0.74f);
            titRect.anchorMax = new Vector2(0.95f, 0.825f);
            titRect.offsetMin = titRect.offsetMax = Vector2.zero;

            // Subtitle
            var subLbl  = CreateText(ProjectSubtitle, bg.transform, font, 36, new Color(0.7f, 0.80f, 1f), FontStyle.Normal, TextAnchor.MiddleCenter, false);
            var subRect = subLbl.GetComponent<RectTransform>();
            subRect.anchorMin = new Vector2(0.05f, 0.70f);
            subRect.anchorMax = new Vector2(0.95f, 0.745f);
            subRect.offsetMin = subRect.offsetMax = Vector2.zero;

            // Divider
            var divider = CreatePanel("Divider", bg.transform, new Color(0.25f, 0.4f, 0.75f, 0.4f), false);
            var divRect = divider.GetComponent<RectTransform>();
            divRect.anchorMin = new Vector2(0.1f, 0.685f);
            divRect.anchorMax = new Vector2(0.9f, 0.690f);
            divRect.offsetMin = divRect.offsetMax = Vector2.zero;

            // "Choose Your Mode"
            var chooseLbl  = CreateText("Choose Your Mode", bg.transform, font, 44, new Color(0.55f, 0.65f, 0.85f), FontStyle.Normal, TextAnchor.MiddleCenter, false);
            var chooseRect = chooseLbl.GetComponent<RectTransform>();
            chooseRect.anchorMin = new Vector2(0.05f, 0.63f);
            chooseRect.anchorMax = new Vector2(0.95f, 0.68f);
            chooseRect.offsetMin = chooseRect.offsetMax = Vector2.zero;

            // ── Buttons ───────────────────────────────────────────────────
            CreateModeButton(
                parent:      bg.transform, font: font,
                icon:        "[AR]",
                title:       "Live Scene Assistance",
                subtitle:    "Point & guide in the real world",
                bgColor:     new Color(0.08f, 0.38f, 0.82f),
                accentColor: new Color(0.15f, 0.55f, 0.98f),
                anchorMin:   new Vector2(0.06f, 0.41f),
                anchorMax:   new Vector2(0.94f, 0.61f),
                onClick:     () => SceneManager.LoadScene(liveSceneName)
            );

            CreateModeButton(
                parent:      bg.transform, font: font,
                icon:        "[AI]",
                title:       "Software UI Assistance",
                subtitle:    "AR copilot for PC applications",
                bgColor:     new Color(0.06f, 0.48f, 0.28f),
                accentColor: new Color(0.10f, 0.70f, 0.40f),
                anchorMin:   new Vector2(0.06f, 0.19f),
                anchorMax:   new Vector2(0.94f, 0.39f),
                onClick:     () => SceneManager.LoadScene(copilotSceneName)
            );

            // Footer
            var footLbl  = CreateText("FYP  |  NeuroGuide XR  |  v2.0", bg.transform, font, 24,
                new Color(0.35f, 0.40f, 0.55f), FontStyle.Normal, TextAnchor.MiddleCenter, false);
            var footRect = footLbl.GetComponent<RectTransform>();
            footRect.anchorMin = new Vector2(0.05f, 0.02f);
            footRect.anchorMax = new Vector2(0.95f, 0.07f);
            footRect.offsetMin = footRect.offsetMax = Vector2.zero;
        }

        // ── Button factory ────────────────────────────────────────────────
        private static void CreateModeButton(
            Transform parent, Font font,
            string icon, string title, string subtitle,
            Color bgColor, Color accentColor,
            Vector2 anchorMin, Vector2 anchorMax,
            System.Action onClick)
        {
            // Card image = the ONLY raycast target in this button
            var card     = new GameObject("Btn_" + title, typeof(RectTransform), typeof(Image), typeof(Button));
            card.transform.SetParent(parent, false);
            var cardRect = card.GetComponent<RectTransform>();
            cardRect.anchorMin = anchorMin;
            cardRect.anchorMax = anchorMax;
            cardRect.offsetMin = cardRect.offsetMax = Vector2.zero;

            var img = card.GetComponent<Image>();
            img.color         = bgColor;
            img.raycastTarget = true;  // Button hit-target

            var btn = card.GetComponent<Button>();
            btn.targetGraphic = img;
            var cb = btn.colors;
            cb.normalColor      = bgColor;
            cb.highlightedColor = accentColor;
            cb.pressedColor     = new Color(bgColor.r * 0.7f, bgColor.g * 0.7f, bgColor.b * 0.7f);
            btn.colors = cb;
            btn.onClick.AddListener(() => onClick?.Invoke());

            // Accent bar (left strip) — NOT a raycast target
            var accentGo   = new GameObject("Accent", typeof(RectTransform), typeof(Image));
            accentGo.transform.SetParent(card.transform, false);
            var accentRect = accentGo.GetComponent<RectTransform>();
            accentRect.anchorMin = new Vector2(0f, 0f);
            accentRect.anchorMax = new Vector2(0.012f, 1f);
            accentRect.offsetMin = accentRect.offsetMax = Vector2.zero;
            var accentImg = accentGo.GetComponent<Image>();
            accentImg.color         = accentColor;
            accentImg.raycastTarget = false;  // decorative only

            // Icon text
            var iconGo = CreateText(icon, card.transform, font, 58, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter, false);
            var iconR  = iconGo.GetComponent<RectTransform>();
            iconR.anchorMin = new Vector2(0.02f, 0.15f);
            iconR.anchorMax = new Vector2(0.22f, 0.85f);
            iconR.offsetMin = iconR.offsetMax = Vector2.zero;

            // Title text
            var titleGo = CreateText(title, card.transform, font, 46, Color.white, FontStyle.Bold, TextAnchor.LowerLeft, false);
            var titR    = titleGo.GetComponent<RectTransform>();
            titR.anchorMin = new Vector2(0.23f, 0.52f);
            titR.anchorMax = new Vector2(0.97f, 0.92f);
            titR.offsetMin = titR.offsetMax = Vector2.zero;

            // Subtitle text
            var subGo = CreateText(subtitle, card.transform, font, 32, new Color(0.8f, 0.9f, 1f, 0.8f), FontStyle.Normal, TextAnchor.UpperLeft, false);
            var subR  = subGo.GetComponent<RectTransform>();
            subR.anchorMin = new Vector2(0.23f, 0.12f);
            subR.anchorMax = new Vector2(0.97f, 0.50f);
            subR.offsetMin = subR.offsetMax = Vector2.zero;
        }

        // ── Helpers ───────────────────────────────────────────────────────
        private static GameObject CreatePanel(string name, Transform parent, Color color, bool raycast = true)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.color         = color;
            img.raycastTarget = raycast;
            return go;
        }

        private static GameObject CreateText(string text, Transform parent, Font font,
            int size, Color color, FontStyle style, TextAnchor anchor, bool raycast)
        {
            var go = new GameObject("Txt_" + text.Substring(0, Mathf.Min(text.Length, 12)),
                typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var t = go.GetComponent<Text>();
            t.text             = text;
            t.font             = font;
            t.fontSize         = size;
            t.color            = color;
            t.fontStyle        = style;
            t.alignment        = anchor;
            t.raycastTarget    = raycast;   // always set explicitly
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.verticalOverflow   = VerticalWrapMode.Overflow;
            return go;
        }

        private static void FillParent(GameObject go)
        {
            var r = go.GetComponent<RectTransform>();
            r.anchorMin = Vector2.zero;
            r.anchorMax = Vector2.one;
            r.offsetMin = r.offsetMax = Vector2.zero;
        }
    }
}
