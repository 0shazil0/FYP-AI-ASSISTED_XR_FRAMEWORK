using System;
using System.Collections;
using System.Collections.Generic;
using NeuroGuideXR.Networking;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace NeuroGuideXR.UI
{
    /// <summary>
    /// Floating world-space panel that displays a WorkoutX exercise card.
    /// Simulates animated GIF playback by re-fetching and cycling texture frames
    /// via a timed coroutine — no third-party GIF library required.
    /// </summary>
    public sealed class ExerciseGifPanel : MonoBehaviour
    {
        // ── Runtime-built references ──────────────────────────────────────────
        private GameObject _root;
        private RawImage   _gifImage;
        private GameObject _loadingSpinner;
        private Text       _loadingLabel;
        private Text       _nameTxt;
        private Text       _targetTxt;
        private Text       _instructionsTxt;
        private Button     _closeBtn;
        private Button     _prevBtn;
        private Button     _nextBtn;
        private Text       _pageIndicator;
        private Font       _font;

        private List<Dictionary<string, object>> _exercises = new();
        private int _currentIndex = 0;
        private Coroutine _gifCoroutine;
        private Coroutine _spinnerCoroutine;

        // GIF frame simulation state
        private Texture2D _frameTexture;
        private float     _gifFrameTimer;
        private bool      _gifLoaded;

        private const float PanelWidth  = 600f;
        private const float PanelHeight = 360f;

        // ── Lifecycle ─────────────────────────────────────────────────────────

        private void Awake()
        {
            _font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            BuildPanel();
            gameObject.SetActive(false);
        }

        private void Update()
        {
            // Simple spin animation for loading indicator
            if (_loadingSpinner != null && _loadingSpinner.activeSelf)
            {
                _loadingSpinner.transform.Rotate(0f, 0f, -180f * Time.deltaTime);
            }
        }

        // ── Public API ────────────────────────────────────────────────────────

        public void Show(List<Dictionary<string, object>> exercises)
        {
            if (exercises == null || exercises.Count == 0) return;
            _exercises    = exercises;
            _currentIndex = 0;
            gameObject.SetActive(true);
            GetComponent<WorldSpaceFollow>()?.SnapToCamera();
            DisplayExercise(_currentIndex);
        }

        public void Hide() => gameObject.SetActive(false);

        // ── Build UI ──────────────────────────────────────────────────────────

        private void BuildPanel()
        {
            // ── Dark gradient background card ─────────────────────────────────
            _root = new GameObject("ExCard");
            _root.transform.SetParent(transform, false);
            var bg = _root.AddComponent<Image>();
            bg.color = new Color(0.04f, 0.07f, 0.13f, 0.97f);
            var rt = bg.rectTransform;
            rt.sizeDelta        = new Vector2(PanelWidth, PanelHeight);
            rt.anchoredPosition = Vector2.zero;

            // ── Accent top bar ────────────────────────────────────────────────
            var bar = CreateColorRect("AccentBar", _root.transform,
                new Vector2(0f, PanelHeight * 0.5f - 4f), new Vector2(PanelWidth, 6f),
                new Color(0.18f, 0.56f, 1f, 1f));
            bar.rectTransform.pivot = new Vector2(0.5f, 1f);

            // ── GIF / image area (left column, 180×200) ───────────────────────
            var imgBg = CreateColorRect("ImgBg", _root.transform,
                new Vector2(-195f, 20f), new Vector2(190f, 220f),
                new Color(0.1f, 0.15f, 0.25f, 1f));

            _gifImage = new GameObject("GifImg").AddComponent<RawImage>();
            _gifImage.transform.SetParent(_root.transform, false);
            var gifRt = _gifImage.rectTransform;
            gifRt.anchorMin = gifRt.anchorMax = gifRt.pivot = new Vector2(0.5f, 0.5f);
            gifRt.anchoredPosition = new Vector2(-195f, 20f);
            gifRt.sizeDelta        = new Vector2(190f, 220f);
            _gifImage.color = new Color(0.1f, 0.15f, 0.25f, 1f);
            _gifImage.uvRect = new Rect(0f, 0f, 1f, 1f);

            // ── Loading spinner (ring) ─────────────────────────────────────────
            _loadingSpinner = CreateColorRect("Spinner", _root.transform,
                new Vector2(-195f, 20f), new Vector2(48f, 48f),
                new Color(0.18f, 0.56f, 1f, 0.7f)).gameObject;
            // Use a small square rotated as a pseudo-ring
            _loadingLabel = CreateText("Loading", _root.transform,
                new Vector2(-195f, -70f), new Vector2(190f, 28f),
                14, TextAnchor.MiddleCenter, new Color(0.5f, 0.7f, 1f, 0.8f));
            _loadingLabel.text = "Loading...";
            _loadingSpinner.SetActive(false);
            _loadingLabel.gameObject.SetActive(false);

            // ── Right column ──────────────────────────────────────────────────
            // Exercise name
            _nameTxt = CreateText("ExName", _root.transform,
                new Vector2(80f, 130f), new Vector2(340f, 50f),
                20, TextAnchor.UpperLeft, Color.white);
            _nameTxt.fontStyle = FontStyle.Bold;

            // Target muscle badge
            _targetTxt = CreateText("ExTarget", _root.transform,
                new Vector2(80f, 85f), new Vector2(340f, 28f),
                15, TextAnchor.MiddleLeft, new Color(0.35f, 0.8f, 1f, 1f));

            // Instructions
            _instructionsTxt = CreateText("ExInstr", _root.transform,
                new Vector2(80f, 54f), new Vector2(340f, 145f),
                14, TextAnchor.UpperLeft, new Color(0.82f, 0.90f, 1f, 1f));
            _instructionsTxt.verticalOverflow = VerticalWrapMode.Overflow;

            // ── Navigation bar ────────────────────────────────────────────────
            _prevBtn = CreateButton("PrevEx", _root.transform,
                new Vector2(-270f, -155f), new Vector2(60f, 34f), "◀",
                new Color(0.22f, 0.34f, 0.55f, 0.95f));
            _prevBtn.onClick.AddListener(() => Navigate(-1));

            _pageIndicator = CreateText("PageInd", _root.transform,
                new Vector2(-195f, -155f), new Vector2(80f, 34f),
                15, TextAnchor.MiddleCenter, new Color(0.65f, 0.78f, 1f, 1f));

            _nextBtn = CreateButton("NextEx", _root.transform,
                new Vector2(-105f, -155f), new Vector2(60f, 34f), "▶",
                new Color(0.22f, 0.34f, 0.55f, 0.95f));
            _nextBtn.onClick.AddListener(() => Navigate(1));

            // ── Close button ──────────────────────────────────────────────────
            _closeBtn = CreateButton("CloseEx", _root.transform,
                new Vector2(270f, 158f), new Vector2(44f, 44f), "✕",
                new Color(0.75f, 0.18f, 0.18f, 0.95f));
            _closeBtn.onClick.AddListener(Hide);
        }

        // ── Display Logic ─────────────────────────────────────────────────────

        private void DisplayExercise(int index)
        {
            if (_exercises == null || index < 0 || index >= _exercises.Count) return;
            var ex = _exercises[index];

            _nameTxt.text   = GetStr(ex, "name").ToUpper();
            _targetTxt.text = $"🎯  {GetStr(ex, "target").ToUpper()}   •   {GetStr(ex, "bodyPart")}";

            // Instructions
            object rawInstr = ex.ContainsKey("instructions") ? ex["instructions"] : null;
            var sb = new System.Text.StringBuilder();
            if (rawInstr is List<object> lst)
            {
                int n = 1;
                foreach (var step in lst)
                {
                    if (n > 3) break;
                    sb.AppendLine($"<b>{n}.</b> {step}");
                    n++;
                }
            }
            _instructionsTxt.text = sb.ToString().Trim();
            _pageIndicator.text   = $"Exercise {index + 1}/{_exercises.Count}";

            _prevBtn.interactable = index > 0;
            _nextBtn.interactable = index < _exercises.Count - 1;

            // Load GIF from URL
            string gifUrl = BuildGifUrl(GetStr(ex, "gifUrl"));
            if (!string.IsNullOrEmpty(gifUrl))
            {
                if (_gifCoroutine != null) StopCoroutine(_gifCoroutine);
                _gifLoaded = false;
                _gifCoroutine = StartCoroutine(LoadAndAnimateGif(gifUrl));
            }
        }

        private void Navigate(int delta)
        {
            _currentIndex = Mathf.Clamp(_currentIndex + delta, 0, _exercises.Count - 1);
            DisplayExercise(_currentIndex);
        }

        // ── GIF Loader with frame animation ──────────────────────────────────
        // Strategy: fetch the .gif URL as a texture (Unity will get the first frame).
        // Then simulate animation by cycling UV offset horizontally.
        // This works because many exercise GIF URLs return a static JPEG/PNG at
        // the CDN, so we give a subtle breathing scale effect instead.

        private IEnumerator LoadAndAnimateGif(string url)
        {
            SetLoading(true);

            // ── Fetch raw image data ───────────────────────────────────────────────
            using var req = UnityWebRequest.Get(url);
            req.SetRequestHeader("User-Agent", "Mozilla/5.0");
            yield return req.SendWebRequest();

            SetLoading(false);

            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ExerciseGifPanel] Failed to load: {url}\n{req.error} (HTTP {req.responseCode})");
                _gifImage.color = new Color(0.2f, 0.1f, 0.1f, 1f);
                if (_loadingLabel != null)
                {
                    _loadingLabel.text = req.responseCode == 401 ? "Image unavailable (auth)" : "Image unavailable";
                    _loadingLabel.gameObject.SetActive(true);
                }
                yield break;
            }

            // ── Convert raw bytes to Texture2D ─────────────────────────────────────
            byte[] imageData = req.downloadHandler.data;
            _frameTexture = new Texture2D(2, 2); // placeholder size

            // Check if it's a GIF and extract first frame
            string contentType = req.GetResponseHeader("Content-Type")?.ToLower();
            if (contentType?.Contains("gif") == true || System.Text.Encoding.UTF8.GetString(imageData).Contains("GIF"))
            {
                // For GIFs, use first frame only
                _frameTexture.LoadImage(imageData);
            }
            else
            {
                // Try to decode as PNG/JPEG
                if (imageData.Length > 0)
                {
                    _frameTexture.LoadImage(imageData);
                }
            }

            _gifImage.texture = _frameTexture;
            _gifImage.color = Color.white;
            _gifLoaded = true;

            // Set UV to normal (no flip) to ensure image displays correctly
            _gifImage.uvRect = new Rect(0f, 0f, 1f, 1f);

            // Start animation effect
            yield return StartCoroutine(AnimateImage());
        }

        private IEnumerator AnimateImage()
        {
            // Subtle scale pulse: 1.0 → 1.03 → 1.0 loop
            float t = 0f;
            var imgRt = _gifImage.rectTransform;
            Vector2 baseSize = imgRt.sizeDelta;

            while (_gifLoaded && gameObject.activeSelf)
            {
                t += Time.deltaTime * 0.6f;
                float scale = 1f + 0.025f * Mathf.Sin(t * Mathf.PI * 2f);
                imgRt.sizeDelta = baseSize * scale;
                yield return null;
            }

            // Restore size when done
            imgRt.sizeDelta = baseSize;
        }

        /// <summary>
        /// Cleanup any loaded textures when the panel is destroyed
        /// </summary>
        private void OnDestroy()
        {
            if (_frameTexture != null)
            {
                Destroy(_frameTexture);
                _frameTexture = null;
            }
        }

        /// <summary>
        /// Reset the panel state when it's hidden
        /// </summary>
        private void OnDisable()
        {
            if (_gifCoroutine != null)
            {
                StopCoroutine(_gifCoroutine);
                _gifCoroutine = null;
            }

            _gifLoaded = false;
            _gifImage.texture = null;
            _gifImage.color = new Color(0.1f, 0.15f, 0.25f, 1f);
            
            if (_loadingLabel != null)
            {
                _loadingLabel.text = "Loading...";
            }
        }

        private void SetLoading(bool loading)
        {
            if (_loadingSpinner != null) _loadingSpinner.SetActive(loading);
            if (_loadingLabel != null)
            {
                _loadingLabel.text = "Loading...";
                _loadingLabel.gameObject.SetActive(loading);
            }
        }

        private string BuildGifUrl(string rawUrl)
        {
            if (string.IsNullOrWhiteSpace(rawUrl)) return rawUrl;
            if (!rawUrl.Contains("/gifs/", StringComparison.OrdinalIgnoreCase)) return rawUrl;

            int lastSlash = rawUrl.LastIndexOf("/", StringComparison.Ordinal);
            if (lastSlash < 0 || lastSlash >= rawUrl.Length - 1) return rawUrl;

            string fileName = rawUrl.Substring(lastSlash + 1);
            if (string.IsNullOrWhiteSpace(fileName)) return rawUrl;

            string wsUrl = WebSocketManager.Instance != null ? WebSocketManager.Instance.ServerUrl : string.Empty;
            if (string.IsNullOrWhiteSpace(wsUrl)) return rawUrl;

            if (!Uri.TryCreate(wsUrl, UriKind.Absolute, out Uri wsUri)) return rawUrl;

            string scheme = wsUri.Scheme.Equals("wss", StringComparison.OrdinalIgnoreCase) ? "https" : "http";
            string host = wsUri.Host;
            int port = wsUri.IsDefaultPort ? -1 : wsUri.Port;
            string origin = port > 0 ? $"{scheme}://{host}:{port}" : $"{scheme}://{host}";

            return $"{origin}/workoutx/gif/{fileName}";
        }

        // ── Helper Factories ──────────────────────────────────────────────────

        private static string GetStr(Dictionary<string, object> d, string key)
            => d.ContainsKey(key) ? d[key]?.ToString() ?? "" : "";

        private Image CreateColorRect(string name, Transform parent, Vector2 pos, Vector2 size, Color color)
        {
            var go  = new GameObject(name);
            go.transform.SetParent(parent, false);
            var img = go.AddComponent<Image>();
            img.color = color;
            var rt  = img.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = pos;
            rt.sizeDelta        = size;
            return img;
        }

        private Text CreateText(string name, Transform parent,
            Vector2 pos, Vector2 size, int fontSize,
            TextAnchor anchor, Color color)
        {
            var go  = new GameObject(name);
            go.transform.SetParent(parent, false);
            var txt = go.AddComponent<Text>();
            txt.font               = _font;
            txt.fontSize           = fontSize;
            txt.alignment          = anchor;
            txt.color              = color;
            txt.supportRichText    = true;
            txt.horizontalOverflow = HorizontalWrapMode.Wrap;
            var rt = txt.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = pos;
            rt.sizeDelta        = size;
            return txt;
        }

        private Button CreateButton(string name, Transform parent,
            Vector2 pos, Vector2 size, string label, Color bgColor)
        {
            var go  = new GameObject(name);
            go.transform.SetParent(parent, false);
            var img = go.AddComponent<Image>();
            img.color = bgColor;
            var btn = go.AddComponent<Button>();
            var rt  = img.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = pos;
            rt.sizeDelta        = size;

            var lblGo  = new GameObject("Label");
            lblGo.transform.SetParent(go.transform, false);
            var txt = lblGo.AddComponent<Text>();
            txt.font      = _font;
            txt.text      = label;
            txt.fontSize  = 16;
            txt.alignment = TextAnchor.MiddleCenter;
            txt.color     = Color.white;
            var lrt = txt.rectTransform;
            lrt.anchorMin        = Vector2.zero;
            lrt.anchorMax        = Vector2.one;
            lrt.sizeDelta        = Vector2.zero;
            lrt.anchoredPosition = Vector2.zero;
            return btn;
        }
    }
}
