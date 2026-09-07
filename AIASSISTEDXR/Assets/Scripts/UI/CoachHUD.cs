using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace NeuroGuideXR.UI
{
    /// <summary>
    /// Persistent HUD overlay that shows Coach Marcus branding + a pulse indicator
    /// when YOLO detects a gym machine. Attaches to the same Canvas as SnapDemoUI.
    /// Creates itself — no scene setup required.
    /// </summary>
    [RequireComponent(typeof(Canvas))]
    public sealed class CoachHUD : MonoBehaviour
    {
        // ── State ─────────────────────────────────────────────────────────────
        private Text       _statusDot;
        private Image      _pulseRing;
        private Image      _scanLine;
        private Text       _machineTag;
        private GameObject _machineTagRoot;
        private Font       _font;
        private Coroutine  _pulseCoroutine;
        private Coroutine  _tagCoroutine;

        private static readonly Color ColLive = new Color(0.22f, 0.95f, 0.55f, 1f);

        // ── Singleton accessor ────────────────────────────────────────────────
        private static CoachHUD _instance;
        public  static CoachHUD Instance => _instance;

        // ── Lifecycle ─────────────────────────────────────────────────────────

        private void Awake()
        {
            _instance = this;
            _font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            Build();
        }

        // ── Build ─────────────────────────────────────────────────────────────

        private void Build()
        {
            var canvas = GetComponent<Canvas>();
            var canvasRt = canvas.GetComponent<RectTransform>();

            // ── Coach name badge (top-left corner) ────────────────────────────
            var badgeGo = new GameObject("CoachBadge", typeof(RectTransform), typeof(Image));
            badgeGo.transform.SetParent(canvasRt, false);
            var badgeRt = badgeGo.GetComponent<RectTransform>();
            badgeRt.anchorMin = new Vector2(0f, 1f);
            badgeRt.anchorMax = new Vector2(0f, 1f);
            badgeRt.pivot     = new Vector2(0f, 1f);
            badgeRt.anchoredPosition = new Vector2(12f, -12f);
            badgeRt.sizeDelta        = new Vector2(288f, 48f);
            badgeGo.GetComponent<Image>().color = new Color(0.04f, 0.09f, 0.18f, 0.88f);

            // Green live dot
            _statusDot = MakeText("LiveDot", badgeGo.transform,
                new Vector2(24f, -24f), new Vector2(22f, 28f), 22,
                TextAnchor.MiddleCenter, ColLive);
            _statusDot.text = "●";
            StartCoroutine(BlinkDot());

            // "COACH MARCUS" label
            var nameLabel = MakeText("CoachName", badgeGo.transform,
                new Vector2(52f, -24f), new Vector2(228f, 30f), 18,
                TextAnchor.MiddleLeft, Color.white);
            nameLabel.text      = "COACH MARCUS";
            nameLabel.fontStyle = FontStyle.Bold;

            // ── Scan-line (full-width slow sweep top→bottom) ───────────────────
            var scanGo = new GameObject("ScanLine", typeof(RectTransform), typeof(Image));
            scanGo.transform.SetParent(canvasRt, false);
            var scanRt = scanGo.GetComponent<RectTransform>();
            scanRt.anchorMin = new Vector2(0f, 1f);
            scanRt.anchorMax = new Vector2(1f, 1f);
            scanRt.pivot     = new Vector2(0.5f, 1f);
            scanRt.anchoredPosition = Vector2.zero;
            scanRt.sizeDelta        = new Vector2(0f, 3f);
            _scanLine = scanGo.GetComponent<Image>();
            _scanLine.color = new Color(0.25f, 0.7f, 1f, 0.14f);
            StartCoroutine(AnimateScanLine(canvasRt));

            // ── Machine detection tag (top-centre, hidden by default) ──────────
            _machineTagRoot = new GameObject("MachineTag", typeof(RectTransform), typeof(Image));
            _machineTagRoot.transform.SetParent(canvasRt, false);
            var tagRt = _machineTagRoot.GetComponent<RectTransform>();
            tagRt.anchorMin = new Vector2(0.5f, 1f);
            tagRt.anchorMax = new Vector2(0.5f, 1f);
            tagRt.pivot     = new Vector2(0.5f, 1f);
            tagRt.anchoredPosition = new Vector2(0f, -68f);
            tagRt.sizeDelta        = new Vector2(400f, 52f);
            _machineTagRoot.GetComponent<Image>().color = new Color(0.06f, 0.22f, 0.10f, 0.94f);

            // Pulse dot inside tag
            var pulsGo = new GameObject("PulseDot", typeof(RectTransform), typeof(Image));
            pulsGo.transform.SetParent(_machineTagRoot.transform, false);
            var pulsRt = pulsGo.GetComponent<RectTransform>();
            pulsRt.anchorMin = pulsRt.anchorMax = pulsRt.pivot = new Vector2(0f, 0.5f);
            pulsRt.anchoredPosition = new Vector2(16f, 0f);
            pulsRt.sizeDelta        = new Vector2(22f, 22f);
            _pulseRing = pulsGo.GetComponent<Image>();
            _pulseRing.color = ColLive;

            _machineTag = MakeText("MachineLabel", _machineTagRoot.transform,
                new Vector2(46f, -26f), new Vector2(340f, 42f), 18,
                TextAnchor.MiddleLeft, new Color(0.5f, 1f, 0.65f, 1f));
            _machineTag.text      = "Machine Detected";
            _machineTag.fontStyle = FontStyle.Bold;
            _machineTagRoot.SetActive(false);
        }

        // ── Public API ────────────────────────────────────────────────────────

        /// <summary>Call when YOLO / LLM detects a machine.</summary>
        public void ShowMachineDetected(string machineName, float dismissAfterSeconds = 8f)
        {
            if (_machineTagRoot == null) return;
            _machineTag.text = $"⚡  {machineName.ToUpper()}  DETECTED";
            _machineTagRoot.SetActive(true);

            if (_pulseCoroutine != null) StopCoroutine(_pulseCoroutine);
            _pulseCoroutine = StartCoroutine(PulseRing(dismissAfterSeconds));

            if (_tagCoroutine != null) StopCoroutine(_tagCoroutine);
            _tagCoroutine = StartCoroutine(DismissTagAfter(dismissAfterSeconds));
        }

        // ── Coroutines ────────────────────────────────────────────────────────

        private IEnumerator BlinkDot()
        {
            while (true)
            {
                yield return new WaitForSeconds(1.4f);
                if (_statusDot)
                {
                    _statusDot.color = new Color(ColLive.r, ColLive.g, ColLive.b, 0.22f);
                    yield return new WaitForSeconds(0.3f);
                    _statusDot.color = ColLive;
                }
            }
        }

        private IEnumerator PulseRing(float duration)
        {
            float elapsed = 0f;
            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t     = Mathf.PingPong(elapsed * 2.2f, 1f);
                float scale = Mathf.Lerp(0.7f, 1.6f, t);
                float alpha = Mathf.Lerp(1f,   0f,   t);
                if (_pulseRing)
                {
                    _pulseRing.transform.localScale = Vector3.one * scale;
                    _pulseRing.color = new Color(ColLive.r, ColLive.g, ColLive.b, alpha);
                }
                yield return null;
            }
        }

        private IEnumerator DismissTagAfter(float seconds)
        {
            yield return new WaitForSeconds(seconds);
            if (_machineTagRoot) _machineTagRoot.SetActive(false);
        }

        private IEnumerator AnimateScanLine(RectTransform canvasRt)
        {
            var rt = _scanLine.rectTransform;
            while (true)
            {
                float duration = 7f;
                float h = canvasRt.sizeDelta.y > 0 ? canvasRt.sizeDelta.y : 1920f;
                for (float t = 0f; t < duration; t += Time.deltaTime)
                {
                    rt.anchoredPosition = new Vector2(0f, -h * (t / duration));
                    yield return null;
                }
                yield return new WaitForSeconds(1.5f);
            }
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private Text MakeText(string name, Transform parent,
            Vector2 pos, Vector2 size, int fontSize,
            TextAnchor anchor, Color color)
        {
            var go  = new GameObject(name);
            go.transform.SetParent(parent, false);
            var txt = go.AddComponent<Text>();
            txt.font            = _font;
            txt.fontSize        = fontSize;
            txt.alignment       = anchor;
            txt.color           = color;
            txt.supportRichText = true;
            var rt = txt.rectTransform;
            rt.anchorMin        = new Vector2(0f, 0f);
            rt.anchorMax        = new Vector2(0f, 0f);
            rt.pivot            = new Vector2(0f, 0.5f);
            rt.anchoredPosition = pos;
            rt.sizeDelta        = size;
            return txt;
        }
    }
}
